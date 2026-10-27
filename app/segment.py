"""SAM 3.1 on the Meta Model API: find the paper in the photo, and the film on an X-ray.

SAM takes ONE concept per request ("document"), so concepts for a document type are sent in parallel.
Tested live: "document" finds the sheet of paper in a phone photo (so Muse Spark gets a close-up without the
table or bed behind it), and "x-ray image" finds the film. Text-level concepts ("table", "printed text",
"handwritten text") return nothing on a printed page, so they are not used.
Its answer is special-token text (dev.meta.ai/docs/sam/reading-segmentation):

    <0f>12<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600;c=0.96|><|mask;x=0;y=0;data=...|>,13<|box;...|>...

Box corners are source pixels (inclusive); w/h is the source size. We only need boxes (for crops and
highlighting), so masks are not decoded.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from . import config, imaging, meta_client

log = logging.getLogger("vision.sam")

# What to look for, per document type. Each phrase is one SAM request.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "lab_report": ("document",),
    "prescription": ("document",),
    "xray": ("x-ray image", "document"),
    "other_medical": ("document",),
}
# page: the sheet of paper, only used as a close-up for Muse Spark. scan: the film, also highlighted in the UI.
REGION_KIND = {"document": "page", "x-ray image": "scan"}

MAX_PER_CONCEPT = 4
MAX_REGIONS = 6
MIN_AREA = 0.01  # fraction of the image; smaller boxes are noise for our purpose
MIN_CONFIDENCE = 0.35
PAGE_MAX_AREA = 0.85  # a page that fills the photo adds nothing as a close-up

_BOX = re.compile(r"<\|box;([^|]*)\|>")


@dataclass
class Region:
    concept: str
    kind: str  # page | scan
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 as fractions of the image (for highlighting)
    box_px: tuple[int, int, int, int]
    confidence: float | None = None

    @property
    def linkable(self) -> bool:
        """Whether items may point at this region for highlighting (highlighting the whole page says nothing)."""
        return self.kind != "page"

    def public(self, index: int) -> dict:
        d = asdict(self)
        d.pop("box_px")
        d["id"] = f"r{index}"
        d["box"] = [round(v, 4) for v in self.box]
        return d


def parse_boxes(text: str, image_size: tuple[int, int] | None = None) -> list[dict]:
    """All box tokens in SAM output: [{"x1","y1","x2","y2","w","h","c"?}] with ints (c float).

    If the token's w/h differ from image_size, coordinates are scaled to image_size.
    """
    out = []
    for m in _BOX.finditer(text or ""):
        fields = {}
        for part in m.group(1).split(";"):
            k, _, v = part.partition("=")
            fields[k.strip()] = v.strip()
        try:
            b = {k: int(fields[k]) for k in ("x1", "y1", "x2", "y2", "w", "h")}
        except (KeyError, ValueError):
            log.warning("unreadable SAM box token: %s", m.group(0)[:120])
            continue
        if "c" in fields:
            try:
                b["c"] = float(fields["c"])
            except ValueError:
                pass
        if image_size and (b["w"], b["h"]) != tuple(image_size) and b["w"] and b["h"]:
            sx, sy = image_size[0] / b["w"], image_size[1] / b["h"]
            b.update(x1=round(b["x1"] * sx), x2=round(b["x2"] * sx), y1=round(b["y1"] * sy), y2=round(b["y2"] * sy),
                     w=image_size[0], h=image_size[1])
        if b["x2"] <= b["x1"] or b["y2"] <= b["y1"]:
            continue
        out.append(b)
    return out


def _iou(a: tuple, b: tuple) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def regions_from(concept: str, boxes: list[dict], size: tuple[int, int]) -> list[Region]:
    w, h = size
    regions = []
    for b in boxes:
        area = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]) / float(w * h)
        kind = REGION_KIND.get(concept, "scan")
        if area < MIN_AREA or (b.get("c") is not None and b["c"] < MIN_CONFIDENCE):
            continue
        if kind == "page" and area > PAGE_MAX_AREA:
            continue
        regions.append(Region(concept=concept, kind=kind,
                              box=(b["x1"] / w, b["y1"] / h, min(1.0, (b["x2"] + 1) / w), min(1.0, (b["y2"] + 1) / h)),
                              box_px=(b["x1"], b["y1"], b["x2"], b["y2"]), confidence=b.get("c")))
    regions.sort(key=lambda r: -(r.confidence if r.confidence is not None else 1.0))
    return regions[:MAX_PER_CONCEPT]


def merge(regions: list[Region]) -> list[Region]:
    """Drop near-duplicates across concepts (a table is often also "printed text"); keep the best."""
    kept: list[Region] = []
    for r in regions:
        if all(_iou(r.box, k.box) < 0.6 for k in kept):
            kept.append(r)
    return kept[:MAX_REGIONS]


def _request(concept: str, data_url: str, model: str) -> str:
    resp = meta_client.client().responses.create(
        model=model,
        input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": concept},
            {"type": "input_image", "image_url": data_url},
        ]}],
        # String values, as documented; one_bit masks are smaller and we don't use masks.
        metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
        store=False,
    )
    return meta_client.output_text(resp)


def segment(prepared: imaging.Prepared, document_type: str) -> list[Region]:
    """Regions for this document type. Never raises: without regions the full image is still read."""
    concepts = CONCEPTS.get(document_type) or CONCEPTS["other_medical"]
    data_url = prepared.data_url()

    def one(concept: str) -> list[Region]:
        try:
            text, _ = meta_client.call_with_fallback([config.SAM_MODEL], lambda m: _request(concept, data_url, m),
                                                     max_wait=4.0)
        except Exception as exc:
            log.warning("SAM failed for %r: %s", concept, type(exc).__name__)
            return []
        return regions_from(concept, parse_boxes(text, prepared.size), prepared.size)

    with ThreadPoolExecutor(max_workers=len(concepts)) as pool:
        found = [r for rs in pool.map(one, concepts) for r in rs]
    return merge(found)


def crops(prepared: imaging.Prepared, regions: list[Region]) -> list[bytes]:
    # A page close-up keeps full resolution so small print stays readable.
    return [imaging.crop(prepared.image, r.box_px, max_side=config.MAX_IMAGE_SIDE if r.kind == "page" else 1400)
            for r in regions]
