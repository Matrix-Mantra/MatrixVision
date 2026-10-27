"""Muse Voice Transcribe (dev.meta.ai/docs/speech-to-text) for spoken questions about the document.

The API takes multipart/form-data: `request` (JSON settings) and `audio` (RIFF/WAVE, mono, 16-bit PCM,
16 or 24 kHz). The browser records and encodes that WAV itself, so no ffmpeg is needed here.

Nepali is not in Muse Voice's language list, so we bias towards Hindi (same Devanagari script) and
English, and Muse Spark then reads the transcript as Nepali (see understand.answer).
"""

from __future__ import annotations

import io
import json
import logging
import wave

import httpx

from . import config, meta_client

log = logging.getLogger("vision.voice")

SAMPLE_RATES = {16000, 24000}


class BadAudio(ValueError):
    pass


def check_wav(data: bytes) -> float:
    """Raise BadAudio unless `data` is the WAV the API accepts. Returns the duration in seconds."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise BadAudio("not a WAV file")
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() not in SAMPLE_RATES:
                raise BadAudio("WAV must be mono, 16-bit, 16 or 24 kHz")
            return w.getnframes() / float(w.getframerate())
    except wave.Error as exc:
        raise BadAudio(str(exc)) from exc


def _post(model: str, data: bytes) -> str:
    settings = {"model": model, "mode": "PUSH_TO_TALK", "audioEncoding": "WAV",
                "languageBias": config.VOICE_LANGUAGE_BIAS}
    resp = httpx.post(
        config.META_API_BASE + "/asr/transcribe",
        headers={"Authorization": f"Bearer {config.META_API_KEY}", "Accept": "application/json"},
        files={"request": (None, json.dumps(settings), "application/json"),
               "audio": ("question.wav", data, "audio/wav")},
        timeout=config.META_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return (resp.json().get("transcript") or "").strip()


def transcribe(data: bytes) -> str:
    if not meta_client.configured():
        raise meta_client.NotConfigured("META_API_KEY is not set")
    seconds = check_wav(data)
    if seconds < 0.4:
        raise BadAudio("recording is empty")
    text, _ = meta_client.call_with_fallback([config.VOICE_MODEL], lambda m: _post(m, data))
    return text
