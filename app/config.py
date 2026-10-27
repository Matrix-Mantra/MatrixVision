"""Settings, all from environment variables (secrets never live in the repo)."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
FONT_DIR = STATIC_DIR / "fonts"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.getenv(name, default).split(",") if s.strip()]


# ------------------------------------------------------------------ Matrix (companion app)
MATRIX_API_BASE = os.getenv("MATRIX_API_BASE", "https://matrix.hospitalsofnepal.com").rstrip("/")
# Public page of one hospital in Matrix; {id} is replaced (Matrix routes are #/h/<id>).
MATRIX_HOSPITAL_URL = os.getenv("MATRIX_HOSPITAL_URL", MATRIX_API_BASE + "/#/h/{id}")
MATRIX_CACHE_SECONDS = _int("MATRIX_CACHE_SECONDS", 600)
MATRIX_TIMEOUT_SECONDS = _int("MATRIX_TIMEOUT_SECONDS", 8)

# ------------------------------------------------------------------ Meta Model API
META_API_BASE = os.getenv("META_API_BASE", "https://api.meta.ai/v1").rstrip("/")
META_API_KEY = os.getenv("META_API_KEY", "")
# Tried in order: if one version fails (busy, unavailable) the next is used.
MUSE_SPARK_MODELS = _list("MUSE_SPARK_MODELS", "muse-spark-1.3,muse-spark-1.2,muse-spark-1.1")
# Audio understanding is not fully supported on 1.3 (see dev.meta.ai/docs/models).
SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1")
VOICE_MODEL = os.getenv("VOICE_MODEL", "muse-voice-transcribe-1.0")
# Nepali is not in Muse Voice's language list; Hindi shares the Devanagari script.
VOICE_LANGUAGE_BIAS = _list("VOICE_LANGUAGE_BIAS", "Hindi,English")
META_TIMEOUT_SECONDS = _int("META_TIMEOUT_SECONDS", 60)
META_MAX_RETRIES = _int("META_MAX_RETRIES", 2)

# ------------------------------------------------------------------ auth and limits
# "firebase" in production; "dev" accepts a fake token "dev:<uid>" for local work and tests.
AUTH_MODE = os.getenv("AUTH_MODE", "firebase")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "projects-4e426")
# Public web config (apiKey, authDomain, projectId, appId). If empty, it is read from Matrix's /api/config.
FIREBASE_WEB_CONFIG: dict = json.loads(os.getenv("FIREBASE_WEB_CONFIG") or "{}")
# "firestore" (shared across Cloud Run instances) or "memory" (one process: dev and tests).
STORE = os.getenv("STORE", "firestore" if AUTH_MODE == "firebase" else "memory")
DAILY_VISION_LIMIT = _int("DAILY_VISION_LIMIT", 10)
DAILY_QUESTION_LIMIT = _int("DAILY_QUESTION_LIMIT", 30)
DAILY_PDF_LIMIT = _int("DAILY_PDF_LIMIT", 30)

# ------------------------------------------------------------------ uploads
MAX_IMAGE_BYTES = _int("MAX_IMAGE_BYTES", 12 * 1024 * 1024)
MAX_IMAGE_SIDE = _int("MAX_IMAGE_SIDE", 2000)  # long side after resize, px
JPEG_QUALITY = _int("JPEG_QUALITY", 82)
MAX_AUDIO_BYTES = _int("MAX_AUDIO_BYTES", 4 * 1024 * 1024)  # ~90 s of 24 kHz mono WAV
MAX_QUESTION_CHARS = 500

PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://matrixvision.hospitalsofnepal.com")
