"""FastAPI app: the web page and the JSON API."""

from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import config, grounding, meta_client, pdf, safety, understand, vision, voice
from .auth import User, check_limit, current_user, refund

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("vision")

app = FastAPI(title="Matrix Vision", version="0.1.0")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(self), geolocation=()")
    if request.url.path.startswith("/api/vision"):
        resp.headers.setdefault("Cache-Control", "no-store")  # results are personal
    return resp


# ------------------------------------------------------------------ pages and config


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "auth": config.AUTH_MODE, "store": config.STORE, "meta_configured": meta_client.configured()}


@app.get("/api/config")
def app_config() -> dict:
    """Everything the browser needs at start-up (all public). Firebase and districts come from Matrix."""
    mcfg = grounding.matrix_config()
    return {
        "auth_mode": config.AUTH_MODE,
        "firebase": (config.FIREBASE_WEB_CONFIG or mcfg.get("firebase")) if config.AUTH_MODE == "firebase" else None,
        "districts": sorted(mcfg.get("districts") or []),
        "matrix_url": config.MATRIX_API_BASE,
        "daily_limit": config.DAILY_VISION_LIMIT,
        "meta_configured": meta_client.configured(),
        "disclaimer": vision.DISCLAIMER,
    }


# ------------------------------------------------------------------ scan (login required)


async def _read_limited(upload: UploadFile, limit: int, too_big: str) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, too_big)
    return data


def _error(exc: vision.PipelineError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code, "safety": exc.safety})


@app.post("/api/vision")
async def scan(
    image: UploadFile = File(...),
    note: str = Form("", max_length=config.MAX_QUESTION_CHARS),
    lang: Literal["ne", "en"] = Form("ne"),
    district: str | None = Form(None, max_length=60),
    user: User = Depends(current_user),
):
    check_limit(user, "vision", config.DAILY_VISION_LIMIT)
    data = await _read_limited(image, config.MAX_IMAGE_BYTES, "The photo is too large.")
    try:
        return await run_in_threadpool(vision.run, data, vision.Options(note=note.strip(), lang=lang,
                                                                        district=district or None))
    except vision.PipelineError as exc:
        if exc.status >= 500:
            refund(user, "vision")  # our failure: don't use up the person's daily scans
        return _error(exc)
    except Exception:
        log.exception("vision failed")
        refund(user, "vision")
        # Even if something unexpected breaks, never hide an emergency.
        return JSONResponse(status_code=502, content={"detail": "Something went wrong. Please try again.",
                                                      "code": "failed", "safety": safety.check_document(note)})


# ------------------------------------------------------------------ follow-up questions (login required)
#
# The browser keeps the result of /api/vision and sends it back with each question (nothing is stored
# here). Hospitals are looked up again from Matrix by department, never taken from the browser.


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DocumentIn(_Loose):
    document_type: str = Field(max_length=40)
    items: list[dict] = Field(default_factory=list, max_length=150)
    medicines: list[dict] = Field(default_factory=list, max_length=60)
    findings: list[dict] = Field(default_factory=list, max_length=40)
    summary: dict = Field(default_factory=dict)
    department: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    questions_for_doctor: dict = Field(default_factory=dict)
    regions: list[dict] = Field(default_factory=list, max_length=12)


def _department_id(doc: DocumentIn) -> str:
    dept = str(doc.department.get("id", ""))
    if dept not in grounding.departments():
        raise HTTPException(422, "This document cannot be used.")
    return dept


def _document_text(doc: DocumentIn) -> str:
    text = str(doc.context.get("document_text", ""))
    if len(text) > 20000 or len(doc.model_dump_json()) > 80000:
        raise HTTPException(413, "This document is too large.")
    return text


def _document_safety(doc: DocumentIn, *extra: str) -> dict:
    words = [_document_text(doc), *extra]
    words += [f"{i.get('name', '')} {i.get('value', '')} {i.get('unit') or ''}" for i in doc.items]
    words += [str(f.get("text", "")) for f in doc.findings] + [str(m.get("name", "")) for m in doc.medicines]
    return safety.check_document(*words, items=doc.items)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=config.MAX_QUESTION_CHARS)
    spoken: bool = False
    lang: Literal["ne", "en"] = "ne"
    district: str | None = Field(default=None, max_length=60)
    document: DocumentIn


