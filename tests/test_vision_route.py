"""/api/vision end to end with Meta and Matrix mocked: safety override, grounding, limits."""

import json

import pytest

from app import grounding, meta_client, schemas, segment, store, understand
from tests.conftest import AUTH
from tests.test_imaging_segment import _png

BHAKTAPUR = {"id": "bhaktapur_hosp", "name": "Bhaktapur Hospital", "name_ne": "भक्तपुर अस्पताल", "district": "Bhaktapur"}
BIR = {"id": "bir", "name": "Bir Hospital", "name_ne": "वीर अस्पताल", "district": "Kathmandu"}
DEPTS = {"general_medicine": {"en": "General medicine", "ne": "जनरल मेडिसिन"}, "emergency": {"en": "Emergency", "ne": "आकस्मिक कक्ष"}}


def extraction(**over):
    raw = {
        "document_type": "lab_report", "document_text": "Haemoglobin 11.0 g/dL (12-15)",
        "items": [{"name": "Haemoglobin", "value": "11.0", "unit": "g/dL", "reference_range": "12-15", "flag": "low",
                   "region_id": "r0", "explanation_ne": "वीर अस्पतालमा जानुहोस्।", "explanation_en": "Go to Bir Hospital."}],
        "medicines": [], "findings": [], "summary_ne": "भक्तपुर अस्पताल राम्रो छ।", "summary_en": "Try Grande International Hospital.",
        "suggested_department": "general_medicine", "department_reason_ne": "", "department_reason_en": "",
        "urgency": "routine", "questions_for_doctor_ne": [], "questions_for_doctor_en": [], "unreadable_parts": [],
    }
    raw.update(over)
    return raw


@pytest.fixture(autouse=True)
def fresh_limits():
    store.get_store.cache_clear()
    yield
    store.get_store.cache_clear()


