"""Muse Spark: read the document and explain it in simple Nepali and English (structured output).

The model explains; code decides. Abnormal flags are recomputed from the printed reference range where
possible, the department must be one of Matrix's, and safety/urgency is decided in safety.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import config, imaging, meta_client
from .schemas import (ANSWER_SCHEMA, CLASSIFY_SCHEMA, Answer, Classification, Extraction, Item,
                      extraction_schema)
from .segment import Region

log = logging.getLogger("vision.spark")

RULES = """Rules you must follow:
- You EXPLAIN what is written. You never diagnose, never say what disease the person has, and never
  suggest starting, stopping or changing any medicine or dose. Copy doses exactly as written.
- If something is unclear or cut off, say so in unreadable_parts; never guess numbers or medicine names.
- Do not name any hospital, clinic or doctor. The app adds verified hospitals itself.
- Nepali must be simple, everyday Nepali in Devanagari that a person with little schooling understands.
  Keep medical words in English in brackets the first time, e.g. "हेमोग्लोबिन (Haemoglobin)".
- The person should always confirm with the doctor who wrote or ordered the document."""

CLASSIFY_PROMPT = """Look at this photo. Is it a medical document a patient might have: a lab/test report,
a prescription, an X-ray/CT/MRI film or its report, or another medical paper (discharge summary, etc.)?
Selfies, scenery, ID cards, bills and anything else are not_medical. readable is false if the photo is
too blurry, dark or cut off to read."""

EXTRACT_PROMPT = """You are helping a patient in Nepal understand a medical document.
The first image is the whole photo. Further images are close-ups, each labelled. When a close-up has a region
id (such as r0), use it to say which items, medicines or findings are in it; otherwise region_id is null.

Fill in:
- document_text: the document's important printed/handwritten words as written (tests, values, medicines,
  impressions), in reading order. Leave out patient name, address, phone and ID numbers.
- items: every test result (name, value, unit, reference range as printed, flag high/low/abnormal/normal,
  unknown if no range). explanation_*: one or two short sentences on what the test measures and what
  this result means in general, without diagnosing.
- medicines: every medicine with strength, dose, frequency (e.g. "1-0-1", "BD"), timing (before/after
  food), duration exactly as written. explanation_*: how to take it in plain words, and what it is
  generally used for.
- findings: for imaging or report impressions, each finding as written, explained simply. For an X-ray
  film without a written report, describe only what kind of image it is (body part, view) and say that a
  doctor's written report is needed; do not interpret the image.
- summary_*: 3 to 5 short sentences for the patient.
- suggested_department: which hospital department usually handles follow-up for this document.
- urgency: emergency only if the document itself marks something critical; soon if results are clearly
  out of range; otherwise routine.
- questions_for_doctor_*: up to 4 useful questions the patient could ask their doctor.

{rules}

Departments (id: meaning): {departments}
{note}"""

ANSWER_PROMPT = """A patient in Nepal is asking about their medical document. Answer in simple Nepali
(answer_ne) and English (answer_en), in at most 4 short sentences, using only what the document says.
question_understood_ne: the question as you understood it, written in correct Nepali. Spoken questions
come from speech recognition that does not know Nepali, so they may be written as Hindi or misspelled;
read them as Nepali.
region_ids: the ids of the regions your answer is about (may be empty).
If the question asks for a diagnosis, a dose change, or anything the document does not say, gently
say you can only explain the document and that their doctor should answer.

{rules}

The document, as already read (JSON):
{document}

Hospitals the patient can be pointed to (only these may be named):
{hospitals}

