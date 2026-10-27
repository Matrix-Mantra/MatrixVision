"""Parsing Muse Spark output and the checks done on it in code."""

import json

import pytest

from app import schemas, understand

DEPTS = {"general_medicine": {"en": "General medicine"}, "cardiology": {"en": "Cardiology"},
         "nephrology": {"en": "Kidney"}}


def _raw(**over):
    raw = {
        "document_type": "lab_report", "document_text": "Haemoglobin 9.1 g/dL 12-15",
        "items": [{"name": "Haemoglobin", "value": "9.1", "unit": "g/dL", "reference_range": "12 - 15",
                   "flag": "normal", "region_id": "r0", "explanation_ne": "…", "explanation_en": "…"}],
        "medicines": [], "findings": [], "summary_ne": "सारांश", "summary_en": "Summary",
        "suggested_department": "general_medicine", "department_reason_ne": "", "department_reason_en": "",
        "urgency": "soon", "questions_for_doctor_ne": [], "questions_for_doctor_en": [], "unreadable_parts": [],
    }
    raw.update(over)
    return raw


@pytest.mark.parametrize("text", [
    json.dumps({"a": 1}),
    "```json\n{\"a\": 1}\n```",
    "Here you go: {\"a\": 1} hope this helps",
])
def test_parse_json_variants(text):
    assert understand.parse_json(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2]"])
def test_parse_json_rejects(text):
    with pytest.raises(ValueError):
        understand.parse_json(text)


@pytest.mark.parametrize("value,rr,flag", [
    ("9.1", "12 - 15", "low"),
    ("16", "12-15 g/dL", "high"),
    ("13.2", "12–15", "normal"),
    ("2,50,000", "1,50,000 - 4,00,000 /cumm", "normal"),
    ("4,80,000", "150000-400000", "high"),
    ("240", "< 200", "high"),
    ("180", "Up to 200 mg/dL", "normal"),
    ("35", "> 40", "low"),
    ("92", "80-100 fL", "normal"),
    ("6.8", "4.0-11.0 x10^3/uL", "normal"),
])
def test_flag_from_range(value, rr, flag):
    assert understand.flag_from_range(value, rr) == flag


@pytest.mark.parametrize("value,rr", [
    ("Positive", "Negative"), ("12", None), ("12", "M: 13-17, F: 12-15"), ("1+", "Nil"), ("12", "15 - 10"),
])
def test_flag_from_range_refuses_to_guess(value, rr):
    assert understand.flag_from_range(value, rr) is None


def test_finalize_recomputes_flags_in_code():
    ext = understand.finalize(_raw(), DEPTS, {"r0"})
    item = ext.items[0]
    assert (item.flag, item.flag_source) == ("low", "range")  # model said "normal"
    assert understand.abnormal_items(ext) == [item]


def test_finalize_keeps_model_flag_when_range_unreadable():
    raw = _raw(items=[{**_raw()["items"][0], "value": "Positive", "reference_range": "Negative", "flag": "abnormal"}])
    item = understand.finalize(raw, DEPTS, {"r0"}).items[0]
    assert (item.flag, item.flag_source) == ("abnormal", "model")


def test_finalize_drops_unknown_regions_and_departments():
    raw = _raw(suggested_department="astrology")
    raw["items"][0]["region_id"] = "r7"
    ext = understand.finalize(raw, DEPTS, {"r0", "r1"})
    assert ext.items[0].region_id is None and ext.suggested_department == "general_medicine"


def test_finalize_never_lowers_model_urgency():
    assert understand.finalize(_raw(urgency="emergency"), DEPTS, set()).urgency == "emergency"


def test_finalize_rejects_missing_required_fields():
    with pytest.raises(ValueError):
        understand.finalize({"items": []}, DEPTS, set())


def test_extraction_schema_is_strict_subset():
    schema = schemas.extraction_schema(list(DEPTS))

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    walk(schemas.CLASSIFY_SCHEMA)
    walk(schemas.ANSWER_SCHEMA)
    assert schema["properties"]["suggested_department"]["enum"] == list(DEPTS)


def test_extract_sends_full_image_then_labelled_crops(monkeypatch):
    from app import imaging, segment
    from tests.test_imaging_segment import _png

    sent = {}

    def fake_respond(model, content, schema, name, effort, max_tokens):
        sent.update(model=model, content=content, name=name)
        return json.dumps(_raw())

    monkeypatch.setattr(understand, "_respond", fake_respond)
    prepared = imaging.prepare(_png())
    regions = [segment.Region("x-ray image", "scan", (0, 0, 0.5, 0.5), (0, 0, 500, 500), 0.9)]
    ext, model = understand.extract(prepared, regions, segment.crops(prepared, regions), DEPTS)
    kinds = [c["type"] for c in sent["content"]]
    assert kinds == ["input_text", "input_image", "input_text", "input_image"]
    assert sent["content"][2]["text"] == "Region r0 (x-ray image):"
    assert model == "muse-spark-1.3" and ext.items[0].flag == "low"


def test_extract_sends_page_closeup_but_never_cites_it(monkeypatch):
    from app import imaging, segment
    from tests.test_imaging_segment import _png
    sent = {}

    def fake_respond(model, content, schema, name, effort, max_tokens):
        sent["content"] = content
        return json.dumps(_raw())  # the model cites r0 anyway

    monkeypatch.setattr(understand, "_respond", fake_respond)
    prepared = imaging.prepare(_png())
    regions = [segment.Region("document", "page", (0.1, 0.1, 0.9, 0.9), (100, 100, 900, 900), 0.9)]
    ext, _ = understand.extract(prepared, regions, segment.crops(prepared, regions), DEPTS)
    assert sent["content"][2]["text"].startswith("Close-up of the paper")
    assert ext.items[0].region_id is None


def test_extract_falls_back_when_first_model_returns_bad_json(monkeypatch):
    from app import imaging
    from tests.test_imaging_segment import _png

    def fake_respond(model, *a):
        return "sorry" if model == "muse-spark-1.3" else json.dumps(_raw())

    monkeypatch.setattr(understand, "_respond", fake_respond)
    _, model = understand.extract(imaging.prepare(_png()), [], [], DEPTS)
    assert model == "muse-spark-1.2"
