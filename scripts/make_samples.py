"""Draw synthetic sample documents for demos and tests. No real patient data: every name is invented and
every page is stamped SAMPLE.

    python scripts/make_samples.py   # writes samples/*.jpg
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
FONT = ROOT / "static" / "fonts" / "Mukta-Regular.ttf"
BOLD = ROOT / "static" / "fonts" / "Mukta-Bold.ttf"
W, H = 1240, 1754  # A4 at 150 dpi


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD if bold else FONT), size, layout_engine=ImageFont.Layout.RAQM
                              if ImageFont.core.HAVE_RAQM else ImageFont.Layout.BASIC)


def page(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), (252, 251, 247))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 150), fill=(24, 74, 120))
    d.text((60, 30), title, font=font(46, True), fill="white")
    d.text((60, 92), subtitle, font=font(24), fill=(220, 232, 245))
    d.text((W - 380, 40), "SAMPLE – synthetic", font=font(30, True), fill=(255, 210, 120))
    return img, d


def patient(d: ImageDraw.ImageDraw, y: int, name: str, age: str) -> int:
    f = font(26)
    d.text((60, y), f"Patient: {name}     Age/Sex: {age}     Date: 2026-10-20", font=f, fill=(30, 30, 30))
    d.text((60, y + 40), "Ref. by: Dr. Example (sample)     Lab No: S-0000", font=f, fill=(30, 30, 30))
    d.line((60, y + 90, W - 60, y + 90), fill=(160, 160, 160), width=2)
    return y + 110


def table(d: ImageDraw.ImageDraw, y: int, rows: list[tuple[str, str, str, str]]) -> int:
    cols = (60, 520, 720, 900)
    head = ("Test", "Result", "Unit", "Reference range")
    d.rectangle((50, y - 6, W - 50, y + 44), fill=(232, 239, 248))
    for x, h in zip(cols, head):
        d.text((x, y), h, font=font(28, True), fill=(20, 50, 90))
    y += 60
    for r in rows:
        bold = r[1].endswith("*")
        for x, v in zip(cols, r):
            d.text((x, y), v.rstrip("*"), font=font(28, bold and x == cols[1]), fill=(25, 25, 25))
        y += 52
        d.line((50, y - 8, W - 50, y - 8), fill=(225, 225, 225), width=1)
    return y + 20


def finish(img: Image.Image, name: str, angle: float = 0.0) -> None:
    """A little realism: slight rotation, blur and noise, as from a phone camera."""
    rnd = random.Random(name)
    if angle:
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(90, 80, 70))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(img.width * img.height // 60):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        r, g, b = px[x, y]
        n = rnd.randint(-18, 18)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    OUT.mkdir(exist_ok=True)
    img.save(OUT / name, "JPEG", quality=88)
    print("wrote", OUT / name)


def lab_report() -> None:
    img, d = page("Sunrise Diagnostic Lab (sample)", "Haematology & Biochemistry  ·  Kathmandu (fictional)")
    y = patient(d, 180, "Sita Example", "45 / F")
    d.text((60, y), "COMPLETE BLOOD COUNT", font=font(30, True), fill=(20, 50, 90))
    y = table(d, y + 50, [
        ("Haemoglobin (Hb)", "9.1*", "g/dL", "12.0 - 15.0"),
        ("Total WBC count", "7,800", "/cumm", "4,000 - 11,000"),
        ("Platelet count", "1,20,000*", "/cumm", "1,50,000 - 4,00,000"),
        ("MCV", "71*", "fL", "80 - 100"),
    ])
    d.text((60, y), "BIOCHEMISTRY", font=font(30, True), fill=(20, 50, 90))
    y = table(d, y + 50, [
        ("Fasting blood sugar", "132*", "mg/dL", "70 - 110"),
        ("Serum creatinine", "0.9", "mg/dL", "0.6 - 1.2"),
        ("Serum potassium", "4.2", "mmol/L", "3.5 - 5.1"),
        ("Total cholesterol", "238*", "mg/dL", "< 200"),
    ])
    d.text((60, y + 20), "* Values outside the reference range are printed in bold.", font=font(22), fill=(90, 90, 90))
    d.text((60, H - 140), "This is a SYNTHETIC SAMPLE for software testing. Not a real patient or laboratory.", font=font(24, True), fill=(160, 40, 40))
    finish(img, "lab_report.jpg", angle=1.2)


def lab_critical() -> None:
    img, d = page("Sunrise Diagnostic Lab (sample)", "Biochemistry  ·  Kathmandu (fictional)")
    y = patient(d, 180, "Ram Example", "68 / M")
    d.text((60, y), "RENAL FUNCTION TEST", font=font(30, True), fill=(20, 50, 90))
    y = table(d, y + 50, [
        ("Serum urea", "118*", "mg/dL", "15 - 45"),
        ("Serum creatinine", "4.6*", "mg/dL", "0.7 - 1.3"),
        ("Serum sodium", "131*", "mmol/L", "135 - 145"),
        ("Serum potassium", "6.9*", "mmol/L", "3.5 - 5.1"),
    ])
    d.rectangle((55, y, W - 55, y + 70), outline=(180, 30, 30), width=3)
    d.text((75, y + 16), "CRITICAL VALUE: potassium reported to ward by phone.", font=font(28, True), fill=(180, 30, 30))
    d.text((60, H - 140), "This is a SYNTHETIC SAMPLE for software testing. Not a real patient or laboratory.", font=font(24, True), fill=(160, 40, 40))
    finish(img, "lab_report_critical.jpg", angle=-0.8)


def prescription() -> None:
    img = Image.new("RGB", (W, H), (250, 248, 240))
    d = ImageDraw.Draw(img)
    d.text((60, 40), "Dr. A. Example, MBBS, MD (sample)", font=font(40, True), fill=(30, 40, 110))
    d.text((60, 95), "General Physician  ·  NMC No. 00000 (fictional)  ·  Pokhara", font=font(24), fill=(60, 60, 60))
    d.text((W - 380, 40), "SAMPLE – synthetic", font=font(30, True), fill=(200, 120, 20))
    d.line((60, 140, W - 60, 140), fill=(30, 40, 110), width=3)
    d.text((60, 165), "Name: Gita Example     Age: 32 F     Date: 2026-10-18", font=font(26), fill=(30, 30, 30))
    d.text((60, 210), "c/o tiredness, dizziness on standing. Hb 9.1 g/dL", font=font(26), fill=(30, 30, 30))
    d.text((60, 280), "Rx", font=font(72, True), fill=(30, 40, 110))
    ink = (25, 45, 130)
    lines = [
        "1. Tab. Ferrous sulphate 200 mg      1 - 0 - 1   after food   x 30 days",
        "2. Tab. Folic acid 5 mg                    0 - 0 - 1   x 30 days",
        "3. Tab. Pantoprazole 40 mg             1 - 0 - 0   before breakfast   x 14 days",
        "4. Syp. Lactulose 15 ml                    0 - 0 - 1   at bedtime, if constipated",
    ]
    y = 390
    for i, line in enumerate(lines):
        # Slightly uneven lines, like handwriting.
        d.text((90 + (i % 2) * 6, y + int(4 * math.sin(i))), line, font=font(32), fill=ink)
        y += 90
    d.text((60, y + 40), "Advice: eat green leafy vegetables, review after 1 month with CBC.", font=font(28), fill=ink)
    d.text((W - 360, y + 160), "Sd/- (sample)", font=font(30), fill=ink)
    d.text((60, H - 140), "This is a SYNTHETIC SAMPLE for software testing. Not a real prescription.", font=font(24, True), fill=(160, 40, 40))
    finish(img, "prescription.jpg", angle=-1.5)


def xray() -> None:
    """A stylised chest film beside a printed report (the film is drawn, not a real radiograph)."""
    img = Image.new("RGB", (W, H), (245, 245, 242))
    film = Image.new("L", (760, 900), 12)
    f = ImageDraw.Draw(film)
    f.ellipse((120, 160, 360, 760), fill=70)   # right lung field
    f.ellipse((400, 160, 640, 760), fill=70)   # left lung field
    f.rectangle((350, 80, 410, 820), fill=150)  # spine
    f.ellipse((360, 420, 560, 700), fill=165)  # heart
    for k in range(9):  # ribs
        yy = 200 + k * 58
        f.arc((100, yy - 60, 380, yy + 60), 200, 340, fill=140, width=7)
        f.arc((380, yy - 60, 660, yy + 60), 200, 340, fill=140, width=7)
    f.ellipse((60, 20, 700, 160), fill=110)  # shoulders
    film = film.filter(ImageFilter.GaussianBlur(6))
    img.paste(Image.merge("RGB", (film, film, film)), (60, 180))
    d = ImageDraw.Draw(img)
    d.text((60, 40), "City Imaging Centre (sample)", font=font(40, True), fill=(20, 50, 90))
    d.text((60, 100), "SAMPLE – synthetic drawing, not a real radiograph", font=font(26, True), fill=(200, 120, 20))
    x = 860
    d.text((x, 200), "CHEST X-RAY PA VIEW", font=font(28, True), fill=(20, 20, 20))
    report = ["Name: Hari Example", "Age/Sex: 52 / M", "", "FINDINGS:", "Mild blunting of right", "costophrenic angle.",
              "Heart size normal.", "Bony thorax normal.", "", "IMPRESSION:", "Small right pleural", "effusion.",
              "Clinical correlation", "advised."]
    for i, line in enumerate(report):
        d.text((x, 260 + i * 44), line, font=font(26, line.endswith(":")), fill=(20, 20, 20))
    d.text((60, H - 140), "This is a SYNTHETIC SAMPLE for software testing. Not a real patient.", font=font(24, True), fill=(160, 40, 40))
    finish(img, "xray.jpg", angle=0.6)


if __name__ == "__main__":
    lab_report()
    lab_critical()
    prescription()
    xray()
