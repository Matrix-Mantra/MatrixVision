"""Only hospitals from Matrix's list may be named; everything else is removed in code."""

import pytest

from app import grounding

BHAKTAPUR = {"id": "bhaktapur_hosp", "name": "Bhaktapur Hospital", "name_ne": "भक्तपुर अस्पताल", "district": "Bhaktapur"}
CANCER = {"id": "bhaktapur_cancer", "name": "Bhaktapur Cancer Hospital", "name_ne": "भक्तपुर क्यान्सर अस्पताल"}
BIR = {"id": "bir", "name": "Bir Hospital", "name_ne": "वीर अस्पताल"}
DIRECTORY = [BHAKTAPUR, CANCER, BIR]


@pytest.mark.parametrize("text,expected", [
    ("Go to Bir Hospital for a check-up.", "Go to a hospital for a check-up."),
    ("Visit Bhaktapur Hospital or Bir Hospital.", "Visit Bhaktapur Hospital or a hospital."),
    ("Try Grande International Hospital tomorrow.", "Try a hospital tomorrow."),  # not in Matrix at all
    ("See Dr. at B.P. Koirala Institute of Health Sciences.", "See Dr. at a hospital."),
    ("Kathmandu Medical College has a lab.", "a hospital has a lab."),
    ("Go to the nearest hospital.", "Go to the nearest hospital."),  # generic, kept
    ("Bhaktapur Cancer Hospital is not allowed here.", "a hospital is not allowed here."),
])
def test_english(text, expected):
    assert grounding.strip_unlisted(text, [BHAKTAPUR], DIRECTORY) == expected


@pytest.mark.parametrize("text,expected", [
    ("वीर अस्पतालमा जानुहोस्।", "अस्पतालमा जानुहोस्।"),
    ("भक्तपुर अस्पतालमा जानुहोस्।", "भक्तपुर अस्पतालमा जानुहोस्।"),  # allowed
    ("ग्राण्डी अस्पताल जानुहोस्।", "अस्पताल जानुहोस्।"),  # unknown name
    ("नजिकको सरकारी अस्पतालमा जानुहोस्।", "नजिकको सरकारी अस्पतालमा जानुहोस्।"),  # generic, kept
    ("काठमाडौं मेडिकल कलेजमा जाँच गराउनुहोस्।", "अस्पतालमा जाँच गराउनुहोस्।"),
    ("तलका अस्पतालमध्ये कुनैमा जानुहोस्।", "तलका अस्पतालमध्ये कुनैमा जानुहोस्।"),
])
def test_nepali(text, expected):
    assert grounding.strip_unlisted(text, [BHAKTAPUR], DIRECTORY) == expected


def test_nothing_allowed_strips_everything_named():
    assert grounding.strip_unlisted("Bhaktapur Hospital", [], DIRECTORY) == "a hospital"


def test_ground_walks_nested_structures():
    out = grounding.ground({"a": ["Go to Bir Hospital"], "b": {"c": "वीर अस्पताल"}, "n": 3}, [BHAKTAPUR], DIRECTORY)
    assert out == {"a": ["Go to a hospital"], "b": {"c": "अस्पताल"}, "n": 3}


def test_matrix_url():
    assert grounding.hospital_url("bhaktapur_hosp") == "https://matrix.hospitalsofnepal.com/#/h/bhaktapur_hosp"


def test_hospitals_for_falls_back_to_national(monkeypatch):
    calls = []

    def fake_get(path, params=None):
        calls.append(params)
        if params.get("district"):
            return {"count": 0, "hospitals": []}
        return {"count": 1, "hospitals": [dict(BIR, departments=["cardiology"], lat=1)]}

    monkeypatch.setattr(grounding, "_get", fake_get)
    r = grounding.hospitals_for("cardiology", district="Mugu")
    assert r["scope"] == "national" and [h["id"] for h in r["hospitals"]] == ["bir"]
    assert r["hospitals"][0]["matrix_url"].endswith("#/h/bir") and "lat" not in r["hospitals"][0]
    assert calls[1] == {"department": "cardiology", "near": "Mugu", "lang": "ne"}


def test_hospitals_for_survives_matrix_down(monkeypatch):
    def boom(path, params=None):
        raise RuntimeError("down")

    monkeypatch.setattr(grounding, "_get", boom)
    assert grounding.hospitals_for("cardiology") == {"department": "cardiology", "district": None,
                                                     "scope": "none", "hospitals": []}


def test_departments_fallback(monkeypatch):
    monkeypatch.setattr(grounding, "matrix_config", lambda: {})
    assert set(grounding.departments()) == set(grounding.FALLBACK_DEPARTMENTS)


UNIVERSAL = {"id": "ucms", "name": "Universal College of Medical Sciences Teaching Hospital",
             "name_ne": "युनिभर्सल कलेज अफ मेडिकल साइन्सेज शिक्षण अस्पताल"}
CMS = {"id": "cms", "name": "College of Medical Sciences Teaching Hospital", "name_ne": "कलेज अफ मेडिकल साइन्सेज शिक्षण अस्पताल"}


def test_name_nested_in_an_allowed_name_is_still_stripped():
    out = grounding.strip_unlisted("Go to Universal College of Medical Sciences Teaching Hospital.", [CMS], [CMS, UNIVERSAL])
    assert out == "Go to a hospital."
    assert grounding.strip_unlisted("Go to College of Medical Sciences Teaching Hospital.", [CMS], [CMS, UNIVERSAL]) \
        == "Go to College of Medical Sciences Teaching Hospital."


@pytest.mark.parametrize("text,expected", [
    ("Go to Shahid Gangalal National Heart Centre.", "Go to a hospital."),
    ("Karnali Academy of Health Sciences can help.", "a hospital can help."),
    ("डोटी जिल्ला अस्पतालमा जानुहोस्।", "अस्पतालमा जानुहोस्।"),
    ("शहीद गंगालाल राष्ट्रिय हृदय केन्द्रमा जानुहोस्।", "अस्पतालमा जानुहोस्।"),
])
def test_names_not_in_directory_are_caught_by_pattern(text, expected):
    assert grounding.strip_unlisted(text, [], []) == expected


@pytest.mark.parametrize("text", [
    "Ask at the Help Centre.", "Go to a Health Post or the District Hospital.", "Visit the Eye Hospital nearby.",
    "जिल्ला अस्पताल वा सरकारी अस्पतालमा जानुहोस्।", "नजिकको स्वास्थ्य चौकीमा जानुहोस्।", "आकस्मिक कक्षमा जानुहोस्।",
    "Your Haemoglobin is low.", "Take Tab. Paracetamol 500 mg.",
])
def test_generic_phrases_are_kept(text):
    assert grounding.strip_unlisted(text, [], DIRECTORY) == text


def test_article_before_stripped_name_is_dropped():
    assert grounding.strip_unlisted("Visit the Grande International Hospital.", [], []) == "Visit a hospital."


def test_english_name_in_nepali_sentence_gets_nepali_replacement():
    assert grounding.strip_unlisted("Bir Hospital मा जाँच गराउनुहोस्।", [], DIRECTORY) == "अस्पताल मा जाँच गराउनुहोस्।"
    assert grounding.strip_unlisted("Grande International Hospital मा जानुहोस्।", [], []) == "अस्पताल मा जानुहोस्।"
