"""The scan pipeline: image -> SAM 3.1 regions -> Muse Spark reading -> safety (code) -> Matrix hospitals.

Nothing here is stored. The image lives only in memory for the length of the request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import grounding, imaging, meta_client, safety, segment, understand
from .schemas import Extraction

log = logging.getLogger("vision.pipeline")

DISCLAIMER = {
    "ne": "यो एप कागजात बुझ्न मद्दत गर्न मात्र हो। यसले रोग पत्ता लगाउँदैन र औषधि वा मात्रा परिवर्तन गर्न भन्दैन। "
          "आफ्नो डाक्टरसँग सधैं सोध्नुहोस्। आपत्कालमा १०२ मा फोन गर्नुहोस्।",
    "en": "This app only helps you understand your document. It does not diagnose and never tells you to change a "
          "medicine or dose. Always check with your doctor. In an emergency, call 102.",
}


class PipelineError(Exception):
    """A step failed; `safety` is still returned so an emergency is never hidden."""

    def __init__(self, status: int, code: str, message: str, safety_result: dict):
        super().__init__(message)
        self.status, self.code, self.safety = status, code, safety_result


@dataclass
class Options:
    note: str = ""
    lang: str = "ne"
    district: str | None = None


def _fail(exc: Exception, check: dict, what: str) -> PipelineError:
    if isinstance(exc, meta_client.NotConfigured):
        return PipelineError(503, "ai_not_configured", "The reading service is not set up yet.", check)
    busy = meta_client.is_busy(exc)
    log.warning("%s failed: %s", what, type(exc).__name__)
    return PipelineError(503 if busy else 502, "ai_busy" if busy else "ai_failed",
                         "The reading service is busy. Please try again in a minute." if busy
                         else "We could not read this document right now. Please try again.", check)


def document_words(ext: Extraction) -> list[str]:
    """The document's own words (not the model's explanations) for the safety rules."""
    words = [ext.document_text]
    words += [f"{i.name} {i.value} {i.unit or ''}" for i in ext.items]
    words += [f.text for f in ext.findings]
    words += [m.name for m in ext.medicines]
    return words


def _ground_extraction(ext: Extraction, allowed: list[dict], directory: list[dict]) -> dict:
    data = ext.model_dump()
    text_keys = ("summary_ne", "summary_en", "department_reason_ne", "department_reason_en",
                 "questions_for_doctor_ne", "questions_for_doctor_en")
    for k in text_keys:
        data[k] = grounding.ground(data[k], allowed, directory)
    for coll in ("items", "medicines", "findings"):
        for x in data[coll]:
            for k in ("explanation_ne", "explanation_en"):
                x[k] = grounding.ground(x[k], allowed, directory)
    return data


def run(image_bytes: bytes, opts: Options) -> dict:
    # Safety first, on what we already have, so it can be returned whatever fails later.
    check = safety.check_document(opts.note)
    try:
        prepared = imaging.prepare(image_bytes)
    except imaging.BadImage as exc:
        status = 413 if exc.code == "too_large" else 400
        raise PipelineError(status, exc.code, str(exc), check) from exc

    try:
        cls, _ = understand.classify(prepared)
    except Exception as exc:
        raise _fail(exc, check, "classify") from exc
    if not cls.is_medical_document or cls.document_type == "not_medical":
        raise PipelineError(422, "not_document", "This does not look like a prescription, lab report or X-ray.", check)
    if not cls.readable:
        raise PipelineError(422, "unreadable", "The photo is too blurry or dark to read. Please take it again in good light.", check)

    regions = segment.segment(prepared, cls.document_type)
    departments = grounding.departments()
    try:
        ext, model = understand.extract(prepared, regions, segment.crops(prepared, regions), departments, opts.note)
    except Exception as exc:
        raise _fail(exc, check, "extract") from exc

    check = safety.check_document(opts.note, *document_words(ext), items=[i.model_dump() for i in ext.items])
    urgency = "emergency" if check["is_emergency"] else ext.urgency

    dept = ext.suggested_department
    found = grounding.hospitals_for(dept, opts.district, opts.lang)
    emergency = grounding.hospitals_for("emergency", opts.district, opts.lang) if urgency == "emergency" else None
    allowed = found["hospitals"] + (emergency["hospitals"] if emergency else [])
    data = _ground_extraction(ext, allowed, grounding.all_hospitals())
    dinfo = departments.get(dept, {})

    return {
        "document_type": data["document_type"],
        "regions": [r.public(i) for i, r in enumerate(regions) if r.linkable],
        "items": data["items"],
        "medicines": data["medicines"],
        "findings": data["findings"],
        "summary": {"ne": data["summary_ne"], "en": data["summary_en"]},
        "questions_for_doctor": {"ne": data["questions_for_doctor_ne"], "en": data["questions_for_doctor_en"]},
        "unreadable_parts": data["unreadable_parts"],
        "abnormal_count": len(understand.abnormal_items(ext)),
        "department": {"id": dept, "ne": dinfo.get("ne", ""), "en": dinfo.get("en", dept),
                       "reason": {"ne": data["department_reason_ne"], "en": data["department_reason_en"]}},
        "urgency": urgency,
        "safety": check,
        "hospitals": found,
        "emergency_hospitals": emergency,
        "disclaimer": DISCLAIMER,
        # Kept by the browser for follow-up questions (the image itself is not).
        "context": {"document_text": ext.document_text},
        "model": model,
    }