@app.post("/api/vision/transcribe")
async def transcribe(audio: UploadFile = File(...), user: User = Depends(current_user)):
    """A spoken question (WAV from the browser) -> text, plus the safety check on what was said."""
    check_limit(user, "question", config.DAILY_QUESTION_LIMIT)
    data = await _read_limited(audio, config.MAX_AUDIO_BYTES, "Recording is too long. Please keep it under a minute.")
    try:
        text = await run_in_threadpool(voice.transcribe, data)
    except voice.BadAudio as exc:
        raise HTTPException(400, "Could not use this recording. Please try again or type your question.") from exc
    except meta_client.NotConfigured as exc:
        refund(user, "question")
        raise HTTPException(503, "Voice questions are not set up yet. Please type your question.") from exc
    except Exception as exc:
        log.exception("transcription failed")
        refund(user, "question")
        raise HTTPException(503 if meta_client.is_busy(exc) else 502,
                            "Could not understand the recording. Please try again or type instead.") from exc
    return {"text": text, "safety": safety.check_text(text)}


@app.post("/api/vision/ask")
def ask(body: AskIn, user: User = Depends(current_user)):
    # Spoken questions were counted at /transcribe.
    if not body.spoken:
        check_limit(user, "question", config.DAILY_QUESTION_LIMIT)
    question_check = safety.check_text(body.question)
    doc = body.document
    dept = _department_id(doc)
    _document_text(doc)
    found = grounding.hospitals_for(dept, body.district, body.lang)
    context = doc.model_dump(include={"document_type", "items", "medicines", "findings", "summary", "context"})
    try:
        ans, model = understand.answer(body.question, context, found["hospitals"], spoken=body.spoken)
    except Exception as exc:
        log.warning("answer failed: %s", type(exc).__name__)
        busy = meta_client.is_busy(exc) or isinstance(exc, meta_client.NotConfigured)
        return JSONResponse(status_code=503 if busy else 502, content={
            "detail": "Could not answer right now. Please try again.", "safety": question_check})
    directory = grounding.all_hospitals()
    valid = {r.get("id") for r in doc.regions}
    return {
        "question_understood": grounding.strip_unlisted(ans.question_understood_ne, found["hospitals"], directory),
        "answer": {"ne": grounding.strip_unlisted(ans.answer_ne, found["hospitals"], directory),
                   "en": grounding.strip_unlisted(ans.answer_en, found["hospitals"], directory)},
        "region_ids": [r for r in ans.region_ids if r in valid],
        # The question and its Nepali reading both go through the rules, in code.
        "safety": safety.check_document(body.question, ans.question_understood_ne),
        "hospitals": found,
        "model": model,
    }


# ------------------------------------------------------------------ PDF


class PdfIn(BaseModel):
    lang: Literal["ne", "en"] = "ne"
    district: str | None = Field(default=None, max_length=60)
    document: DocumentIn


@app.post("/api/vision/pdf")
def summary_pdf(body: PdfIn, user: User = Depends(current_user)) -> Response:
    check_limit(user, "pdf", config.DAILY_PDF_LIMIT)
    doc = body.document
    dept = _department_id(doc)
    check = _document_safety(doc)
    found = grounding.hospitals_for(dept, body.district, body.lang)
    hospitals = found["hospitals"]
    if check["is_emergency"]:
        hospitals = grounding.hospitals_for("emergency", body.district, body.lang)["hospitals"] + hospitals
    rep = doc.model_dump()
    rep.update(lang=body.lang, disclaimer=vision.DISCLAIMER)
    rep = grounding.ground(rep, hospitals, grounding.all_hospitals())
    try:
        data = pdf.render_pdf(rep, check, hospitals)
    except Exception as exc:
        log.exception("pdf failed")
        raise HTTPException(400, "Could not create the PDF.") from exc
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="matrix-vision-summary.pdf"',
                             "Cache-Control": "no-store"})