Question ({source}): {question}"""


# ------------------------------------------------------------------ calls


def _image(url: str) -> dict:
    return {"type": "input_image", "image_url": url}


def _respond(model: str, content: list[dict], schema: dict, name: str, effort: str, max_tokens: int) -> str:
    resp = meta_client.client().responses.create(
        model=model,
        input=[{"type": "message", "role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        reasoning={"effort": effort},
        max_output_tokens=max_tokens,
        store=False,  # don't keep the patient's document on Meta's side
    )
    if getattr(resp, "status", None) == "incomplete":
        # Reasoning tokens count toward max_output_tokens, so a cut-off answer is not valid JSON.
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
        raise ValueError(f"{model} response incomplete: {reason}")
    return meta_client.output_text(resp)


def parse_json(text: str) -> dict:
    """Model JSON, tolerating a ```json fence or text around one object. Raises ValueError."""
    t = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if fence:
        t = fence.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model did not return JSON") from None
        data = json.loads(t[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("model JSON is not an object")
    return data


def classify(prepared: imaging.Prepared) -> tuple[Classification, str]:
    content = [{"type": "input_text", "text": CLASSIFY_PROMPT}, _image(prepared.data_url())]

    def run(model: str) -> Classification:
        return Classification.model_validate(parse_json(_respond(model, content, CLASSIFY_SCHEMA, "classify", "low", 1500)))

    return meta_client.call_with_fallback(config.MUSE_SPARK_MODELS, run)


def extract(prepared: imaging.Prepared, regions: list[Region], crops: list[bytes], departments: dict[str, dict],
            note: str = "") -> tuple[Extraction, str]:
    dep_lines = "; ".join(f"{k}: {v.get('en', k)}" for k, v in departments.items())
    prompt = EXTRACT_PROMPT.format(rules=RULES, departments=dep_lines,
                                   note=f"The patient added this note: {note!r}" if note else "")
    content: list[dict] = [{"type": "input_text", "text": prompt}, _image(prepared.data_url())]
    for i, (r, jpeg) in enumerate(zip(regions, crops)):
        label = f"Region r{i} ({r.concept}):" if r.linkable else "Close-up of the paper (not a region; read it, don't cite it):"
        content.append({"type": "input_text", "text": label})
        content.append(_image(imaging.to_data_url(jpeg)))
    schema = extraction_schema(list(departments))

    def run(model: str) -> Extraction:
        return finalize(parse_json(_respond(model, content, schema, "document", "medium", 8000)), departments,
                        {f"r{i}" for i, r in enumerate(regions) if r.linkable})

    return meta_client.call_with_fallback(config.MUSE_SPARK_MODELS, run)


def answer(question: str, document: dict, hospitals: list[dict], spoken: bool = False) -> tuple[Answer, str]:
    hosp = "\n".join(f"- {h.get('name')} / {h.get('name_ne')} ({h.get('district')})" for h in hospitals) or "(none)"
    prompt = ANSWER_PROMPT.format(rules=RULES, document=json.dumps(document, ensure_ascii=False)[:30000],
                                  hospitals=hosp, question=question,
                                  source="spoken, from speech recognition" if spoken else "typed")

    def run(model: str) -> Answer:
        return Answer.model_validate(parse_json(_respond(model, [{"type": "input_text", "text": prompt}],
                                                         ANSWER_SCHEMA, "answer", "low", 3000)))

    return meta_client.call_with_fallback(config.MUSE_SPARK_MODELS, run)


# ------------------------------------------------------------------ checks done in code

_NUM = r"(-?\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"^\s*{_NUM}\s*(?:-|–|—|to)\s*{_NUM}\s*$", re.I)
_BELOW = re.compile(rf"^\s*(?:<|<=|≤|less than|below|up ?to)\s*{_NUM}\s*$", re.I)
_ABOVE = re.compile(rf"^\s*(?:>|>=|≥|more than|above|greater than)\s*{_NUM}\s*$", re.I)
_VALUE = re.compile(rf"^\s*{_NUM}\s*$")


def _clean_num(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", s or "")


def flag_from_range(value: str, reference_range: str | None) -> str | None:
    """high/low/normal if the value and range are plain numbers; None if they can't be compared safely."""
    if not reference_range:
        return None
    v = _VALUE.match(_clean_num(value))
    if not v:
        return None
    x = float(v.group(1))
    rr = _clean_num(reference_range)
    rr = re.sub(r"\s*[a-zA-Zµμ%/^*×³]+[a-zA-Z0-9µμ%/^*×³.]*\s*$", "", rr)  # trailing unit: "mg/dL", "fL", "x10^3/uL"
    if m := _RANGE.match(rr):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            return None
        return "low" if x < lo else "high" if x > hi else "normal"
    if m := _BELOW.match(rr):
        return "high" if x > float(m.group(1)) else "normal"
    if m := _ABOVE.match(rr):
        return "low" if x < float(m.group(1)) else "normal"
    return None


def finalize(raw: dict, departments: dict[str, Any], valid_regions: set[str]) -> Extraction:
    ext = Extraction.model_validate(raw)
    for coll in (ext.items, ext.medicines, ext.findings):
        for x in coll:
            if x.region_id not in valid_regions:
                x.region_id = None
    for item in ext.items:
        computed = flag_from_range(item.value, item.reference_range)
        if computed is not None:
            item.flag, item.flag_source = computed, "range"
    if ext.suggested_department not in departments:
        ext.suggested_department = "general_medicine" if "general_medicine" in departments else next(iter(departments))
    # Urgency from the model is kept as a floor only; safety.py can raise it to emergency (never lower it).
    return ext


def abnormal_items(ext: Extraction) -> list[Item]:
    return [i for i in ext.items if i.flag in ("high", "low", "abnormal")]
