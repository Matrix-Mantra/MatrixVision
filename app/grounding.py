"""Grounding in Matrix: hospitals come only from Matrix's public API, never from the model.

The model suggests a department (one of Matrix's department ids). Code fetches the hospitals for it,
and any hospital name in the model's text that is not on that list is removed here, in code.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

from . import config

log = logging.getLogger("vision.matrix")

# Used when Matrix's /api/config can't be reached (copied from it; Matrix stays the source of truth).
FALLBACK_DEPARTMENTS = (
    "emergency", "general_medicine", "general_surgery", "cardiology", "neurology", "neurosurgery", "orthopedics",
    "obstetrics_gynecology", "pediatrics", "ophthalmology", "ent", "dermatology", "psychiatry", "oncology",
    "nephrology", "gastroenterology", "pulmonology", "urology", "dental", "burns",
)

# ------------------------------------------------------------------ Matrix API client (short TTL cache)

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _get(path: str, params: dict | None = None) -> Any:
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()) if v is not None)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < config.MATRIX_CACHE_SECONDS:
            return hit[1]
    resp = httpx.get(config.MATRIX_API_BASE + path, params={k: v for k, v in (params or {}).items() if v is not None},
                     timeout=config.MATRIX_TIMEOUT_SECONDS, headers={"User-Agent": "MatrixVision/0.1"})
    resp.raise_for_status()
    data = resp.json()
    with _lock:
        _cache[key] = (now, data)
    return data


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def matrix_config() -> dict:
    """Matrix's public start-up config (departments, districts, Firebase web config). {} if unreachable."""
    try:
        return _get("/api/config")
    except Exception:
        log.exception("Matrix /api/config unreachable")
        return {}


def departments() -> dict[str, dict]:
    deps = matrix_config().get("departments") or {}
    return deps or {d: {"en": d.replace("_", " ").title(), "ne": ""} for d in FALLBACK_DEPARTMENTS}


def all_hospitals() -> list[dict]:
    try:
        return _get("/api/hospitals").get("hospitals", [])
    except Exception:
        log.exception("Matrix /api/hospitals unreachable")
        return []


def hospital_url(hospital_id: str) -> str:
    """The hospital's page in Matrix (#/h/<id>)."""
    return config.MATRIX_HOSPITAL_URL.replace("{id}", quote(hospital_id, safe=""))


def _public(h: dict) -> dict:
    keep = ("id", "name", "name_ne", "type", "type_label", "city", "district", "province", "emergency_24h",
            "health_insurance", "phone", "verified", "directions_url")
    out = {k: h.get(k) for k in keep}
    out["matrix_url"] = hospital_url(h["id"])
    return out


def hospitals_for(department: str, district: str | None = None, lang: str = "ne", limit: int = 5) -> dict:
    """Hospitals with this department, nearest-district first when a district is given.

    Returns {"department", "district", "scope": "district"|"national"|"none", "hospitals": [...]}.
    """
    rows: list[dict] = []
    scope = "none"
    try:
        if district:
            rows = _get("/api/hospitals", {"department": department, "district": district, "lang": lang})["hospitals"]
            scope = "district" if rows else scope
        if not rows:
            # Matrix sorts by distance from `near` when it is given.
            rows = _get("/api/hospitals", {"department": department, "near": district, "lang": lang})["hospitals"]
            scope = "national" if rows else "none"
    except Exception:
        log.exception("Matrix hospital search failed")
        rows, scope = [], "none"
    return {"department": department, "district": district, "scope": scope,
            "hospitals": [_public(h) for h in rows[:limit] if h.get("id")]}


# ------------------------------------------------------------------ the filter

# English: one or more capitalised words (or initials) followed by a facility word.
_EN_FACILITY = r"(?:Hospitals?|Medical College|Cent(?:er|re)|Clinic|Polyclinic|Nursing Home|Health Post|Memorial|(?:Institute|Academy)(?: of(?: [A-Z][\w.-]*)+)?)"
_EN_NAME = re.compile(r"\b(?:[A-Z][\w.'&-]*\s+(?:(?:of|and|for|the)\s+)?){1,6}" + _EN_FACILITY + r"\b")
# Capitalised words that start sentences, not names ("Try X Hospital", "The Hospital").
_EN_LEAD = {"Try", "Go", "Visit", "See", "Please", "The", "At", "In", "To", "From", "Your", "A", "An", "Or", "And",
            "Ask", "Call", "Contact", "Consult", "Any", "This", "That", "Nearest", "Nearby", "Government", "Private",
            "Big", "Large", "Local", "District", "Zonal", "Regional", "Teaching", "Referral", "Help", "Information",
            "Service", "Customer", "Health", "Medical", "Eye", "Heart", "Cancer", "Trauma", "Dialysis", "Diagnostic"}
# Nepali: words before a facility word. Generic words ("नजिकको सरकारी अस्पताल") are not names.
_NE_FACILITY = ("अस्पताल", "मेडिकल कलेज", "क्लिनिक", "नर्सिङ होम", "स्वास्थ्य चौकी", "प्रतिष्ठान", "केन्द्र", "सेन्टर",
                "इन्स्टिच्युट", "एकेडेमी")