@pytest.fixture
def mocked(monkeypatch):
    """Meta + Matrix mocked. Returns a dict to tweak what the fakes return."""
    state = {"classify": {"is_medical_document": True, "document_type": "lab_report", "readable": True, "reason": ""},
             "extract": extraction(), "extract_error": None, "matrix_calls": []}

    def fake_respond(model, content, schema, name, effort, max_tokens):
        if name == "classify":
            return json.dumps(state["classify"])
        if state["extract_error"]:
            raise state["extract_error"]
        return json.dumps(state["extract"])

    def fake_hospitals_for(department, district=None, lang="ne", limit=5):
        state["matrix_calls"].append(department)
        rows = [BHAKTAPUR] if department == "general_medicine" else [BIR]
        return {"department": department, "district": district, "scope": "national",
                "hospitals": [dict(h, matrix_url=grounding.hospital_url(h["id"])) for h in rows]}

    monkeypatch.setattr(meta_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(meta_client, "configured", lambda: True)
    monkeypatch.setattr(understand, "_respond", fake_respond)
    monkeypatch.setattr(segment, "_request", lambda c, u, m: "<0f>1<|box;x1=10;y1=10;x2=900;y2=900;w=1200;h=1600;c=0.9|>")
    monkeypatch.setattr(grounding, "departments", lambda: DEPTS)
    monkeypatch.setattr(grounding, "hospitals_for", fake_hospitals_for)
    monkeypatch.setattr(grounding, "all_hospitals", lambda: [BHAKTAPUR, BIR])
    return state


def post(client, note="", headers=AUTH, data=None):
    return client.post("/api/vision", headers=headers, files={"image": ("doc.png", data or _png(), "image/png")},
                       data={"note": note, "lang": "ne"})


def test_requires_sign_in(client):
    assert post(client, headers={}).status_code == 401
    assert post(client, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_success_grounds_hospitals_and_recomputes_flags(client, mocked):
    r = post(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["urgency"] == "routine" and not body["safety"]["is_emergency"]
    assert body["items"][0]["flag"] == "low" and body["items"][0]["flag_source"] == "range"
    assert body["items"][0]["explanation_en"] == "Go to a hospital."  # Bir is not in the allowed list
    assert body["items"][0]["explanation_ne"] == "अस्पतालमा जानुहोस्।"
    assert body["summary"]["ne"] == "भक्तपुर अस्पताल राम्रो छ।"  # allowed, kept
    assert body["summary"]["en"] == "Try a hospital."
    assert [h["id"] for h in body["hospitals"]["hospitals"]] == ["bhaktapur_hosp"]
    assert body["hospitals"]["hospitals"][0]["matrix_url"].endswith("#/h/bhaktapur_hosp")
    assert body["regions"] == []  # the page close-up went to Muse Spark but is not a highlight target
    assert body["disclaimer"]["ne"] and body["disclaimer"]["en"]
    assert r.headers["cache-control"] == "no-store"


def test_safety_overrides_model_urgency(client, mocked):
    mocked["extract"] = extraction(document_text="IMPRESSION: small left pneumothorax", urgency="routine")
    body = post(client).json()
    assert body["urgency"] == "emergency" and body["safety"]["is_emergency"]
    assert "critical_imaging" in [f["id"] for f in body["safety"]["flags"]]
    assert "102" in body["safety"]["flags"][0]["action_en"]
    assert body["emergency_hospitals"]["hospitals"][0]["id"] == "bir"
    assert "emergency" in mocked["matrix_calls"]


def test_critical_lab_value_overrides(client, mocked):
    mocked["extract"] = extraction(items=[{**extraction()["items"][0], "name": "Potassium", "value": "7.1",
                                           "unit": "mmol/L", "reference_range": "3.5-5.1"}])
    body = post(client).json()
    assert body["urgency"] == "emergency" and body["safety"]["flags"][0]["id"] == "potassium_critical"


def test_safety_survives_model_failure(client, mocked):
    import httpx
    import openai

    resp = httpx.Response(503, request=httpx.Request("POST", "https://api.meta.ai/v1/responses"))
    mocked["extract_error"] = openai.APIStatusError("down", response=resp, body=None)
    r = post(client, note="बिरामी बेहोस भयो")
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "ai_busy" and body["safety"]["is_emergency"]
    assert body["safety"]["flags"][0]["id"] == "unconscious"


def test_unexpected_crash_still_returns_safety(client, mocked, monkeypatch):
    from app import vision

    monkeypatch.setattr(vision, "run", lambda *a: 1 / 0)
    body = post(client, note="chest pain").json()
    assert body["code"] == "failed" and body["safety"]["is_emergency"]


def test_not_configured_returns_503_with_safety(client, monkeypatch):
    monkeypatch.setattr(meta_client, "configured", lambda: False)
    meta_client.client.cache_clear()
    r = post(client, note="snake bite")
    assert r.status_code == 503 and r.json()["code"] == "ai_not_configured"
    assert r.json()["safety"]["flags"][0]["id"] == "snake_bite"


def test_rejects_non_documents(client, mocked):
    mocked["classify"] = {"is_medical_document": False, "document_type": "not_medical", "readable": True, "reason": "selfie"}
    r = post(client)
    assert r.status_code == 422 and r.json()["code"] == "not_document"


def test_rejects_bad_files(client, mocked):
    r = post(client, data=b"%PDF-1.7 hello")
    assert r.status_code == 400 and r.json()["code"] == "bad_type"


def test_daily_limit_and_refund_on_our_failure(client, mocked):
    import httpx
    import openai

    # Limit is 3 in tests. A 503 from Meta is refunded, so it doesn't count.
    resp = httpx.Response(503, request=httpx.Request("POST", "https://api.meta.ai/v1/responses"))
    mocked["extract_error"] = openai.APIStatusError("down", response=resp, body=None)
    assert post(client).status_code == 503
    mocked["extract_error"] = None
    assert [post(client).status_code for _ in range(4)] == [200, 200, 200, 429]
    # Another user is not affected.
    assert post(client, headers={"Authorization": "Bearer dev:someone-else"}).status_code == 200


def test_config_is_public(client, monkeypatch):
    monkeypatch.setattr(grounding, "matrix_config", lambda: {"districts": ["Kaski", "Bhaktapur"], "firebase": {"projectId": "p"}})
    body = client.get("/api/config").json()
    assert body["districts"] == ["Bhaktapur", "Kaski"] and body["auth_mode"] == "dev" and body["firebase"] is None
