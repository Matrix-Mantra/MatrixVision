import io

import pytest
from PIL import Image

from app import imaging, segment

# Token format copied from dev.meta.ai/docs/sam/reading-segmentation (payloads shortened).
DOC_EXAMPLE = "<0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600|><|mask;x=0;y=0;data=122,376,~abc|>"
WITH_CONF = ("<0f>7<|box;x1=444;y1=625;x2=679;y2=850;w=1800;h=1200;c=0.9609375|><|mask;x=0;y=0;c=0.96;data=226,236,!x|>,"
             "9<|box;x1=10;y1=10;x2=12;y2=12;w=1800;h=1200;c=0.9|><|mask;x=0;y=0;data=2,2,!x|>,"
             "11<|box;x1=0;y1=0;x2=900;y2=600;w=1800;h=1200;c=0.2|><|mask;x=0;y=0;data=2,2,!x|>")


def _png(w=1200, h=1600, mode="RGB", fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), "white").save(buf, fmt)
    return buf.getvalue()


def test_parse_doc_example():
    assert segment.parse_boxes(DOC_EXAMPLE) == [{"x1": 181, "y1": 365, "x2": 556, "y2": 486, "w": 1516, "h": 1600}]


def test_parse_scales_to_our_image_size():
    (b,) = segment.parse_boxes(DOC_EXAMPLE, (758, 800))
    assert (b["x1"], b["y1"], b["x2"], b["y2"], b["w"], b["h"]) == (90, 182, 278, 243, 758, 800)


def test_parse_ignores_garbage_and_empty():
    assert segment.parse_boxes("") == []
    assert segment.parse_boxes("<0f>1<|box;x1=a;y1=2|>") == []
    assert segment.parse_boxes("<0f>1<|box;x1=50;y1=50;x2=10;y2=10;w=100;h=100|>") == []


def test_regions_drop_tiny_and_low_confidence():
    boxes = segment.parse_boxes(WITH_CONF)
    regions = segment.regions_from("x-ray image", boxes, (1800, 1200))
    assert len(regions) == 1
    r = regions[0]
    assert r.kind == "scan" and r.linkable and r.confidence == pytest.approx(0.96, abs=0.01)
    assert r.box == pytest.approx((444 / 1800, 625 / 1200, 680 / 1800, 851 / 1200))
    assert r.public(0)["id"] == "r0" and "box_px" not in r.public(0)


def test_page_regions_are_not_linkable_and_skipped_when_they_fill_the_photo():
    # Box from a live SAM 3.1 call: the sheet of paper inside a 1500x2000 photo.
    near = segment.parse_boxes("<0f>0<|box;x1=237;y1=267;x2=1272;y2=1623;w=1500;h=2000;c=0.89|>")
    (page,) = segment.regions_from("document", near, (1500, 2000))
    assert page.kind == "page" and not page.linkable
    full = segment.parse_boxes("<0f>0<|box;x1=5;y1=5;x2=1495;y2=1990;w=1500;h=2000;c=0.9|>")
    assert segment.regions_from("document", full, (1500, 2000)) == []


def test_merge_removes_overlaps():
    a = segment.Region("x-ray image", "scan", (0.1, 0.1, 0.9, 0.5), (1, 1, 9, 5), 0.9)
    b = segment.Region("document", "page", (0.12, 0.1, 0.9, 0.52), (1, 1, 9, 5), 0.8)
    c = segment.Region("document", "page", (0.1, 0.6, 0.9, 0.9), (1, 6, 9, 9), 0.8)
    assert segment.merge([a, b, c]) == [a, c]


def test_segment_runs_one_request_per_concept_and_survives_failures(monkeypatch):
    seen = []

    def fake(concept, data_url, model):
        seen.append((concept, model))
        assert data_url.startswith("data:image/jpeg;base64,")
        if concept == "document":
            raise ValueError("boom")
        return "<0f>1<|box;x1=100;y1=100;x2=1000;y2=600;w=1200;h=1600;c=0.9|><|mask;x=0;y=0;data=1,1,!x|>"

    monkeypatch.setattr(segment, "_request", fake)
    prepared = imaging.prepare(_png())
    regions = segment.segment(prepared, "xray")
    assert sorted(c for c, _ in seen) == ["document", "x-ray image"]
    assert [r.concept for r in regions] == ["x-ray image"]
    (jpeg,) = segment.crops(prepared, regions)
    assert Image.open(io.BytesIO(jpeg)).size[0] > 800


def test_prepare_resizes_and_strips_alpha():
    p = imaging.prepare(_png(4000, 3000, "RGBA"))
    assert p.image.mode == "RGB" and max(p.size) == 2000
    assert p.jpeg[:2] == b"\xff\xd8"


def test_prepare_applies_exif_rotation():
    img = Image.new("RGB", (1600, 1200), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    assert imaging.prepare(buf.getvalue()).size == (1200, 1600)


def test_prepare_heic():
    try:
        heic = _png(1000, 1200, fmt="HEIF")
    except Exception:
        pytest.skip("no HEIF encoder in this pillow-heif build")
    assert imaging.prepare(heic).size == (1000, 1200)


@pytest.mark.parametrize("data,code", [
    (b"%PDF-1.4 not an image", "bad_type"),
    (b"", "bad_type"),
    (None, "too_small"),
    (b"GIF89a" + b"\x00" * 20, "bad_type"),
])
def test_prepare_rejects(data, code):
    if data is None:
        data = _png(300, 300)
    with pytest.raises(imaging.BadImage) as e:
        imaging.prepare(data)
    assert e.value.code == code


def test_prepare_rejects_gif():
    buf = io.BytesIO()
    Image.new("RGB", (800, 800)).save(buf, "GIF")
    with pytest.raises(imaging.BadImage):
        imaging.prepare(buf.getvalue())


def test_prepare_rejects_huge_upload(monkeypatch):
    monkeypatch.setattr(imaging.config, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(imaging.BadImage) as e:
        imaging.prepare(_png())
    assert e.value.code == "too_large"