# Words that end a name when walking back from the facility word.
_NE_STOP = {
    "नजिकको", "नजिकैको", "नजिक", "नजिकका", "कुनै", "त्यो", "यो", "यी", "ती", "आफ्नो", "मेरो", "हाम्रो", "तपाईंको", "तपाईको",
    "राम्रो", "ठूलो", "ठूला", "सानो", "सूचीमा", "सूचीका", "माथिको", "माथिका", "तलको", "तलका", "एउटा", "कुन", "अर्को", "वा",
    "र", "भएको", "भएका", "दिइएको", "दिइएका", "मा", "को", "का", "की", "ले", "लाई", "धेरै", "सबै", "उक्त", "Matrix",
    "म्याट्रिक्स", "जानुहोस्", "जानुहोस्।", "गर्नुहोस्", "गर्नुहोस्।",
}
# Type words: part of a name ("डोटी जिल्ला अस्पताल") but not a name on their own ("सरकारी अस्पताल").
_NE_TYPE = {
    "सरकारी", "निजी", "सामुदायिक", "जिल्ला", "प्रादेशिक", "क्षेत्रीय", "अञ्चल", "केन्द्रीय", "स्थानीय", "विशेषज्ञ", "शिक्षण",
    "आकस्मिक", "रेफरल", "राष्ट्रिय", "आँखा", "मुटु", "बाल", "प्रसूति", "क्यान्सर", "विभाग",
}
_DEVANAGARI_CHAR = re.compile(r"[\u0900-\u097F]")
_DEVANAGARI_WORD = re.compile(r"^[ऀ-ॿ]+[,।]?$")

REPLACEMENT = {"en": "a hospital", "ne": "अस्पताल"}


def _names(h: dict) -> set[str]:
    return {n.strip() for n in (h.get("name"), h.get("name_ne")) if n and n.strip()}


def _lang_at(text: str, start: int, end: int) -> str:
    """Nepali if the name itself, or the word right before or after it, is Devanagari ("Bir Hospital मा")."""
    if _DEVANAGARI_CHAR.search(text[start:end]):
        return "ne"
    after = text[end:].lstrip()[:1]
    before = text[:start].rstrip()[-1:]
    return "ne" if _DEVANAGARI_CHAR.match(after or " ") or _DEVANAGARI_CHAR.match(before or " ") else "en"


def _strip_nepali(text: str) -> str:
    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        hit = None
        for fac in sorted(_NE_FACILITY, key=len, reverse=True):
            fw = fac.split(" ")
            got = tokens[i:i + len(fw)]
            # The last word may carry a case ending: अस्पतालमा, कलेजबाट, अस्पतालमध्ये.
            if len(got) == len(fw) and got[:-1] == fw[:-1] and got[-1].startswith(fw[-1]) \
                    and len(got[-1]) <= len(fw[-1]) + 6:
                hit = fw
                break
        if hit is None:
            out.append(tokens[i])
            i += 1
            continue
        # Walk back over the name's words (Devanagari, not a stop word), at most 5.
        j = len(out)
        while j > 0 and len(out) - j < 5 and _DEVANAGARI_WORD.match(out[j - 1]) and out[j - 1].rstrip(",।") not in _NE_STOP:
            j -= 1
        if any(w.rstrip(",।") not in _NE_TYPE for w in out[j:]):
            out[j:] = [REPLACEMENT["ne"] + tokens[i + len(hit) - 1][len(hit[-1]):]]
        else:
            out.extend(tokens[i:i + len(hit)])
        i += len(hit)
    return " ".join(out)


def _strip_english(text: str) -> str:
    def sub(m: re.Match) -> str:
        words = m.group(0).split()
        lead = 0
        while lead < len(words) - 1 and (words[lead] in _EN_LEAD or words[lead].islower()):
            lead += 1
        if len(words) - lead < 2:  # "The Hospital", "Nearest Hospital": generic
            return m.group(0)
        prefix = words[:lead]
        if prefix and prefix[-1].lower() in ("the", "a", "an"):
            prefix = prefix[:-1]
        return " ".join(prefix + [REPLACEMENT[_lang_at(m.string, m.start(), m.end())]])

    return _EN_NAME.sub(sub, text)


def strip_unlisted(text: str, allowed: list[dict], directory: list[dict] | None = None) -> str:
    """Remove hospital names that are not in `allowed` (Matrix rows). `directory` is Matrix's full list,
    so known names are caught even when they don't look like names."""
    if not text:
        return text
    # 1) Known names, longest first (so "Universal College of ... Hospital" is handled before the
    #    "College of ... Hospital" inside it): allowed ones are masked so nothing below touches them,
    #    the rest are replaced.
    allowed_names = set().union(*(_names(h) for h in allowed)) if allowed else set()
    known = sorted(allowed_names | {n for h in directory or [] for n in _names(h)}, key=len, reverse=True)
    masks = {}
    for n in known:
        if n not in text:
            continue
        if n in allowed_names:
            mask = f"\ue000{len(masks)}\ue001"
            masks[mask] = n
            text = text.replace(n, mask)
        else:
            text = re.sub(re.escape(n), lambda m: REPLACEMENT[_lang_at(m.string, m.start(), m.end())], text)
    # 2) and 3) Anything else that looks like a hospital name.
    text = _strip_nepali(_strip_english(text))
    for mask, n in masks.items():
        text = text.replace(mask, n)
    return text


def ground(obj: Any, allowed: list[dict], directory: list[dict] | None = None) -> Any:
    """strip_unlisted on every string inside a JSON-like structure."""
    if isinstance(obj, str):
        return strip_unlisted(obj, allowed, directory)
    if isinstance(obj, list):
        return [ground(x, allowed, directory) for x in obj]
    if isinstance(obj, dict):
        return {k: ground(v, allowed, directory) for k, v in obj.items()}
    return obj
