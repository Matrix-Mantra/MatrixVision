"""What Muse Spark must return (as JSON Schema for structured output) and its pydantic mirror for validation.

The JSON Schema follows the strict subset (dev.meta.ai/docs/structured-output): the root is an object,
every object has additionalProperties: false, and `required` lists every property (optional values
are nullable instead).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DOC_TYPES = ("lab_report", "prescription", "xray", "other_medical")
FLAGS = ("high", "low", "abnormal", "normal", "unknown")
URGENCY = ("emergency", "soon", "routine")


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


_S = {"type": "string"}
_NS = {"type": ["string", "null"]}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


CLASSIFY_SCHEMA = _obj({
    "is_medical_document": {"type": "boolean"},
    "document_type": {"type": "string", "enum": [*DOC_TYPES, "not_medical"]},
    "readable": {"type": "boolean"},
    "reason": _S,
})


def extraction_schema(department_ids: list[str]) -> dict:
    return _obj({
        "document_type": {"type": "string", "enum": list(DOC_TYPES)},
        "document_text": _S,
        "items": _arr(_obj({
            "name": _S, "value": _S, "unit": _NS, "reference_range": _NS,
            "flag": {"type": "string", "enum": list(FLAGS)},
            "region_id": _NS, "explanation_ne": _S, "explanation_en": _S,
        })),
        "medicines": _arr(_obj({
            "name": _S, "strength": _NS, "dose": _NS, "frequency": _NS, "timing": _NS, "duration": _NS,
            "region_id": _NS, "explanation_ne": _S, "explanation_en": _S,
        })),
        "findings": _arr(_obj({"text": _S, "region_id": _NS, "explanation_ne": _S, "explanation_en": _S})),
        "summary_ne": _S,
        "summary_en": _S,
        "suggested_department": {"type": "string", "enum": department_ids},
        "department_reason_ne": _S,
        "department_reason_en": _S,
        "urgency": {"type": "string", "enum": list(URGENCY)},
        "questions_for_doctor_ne": _arr(_S),
        "questions_for_doctor_en": _arr(_S),
        "unreadable_parts": _arr(_S),
    })


ANSWER_SCHEMA = _obj({"question_understood_ne": _S, "answer_ne": _S, "answer_en": _S, "region_ids": _arr(_S)})


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Classification(_M):
    is_medical_document: bool
    document_type: Literal["lab_report", "prescription", "xray", "other_medical", "not_medical"]
    readable: bool
    reason: str = ""


class Item(_M):
    name: str = Field(max_length=200)
    value: str = Field(max_length=100)
    unit: str | None = Field(default=None, max_length=40)
    reference_range: str | None = Field(default=None, max_length=120)
    flag: Literal["high", "low", "abnormal", "normal", "unknown"] = "unknown"
    flag_source: Literal["range", "model"] = "model"
    region_id: str | None = None
    explanation_ne: str = ""
    explanation_en: str = ""


class Medicine(_M):
    name: str = Field(max_length=200)
    strength: str | None = None
    dose: str | None = None
    frequency: str | None = None
    timing: str | None = None
    duration: str | None = None
    region_id: str | None = None
    explanation_ne: str = ""
    explanation_en: str = ""


class Finding(_M):
    text: str
    region_id: str | None = None
    explanation_ne: str = ""
    explanation_en: str = ""


class Extraction(_M):
    document_type: Literal["lab_report", "prescription", "xray", "other_medical"]
    document_text: str = Field(default="", max_length=20000)
    items: list[Item] = Field(default_factory=list, max_length=150)
    medicines: list[Medicine] = Field(default_factory=list, max_length=60)
    findings: list[Finding] = Field(default_factory=list, max_length=40)
    summary_ne: str = ""
    summary_en: str = ""
    suggested_department: str = "general_medicine"
    department_reason_ne: str = ""
    department_reason_en: str = ""
    urgency: Literal["emergency", "soon", "routine"] = "routine"
    questions_for_doctor_ne: list[str] = Field(default_factory=list, max_length=10)
    questions_for_doctor_en: list[str] = Field(default_factory=list, max_length=10)
    unreadable_parts: list[str] = Field(default_factory=list, max_length=20)


class Answer(_M):
    question_understood_ne: str = ""
    answer_ne: str
    answer_en: str
    region_ids: list[str] = Field(default_factory=list)
