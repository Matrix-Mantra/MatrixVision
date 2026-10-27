"""The ported Matrix rules keep their behaviour; the document checks work on real-looking reports."""

import pytest

from app import safety


@pytest.mark.parametrize("text,rule", [
    ("Patient complains of chest pain since morning", "chest_pain"),
    ("छातीमा दुखेको छ", "chest_pain"),
    ("saas pherna garo bhayo", "breathing"),
    ("बिरामी बेहोस भयो", "unconscious"),
    ("h/o seizure last night", "seizure"),
    ("pregnant, 32 weeks, bleeding", "pregnancy_danger"),
    ("बच्चा दूध खाँदैन", "infant_danger"),
    ("No chest pain", "chest_pain"),  # deliberately a false alarm, as in Matrix
])
def test_matrix_rules_fire(text, rule):
    ids = [f["id"] for f in safety.check_text(text)["flags"]]
    assert rule in ids


@pytest.mark.parametrize("text", ["benefits of iron tablets", "Tab. Paracetamol 500 mg TDS", "Hypertension follow-up"])
def test_matrix_rules_do_not_fire_on_ordinary_text(text):
    assert safety.check_text(text) == {"is_emergency": False, "flags": []}


def test_every_flag_says_call_102():
    for rule in safety.RULES:
        assert "102" in rule.action_en and "१०२" in rule.action_ne


@pytest.mark.parametrize("item,flag", [
    ({"name": "Serum Potassium", "value": "6.9", "unit": "mmol/L"}, "potassium_critical"),
    ({"name": "Sodium (Na+)", "value": "118", "unit": "mEq/L"}, "sodium_critical"),
    ({"name": "Blood Sugar (Random)", "value": "42", "unit": "mg/dL"}, "glucose_critical"),
    ({"name": "Glucose fasting", "value": "30.1", "unit": "mmol/L"}, "glucose_critical"),
    ({"name": "Haemoglobin (Hb)", "value": "6.2", "unit": "gm%"}, "hemoglobin_critical"),
    ({"name": "Hemoglobin", "value": "58", "unit": "g/L"}, "hemoglobin_critical"),
    ({"name": "Platelet count", "value": "15,000", "unit": "/cumm"}, "platelets_critical"),
    ({"name": "Platelets", "value": "0.12", "unit": "lakh/cumm"}, "platelets_critical"),
    ({"name": "PLT", "value": "18", "unit": "10³/µL"}, "platelets_critical"),
])
def test_critical_values(item, flag):
    assert [f["id"] for f in safety.check_values([item])] == [flag]


@pytest.mark.parametrize("item", [
    {"name": "Serum Potassium", "value": "4.1", "unit": "mmol/L"},
    {"name": "Haemoglobin", "value": "11.2", "unit": "gm/dL"},
    {"name": "HbA1c", "value": "6.1", "unit": "%"},
    {"name": "HBsAg", "value": "0.4", "unit": ""},
    {"name": "Urine sodium", "value": "40", "unit": "mmol/L"},
    {"name": "Platelet count", "value": "2,50,000", "unit": "/cumm"},
    {"name": "Potassium", "value": "7.0", "unit": "mg/dL"},  # unknown unit for this test: no guess
    {"name": "Glucose", "value": "Nil", "unit": ""},
])
def test_normal_or_unknown_values_do_not_fire(item):
    assert safety.check_values([item]) == []


def test_check_document_combines_all_sources():
    r = safety.check_document("note: patient fainted", "IMPRESSION: Right pneumothorax",
                              items=[{"name": "Potassium", "value": "2.1", "unit": "mmol/L"}])
    ids = {f["id"] for f in r["flags"]}
    assert r["is_emergency"] and ids == {"unconscious", "critical_imaging", "potassium_critical"}


def test_check_document_on_nothing():
    assert safety.check_document("", None, items=None) == {"is_emergency": False, "flags": []}
