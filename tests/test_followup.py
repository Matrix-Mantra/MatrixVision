"""Voice questions, typed questions and the PDF."""

import io
import json
import wave

import httpx
import pytest

from app import grounding, meta_client, understand, voice
from tests.conftest import AUTH
from tests.test_vision_route import BHAKTAPUR, BIR, DEPTS, extraction, fresh_limits, mocked  # noqa: F401


def wav(seconds=1.0, rate=24000, channels=1, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


def document():
    e = extraction()
    return {"document_type": "lab_report", "items": e["items"], "medicines": [], "findings": [],
            "summary": {"ne": "…", "en": "…"}, "department": {"id": "general_medicine"},
            "context": {"document_text": e["document_text"]}, "regions": [{"id": "r0", "box": [0, 0, 1, 1]}],
            "questions_for_doctor": {"ne": ["के यो चिन्ताको कुरा हो?"], "en": ["Is this a concern?"]}}


# ------------------------------------------------------------------ WAV checks


def test_check_wav_accepts_api_format():
    assert voice.check_wav(wav(2.0, 16000)) == pytest.approx(2.0)


@pytest.mark.parametrize("data", [wav(rate=44100), wav(channels=2), wav(width=1), b"OggS....", b""])
def test_check_wav_rejects(data):
    with pytest.raises(voice.BadAudio):
        voice.check_wav(data)


def test_transcribe_request_format(monkeypatch):
    monkeypatch.setattr(meta_client, "configured", lambda: True)
    seen = {}

    def fake_post(url, headers, files, timeout):
        seen.update(url=url, headers=headers, files=files)
        return httpx.Response(200, json={"sessionId": "s", "transcript": " मेरो सुगर कति छ? ", "audioDurationMs": 900,
                                         "turns": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(voice.httpx, "post", fake_post)
    assert voice.transcribe(wav()) == "मेरो सुगर कति छ?"
    assert seen["url"] == "https://api.meta.ai/v1/asr/transcribe"
    settings = json.loads(seen["files"]["request"][1])
    assert seen["files"]["request"][2] == "application/json"
    assert settings == {"model": "muse-voice-transcribe-1.0", "mode": "PUSH_TO_TALK", "audioEncoding": "WAV",
                        "languageBias": ["Hindi", "English"]}
    assert seen["files"]["audio"][2] == "audio/wav"


# ------------------------------------------------------------------ routes


def test_transcribe_route_runs_safety(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda data: "मलाई छाती दुखेको छ")
    r = client.post("/api/vision/transcribe", headers=AUTH, files={"audio": ("q.wav", wav(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["safety"]["flags"][0]["id"] == "chest_pain"


def test_transcribe_route_not_configured(client):
    r = client.post("/api/vision/transcribe", headers=AUTH, files={"audio": ("q.wav", wav(), "audio/wav")})
    assert r.status_code == 503


def test_ask_grounds_answer_and_checks_safety(client, mocked, monkeypatch):
    captured = {}

    def fake_answer(question, context, hospitals, spoken=False):
        captured.update(hospitals=hospitals, spoken=spoken, context=context)
        return understand.Answer(question_understood_ne="यसको अर्थ के हो?",
                                 answer_ne="वीर अस्पताल वा भक्तपुर अस्पतालमा देखाउनुहोस्।",
                                 answer_en="Show it at Bir Hospital or Bhaktapur Hospital.",
                                 region_ids=["r0", "r9"]), "muse-spark-1.3"

    monkeypatch.setattr(understand, "answer", fake_answer)
    r = client.post("/api/vision/ask", headers=AUTH, json={"question": "yo k ho? I have chest pain", "spoken": True,
                                                           "document": document()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"]["en"] == "Show it at a hospital or Bhaktapur Hospital."
    assert body["answer"]["ne"] == "अस्पताल वा भक्तपुर अस्पतालमा देखाउनुहोस्।"
    assert body["region_ids"] == ["r0"]
    assert body["safety"]["is_emergency"]
    assert [h["id"] for h in captured["hospitals"]] == ["bhaktapur_hosp"] and captured["spoken"]
    assert "regions" not in captured["context"]


def test_ask_rejects_unknown_department(client, mocked):
    doc = document()
    doc["department"] = {"id": "made_up"}
    assert client.post("/api/vision/ask", headers=AUTH, json={"question": "what?", "document": doc}).status_code == 422


def test_ask_failure_still_returns_safety(client, mocked, monkeypatch):
    def boom(*a, **k):
        raise meta_client.NotConfigured("no key")

    monkeypatch.setattr(understand, "answer", boom)
    r = client.post("/api/vision/ask", headers=AUTH, json={"question": "saas pherna garo", "document": document()})
    assert r.status_code == 503 and r.json()["safety"]["flags"][0]["id"] == "breathing"


def test_pdf_renders_nepali_and_recomputes_safety(client, mocked):
    doc = document()
    doc["context"]["document_text"] = "CRITICAL VALUE called to ward"  # browser can't hide this
    r = client.post("/api/vision/pdf", headers=AUTH, json={"lang": "ne", "document": doc})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert r.headers["content-type"] == "application/pdf"
    from pypdf import PdfReader

    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "१०२" in text and "matrix.hospitalsofnepal.com/#/h/bhaktapur_hosp" in text
    assert "matrix.hospitalsofnepal.com/#/h/bir" in text  # emergency hospitals added


def test_pdf_english(client, mocked):
    r = client.post("/api/vision/pdf", headers=AUTH, json={"lang": "en", "document": document()})
    assert r.status_code == 200 and len(r.content) > 2000
