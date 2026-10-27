"""Deterministic red-flag detection, ported from Matrix (app/safety.py).

This layer runs in plain Python, never in the model, so an emergency is never left to the model
alone. It deliberately prefers false alarms over missed emergencies (e.g. "no chest pain" still
triggers).

Ported unchanged from Matrix: RULES, _normalize, _has, check_text (English, Nepali Devanagari and
romanized Nepali). Not ported: the animal/vet rules (documents here are about people).
Added for documents: CRITICAL_VALUES (lab numbers) and DOCUMENT_RULES (report wording).

Have a clinician review these lists and thresholds before launch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedFlagRule:
    id: str
    label_en: str
    label_ne: str
    # Rule fires if ANY phrase in `any_of` appears ...
    any_of: tuple[str, ...] = ()
    # ... OR if, for every group in `all_groups`, at least one phrase appears.
    all_groups: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    action_en: str = "Call 102 for an ambulance or go to the nearest emergency department now."
    action_ne: str = "अहिले नै १०२ मा फोन गरी एम्बुलेन्स बोलाउनुहोस् वा नजिकको आकस्मिक कक्षमा जानुहोस्।"


RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule(
        id="chest_pain",
        label_en="Chest pain or pressure",
        label_ne="छाती दुखाइ वा छाती थिचिएको जस्तो",
        any_of=(
            "chest pain", "chest tightness", "pain in chest", "pressure in chest", "heart attack",
            "छाती दुख", "छातीमा दुख", "छाती पोल", "छाती कस", "मुटुको दौरा", "हार्ट अट्याक",
            "chhati dukh", "chati dukh", "chhatima dukh", "chatima dukh",
        ),
    ),
    RedFlagRule(
        id="breathing",
        label_en="Severe difficulty breathing",
        label_ne="सास फेर्न धेरै गाह्रो",
        any_of=(
            "can't breathe", "cannot breathe", "can not breathe", "difficulty breathing",
            "trouble breathing", "shortness of breath", "breathless", "not breathing", "choking",
            "सास फेर्न गाह्रो", "सास फेर्न सकेन", "सास फेर्न सक्दैन", "सास रोकि", "सास बढ", "निसास्सिए",
            "saas pherna garo", "sas ferna garo", "saas fernu garo", "sas pherna garo",
        ),
    ),
    RedFlagRule(
        id="unconscious",
        label_en="Unconscious, fainted or not responding",
        label_ne="बेहोस वा प्रतिक्रिया नदिने",
        any_of=(
            "unconscious", "fainted", "passed out", "not responding", "unresponsive", "collapsed",
            "बेहोस", "होस छैन", "ढलेको", "ढल्यो",
            "behosh", "behos", "hos chaina",
        ),
    ),
    RedFlagRule(
        id="seizure",
        label_en="Seizure / fits",
        label_ne="छारे रोग / काम्ने दौरा",
        any_of=(
            "seizure", "convulsion", "fits", "fitting",
            "छारे", "मिर्गी", "कम्प छुट", "दौरा पर्",
            "chhare", "chare rog", "mirgi",
        ),
    ),
    RedFlagRule(
        id="stroke",
        label_en="Possible stroke (face drooping, weakness on one side, slurred speech)",
        label_ne="पक्षघातको लक्षण (अनुहार बाङ्गिने, एक भाग कमजोर, बोली लरबराउने)",
        any_of=(
            "stroke", "face drooping", "face is drooping", "slurred speech", "one side weak",
            "weakness on one side", "can't move one side", "paralysis", "paralyzed",
            "पक्षघात", "प्यारालाइसिस", "मुख बाङ्गो", "अनुहार बाङ्गो", "बोली लर", "आधा जिउ",
            "pakshaghat", "mukh bango", "boli lar",
        ),
    ),
    RedFlagRule(
        id="severe_bleeding",
        label_en="Heavy bleeding",
        label_ne="धेरै रगत बगिरहेको",
        any_of=(
            "heavy bleeding", "bleeding a lot", "won't stop bleeding", "bleeding heavily",
            "vomiting blood", "coughing blood", "blood in vomit",
            "धेरै रगत", "रगत रोकिएन", "रगत बान्ता", "रगत खकार",
            "dherai ragat", "ragat rokiyena", "ragat banta",
        ),
    ),
    RedFlagRule(
        id="pregnancy_danger",
        label_en="Danger sign in pregnancy",
        label_ne="गर्भावस्थामा खतराको संकेत",
        all_groups=(
            ("pregnan", "गर्भ", "garbha", "pet ma bachcha", "पेटमा बच्चा", "sutkeri", "सुत्केरी", "delivery", "labor", "labour"),
            ("bleed", "रगत", "ragat", "severe pain", "धेरै दुख", "fit", "छारे", "swelling", "सुन्निए", "blurred vision",
             "headache", "टाउको दुख", "water broke", "पानी फुट", "baby not moving", "बच्चा चलेन"),
        ),
    ),
    RedFlagRule(
        id="snake_bite",
        label_en="Snake bite",
        label_ne="सर्पदंश",
        any_of=(
            "snake bite", "snakebite", "bitten by a snake", "snake bit",
            "सर्पले टोक", "सर्पदंश", "सर्प टोक",
            "sarpa le tok", "sarpale tok", "sap le tok", "saap le tok",
        ),
        action_en="Keep the person still, do not cut or suck the wound, and go to the nearest hospital or snakebite treatment centre now (call 102).",
        action_ne="बिरामीलाई नचलाउनुहोस्, घाउ नकाट्नुहोस् वा नचुस्नुहोस्, र तुरुन्तै नजिकको अस्पताल वा सर्पदंश उपचार केन्द्र जानुहोस् (१०२)।",
    ),
    RedFlagRule(
        id="poisoning",
        label_en="Poisoning or overdose",
        label_ne="विष वा औषधि धेरै खाएको",
        any_of=(
            "poison", "pesticide", "overdose", "swallowed chemical", "drank kerosene",
            "विष", "बिष", "किटनाशक", "विषादी", "धेरै औषधि खा",
            "bish", "bis khayo", "bisadi",
        ),
    ),
    RedFlagRule(
        id="self_harm",
        label_en="Thoughts of suicide or self-harm",
        label_ne="आत्महत्या वा आफूलाई हानि गर्ने विचार",
        any_of=(
            "suicide", "kill myself", "want to die", "end my life", "self harm", "self-harm", "hurt myself",
            "आत्महत्या", "मर्न मन", "बाँच्न मन छैन", "आफैलाई मार",
            "atmahatya", "marna man", "banchna man chaina",
        ),
        action_en="You are not alone. If you are in danger right now, call 102 or go to the nearest emergency department, and reach out to someone you trust.",
        action_ne="तपाईं एक्लै हुनुहुन्न। अहिले नै खतरा छ भने १०२ मा फोन गर्नुहोस् वा नजिकको आकस्मिक कक्षमा जानुहोस्, र विश्वास लाग्ने कसैसँग कुरा गर्नुहोस्।",
    ),
    RedFlagRule(
        id="severe_burn",
        label_en="Serious burn",
        label_ne="गम्भीर रूपमा पोलेको",
        any_of=(
            "severe burn", "badly burned", "burnt badly", "burned face", "electric shock",
            "नराम्ररी पोल", "आगोले पोल", "करेन्ट लाग",
            "naramrari pol", "current lagyo",
        ),
    ),
    RedFlagRule(
        id="head_injury",
        label_en="Serious head injury",
        label_ne="टाउकोमा गम्भीर चोट",
        all_groups=(
            ("head injury", "hit head", "hit his head", "hit her head", "fell on head", "टाउकोमा चोट", "टाउको फुट", "tauko ma chot", "tauko phut"),
            ("vomit", "बान्ता", "banta", "sleepy", "निदाउ", "confus", "bleeding", "रगत", "ragat", "unconscious", "बेहोस", "behosh"),
        ),
    ),
    RedFlagRule(
        id="infant_danger",
        label_en="Danger sign in a baby",
        label_ne="शिशुमा खतराको संकेत",
        all_groups=(
            ("baby", "infant", "newborn", "शिशु", "नवजात", "सानो बच्चा", "nani", "नानी", "bachcha", "बच्चा"),
            ("not feeding", "not breastfeeding", "won't feed", "दूध खाँदैन", "दूध चुस्दैन", "blue", "निलो",
             "very high fever", "fever and fits", "limp", "lethargic", "जिउ गल", "दूध खादैन", "dudh khadaina"),
        ),
    ),
)


def _normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def _has(phrase: str, norm: str) -> bool:
    """Latin phrases must start at a word boundary ("fits" must not match "benefits");
    Devanagari phrases match as substrings because Nepali attaches suffixes (छातीमा, छातीको)."""
    if phrase.isascii():
        return re.search(r"(?<![a-z])" + re.escape(phrase), norm) is not None
    return phrase in norm


def _flag(rule: RedFlagRule) -> dict:
    return {"id": rule.id, "label_en": rule.label_en, "label_ne": rule.label_ne,
            "action_en": rule.action_en, "action_ne": rule.action_ne}


def _run(rules: tuple[RedFlagRule, ...], text: str) -> list[dict]:
    norm = _normalize(text or "")
    hits = []
    for rule in rules:
        fired = any(_has(p, norm) for p in rule.any_of)
        if not fired and rule.all_groups:
            fired = all(any(_has(p, norm) for p in group) for group in rule.all_groups)
        if fired:
            hits.append(_flag(rule))
    return hits


def check_text(text: str) -> dict:
    """Return the red flags found in `text`.

    Result shape:
        {"is_emergency": bool, "flags": [{"id", "label_en", "label_ne", "action_en", "action_ne"}]}
    """
    hits = _run(RULES, text)
    return {"is_emergency": bool(hits), "flags": hits}


# ------------------------------------------------------------------ documents
#
# Words a report uses for results that need care the same day. Same matching as RULES, so
# "no pneumothorax" still fires: a false alarm is better than a missed one.

DOCUMENT_RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule(
        id="critical_result",
        label_en="The report marks a result as critical",
        label_ne="रिपोर्टमा कुनै नतिजालाई गम्भीर (क्रिटिकल) भनिएको छ",
        any_of=("critical value", "critical result", "critical alert", "panic value", "panic result",
                "critically high", "critically low", "क्रिटिकल"),
    ),
    RedFlagRule(
        id="critical_imaging",
        label_en="The report mentions a finding that can need emergency care",
        label_ne="रिपोर्टमा तुरुन्त उपचार चाहिन सक्ने कुरा लेखिएको छ",
        any_of=("pneumothorax", "free air", "pneumoperitoneum", "intracranial hemorrhage", "intracranial haemorrhage",
                "aortic dissection", "midline shift", "subdural", "extradural", "epidural hematoma"),
    ),
)


@dataclass(frozen=True)
class CriticalValue:
    id: str
    label_en: str
    label_ne: str
    names: tuple[str, ...]  # matched like RULES phrases against the item name
    # Limits in `unit`; other units are converted with `convert` (unit -> factor to `unit`).
    unit: str
    low: float | None
    high: float | None
    convert: tuple[tuple[str, float], ...] = ()
    # Words that, if present in the name, mean it is a different test (e.g. "urine sodium").
    exclude: tuple[str, ...] = ("urine", "csf", "fluid")


CRITICAL_VALUES: tuple[CriticalValue, ...] = (
    CriticalValue("potassium_critical", "Potassium is at a dangerous level", "पोटासियम खतरनाक तहमा छ",
                  ("potassium", "serum k", "k+"), "mmol/l", 2.5, 6.5, (("meq/l", 1.0),)),
    CriticalValue("sodium_critical", "Sodium is at a dangerous level", "सोडियम खतरनाक तहमा छ",
                  ("sodium", "serum na", "na+"), "mmol/l", 120, 160, (("meq/l", 1.0),)),
    CriticalValue("glucose_critical", "Blood sugar is at a dangerous level", "रगतमा चिनी खतरनाक तहमा छ",
                  ("glucose", "blood sugar", "fbs", "rbs", "ppbs"), "mg/dl", 54, 500, (("mmol/l", 18.0), ("mg%", 1.0))),
    CriticalValue("hemoglobin_critical", "Haemoglobin is very low", "हेमोग्लोबिन धेरै कम छ",
                  ("hemoglobin", "haemoglobin", "hb", "hgb"), "g/dl", 7.0, None, (("gm/dl", 1.0), ("gm%", 1.0), ("g%", 1.0), ("g/l", 0.1)),
                  exclude=("hba1c", "glycated", "glycosylated", "a1c", "hbsag", "hbs", "hbe", "hbv", "urine")),
    CriticalValue("platelets_critical", "Platelet count is very low", "प्लेटलेट धेरै कम छ",
                  ("platelet", "plt"), "10^3/ul", 20, None,
                  (("/ul", 0.001), ("/cumm", 0.001), ("/mm3", 0.001), ("10^9/l", 1.0), ("lakh/cumm", 100.0),
                   ("x10^3/ul", 1.0), ("k/ul", 1.0))),
)

_CRITICAL_ACTION_EN = "This result can be dangerous. Contact your doctor today, or call 102 / go to an emergency department if you feel unwell."
_CRITICAL_ACTION_NE = "यो नतिजा खतरनाक हुन सक्छ। आजै डाक्टरलाई सम्पर्क गर्नुहोस्, अस्वस्थ महसुस भए १०२ मा फोन गर्नुहोस् वा आकस्मिक कक्षमा जानुहोस्।"

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _number(value: str) -> float | None:
    """First number in a printed value. Commas are thousands separators in Nepal (1,50,000)."""
    m = _NUMBER.search((value or "").replace(",", ""))
    return float(m.group()) if m else None


def _unit_key(unit: str) -> str:
    u = (unit or "").lower().replace(" ", "").replace("µ", "u").replace("μ", "u")
    u = u.replace("10³", "10^3").replace("10⁹", "10^9").replace("³", "3")
    return u.replace("×", "x").replace("*", "x")


def _in_unit(cv: CriticalValue, value: float, unit: str) -> float | None:
    u = _unit_key(unit)
    if not u or u == cv.unit:
        return value
    for other, factor in sorted(cv.convert, key=lambda c: -len(c[0])):
        if u == other or u.endswith(other):
            return value * factor
    return None  # unknown unit: don't guess


def check_values(items: list[dict]) -> list[dict]:
    """Critical lab values. `items` are dicts with name, value, unit (from the model's extraction;
    the comparison itself is done here, in code)."""
    hits: dict[str, dict] = {}
    for item in items or []:
        name = _normalize(str(item.get("name", "")))
        for cv in CRITICAL_VALUES:
            if cv.id in hits or any(x in name for x in cv.exclude) or not any(_has(n, name) for n in cv.names):
                continue
            raw = _number(str(item.get("value", "")))
            if raw is None:
                continue
            v = _in_unit(cv, raw, str(item.get("unit", "")))
            if v is None:
                continue
            if (cv.low is not None and v <= cv.low) or (cv.high is not None and v >= cv.high):
                hits[cv.id] = {"id": cv.id, "label_en": cv.label_en, "label_ne": cv.label_ne,
                               "action_en": _CRITICAL_ACTION_EN, "action_ne": _CRITICAL_ACTION_NE}
    return list(hits.values())


def check_document(*texts: str, items: list[dict] | None = None) -> dict:
    """Everything for a scanned document: Matrix's red-flag rules and the document rules over all
    texts (the user's note, the document's own words, the model's explanation), plus critical
    lab values. Same result shape as check_text."""
    text = "\n".join(t for t in texts if t)
    hits = _run(RULES, text) + _run(DOCUMENT_RULES, text) + check_values(items or [])
    return {"is_emergency": bool(hits), "flags": hits}
