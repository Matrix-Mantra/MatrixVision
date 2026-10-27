"""Summary PDF (fpdf2 + HarfBuzz shaping, so Devanagari conjuncts render correctly). Built in memory."""

from __future__ import annotations

from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from . import config
from .store import NPT

FLAG_LABEL = {
    "ne": {"high": "बढी", "low": "कम", "abnormal": "असामान्य", "normal": "सामान्य", "unknown": "—"},
    "en": {"high": "High", "low": "Low", "abnormal": "Abnormal", "normal": "Normal", "unknown": "—"},
}
T = {
    "ne": {"title": "कागजातको सजिलो व्याख्या", "summary": "सारांश", "results": "जाँचका नतिजा", "medicines": "औषधि",
           "findings": "रिपोर्टमा लेखिएको", "department": "जानुपर्ने विभाग", "hospitals": "Matrix मा भएका अस्पताल",
           "questions": "डाक्टरलाई सोध्न सकिने प्रश्न", "test": "जाँच", "value": "नतिजा", "range": "सामान्य दायरा",
           "flag": "अवस्था", "emergency": "आपत्कालीन संकेत: अहिले नै १०२ मा फोन गर्नुहोस्", "made": "बनाएको"},
    "en": {"title": "Your document, explained simply", "summary": "Summary", "results": "Test results",
           "medicines": "Medicines", "findings": "What the report says", "department": "Department to visit",
           "hospitals": "Hospitals listed in Matrix", "questions": "Questions to ask your doctor", "test": "Test",
           "value": "Result", "range": "Normal range", "flag": "Status",
           "emergency": "Emergency sign: call 102 now", "made": "Made"},
}


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Mukta", size=8)
        self.set_text_color(110)
        self.cell(0, 6, f"Matrix Vision · {config.PUBLIC_ORIGIN} · {self.page_no()}", align="C")


def render_pdf(rep: dict, safety_result: dict, hospitals: list[dict]) -> bytes:
    lang = rep.get("lang", "ne")
    t = T[lang]
    pdf = _PDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_font("Mukta", "", str(config.FONT_DIR / "Mukta-Regular.ttf"))
    pdf.add_font("Mukta", "B", str(config.FONT_DIR / "Mukta-Bold.ttf"))
    pdf.set_text_shaping(True)
    pdf.add_page()

    def heading(text: str, size: int = 13):
        pdf.ln(2)
        pdf.set_font("Mukta", "B", size)
        pdf.set_text_color(20, 60, 110)
        pdf.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0)
        pdf.set_font("Mukta", size=10.5)

    def para(text: str, h: float = 5.6):
        if text:
            pdf.multi_cell(0, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    heading(t["title"], 17)
    pdf.set_font("Mukta", size=9)
    pdf.set_text_color(90)
    para(f"{t['made']}: {datetime.now(NPT).strftime('%Y-%m-%d %H:%M')}")
    pdf.set_text_color(0)

    if safety_result.get("is_emergency"):
        pdf.set_fill_color(180, 20, 30)
        pdf.set_text_color(255)
        pdf.set_font("Mukta", "B", 12)
        pdf.multi_cell(0, 8, " " + t["emergency"], fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Mukta", size=10)
        for f in safety_result["flags"]:
            pdf.multi_cell(0, 6, f" • {f['label_' + lang]}: {f['action_' + lang]}", fill=True,
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0)
    pdf.set_fill_color(232, 239, 248)  # table headings

    heading(t["summary"])
    para(rep.get("summary", {}).get(lang, ""))

    items = rep.get("items") or []
    if items:
        heading(t["results"])
        pdf.set_font("Mukta", size=9.5)
        with pdf.table(col_widths=(34, 18, 22, 14, 52), line_height=5.4, first_row_as_headings=True) as table:
            row = table.row()
            for c in (t["test"], t["value"], t["range"], t["flag"], ""):
                row.cell(c)
            for i in items:
                row = table.row()
                row.cell(i.get("name", ""))
                row.cell(f"{i.get('value', '')} {i.get('unit') or ''}".strip())
                row.cell(i.get("reference_range") or "")
                row.cell(FLAG_LABEL[lang].get(i.get("flag", "unknown"), "—"))
                row.cell(i.get(f"explanation_{lang}", ""))
        pdf.set_font("Mukta", size=10.5)

    meds = rep.get("medicines") or []
    if meds:
        heading(t["medicines"])
        for m in meds:
            how = " · ".join(x for x in (m.get("strength"), m.get("dose"), m.get("frequency"), m.get("timing"),
                                          m.get("duration")) if x)
            pdf.set_font("Mukta", "B", 10.5)
            para(f"{m.get('name', '')}  {how}")
            pdf.set_font("Mukta", size=10.5)
            para(m.get(f"explanation_{lang}", ""))

    findings = rep.get("findings") or []
    if findings:
        heading(t["findings"])
        for f in findings:
            pdf.set_font("Mukta", "B", 10.5)
            para(f.get("text", ""))
            pdf.set_font("Mukta", size=10.5)
            para(f.get(f"explanation_{lang}", ""))

    dept = rep.get("department") or {}
    heading(t["department"])
    para(f"{dept.get(lang) or dept.get('en') or dept.get('id', '')}. {(dept.get('reason') or {}).get(lang, '')}")

    if hospitals:
        heading(t["hospitals"])
        for h in hospitals:
            name = h.get("name_ne") if lang == "ne" and h.get("name_ne") else h.get("name", "")
            pdf.set_font("Mukta", "B", 10.5)
            pdf.multi_cell(0, 5.6, f"{name} — {h.get('district') or ''}", link=h.get("matrix_url"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Mukta", size=9)
            pdf.set_text_color(20, 60, 160)
            pdf.multi_cell(0, 5, h.get("matrix_url", ""), link=h.get("matrix_url"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0)
        pdf.set_font("Mukta", size=10.5)

    qs = (rep.get("questions_for_doctor") or {}).get(lang) or []
    if qs:
        heading(t["questions"])
        for q in qs:
            para(f"• {q}")

    pdf.ln(3)
    pdf.set_font("Mukta", size=9)
    pdf.set_text_color(70)
    disc = rep.get("disclaimer") or {}
    para(disc.get("ne", ""), 5)
    para(disc.get("en", ""), 5)
    return bytes(pdf.output())
