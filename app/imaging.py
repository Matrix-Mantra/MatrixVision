"""Image handling, all in memory: decode (JPEG/PNG/HEIC/WebP), fix rotation, resize, re-encode, crop."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from . import config

register_heif_opener()
# A 2000 px phone photo is ~12 MP; refuse anything absurd before decoding it (decompression bombs).
Image.MAX_IMAGE_PIXELS = 60_000_000

ACCEPTED_FORMATS = {"JPEG", "PNG", "HEIF", "WEBP", "MPO"}  # MPO: some phones' JPEGs
MIN_SIDE = 400


class BadImage(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Prepared:
    image: Image.Image  # RGB, resized
    jpeg: bytes

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def data_url(self) -> str:
        return to_data_url(self.jpeg)


def to_data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def encode_jpeg(img: Image.Image, quality: int | None = None) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality or config.JPEG_QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def prepare(data: bytes) -> Prepared:
    """Validate and normalise an upload. Raises BadImage with a code the browser can translate."""
    if len(data) > config.MAX_IMAGE_BYTES:
        raise BadImage("too_large", "The photo is too large.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        if fmt not in ACCEPTED_FORMATS:
            raise BadImage("bad_type", "Please upload a JPEG, PNG or HEIC photo.")
        img.load()
    except BadImage:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise BadImage("bad_type", "Please upload a JPEG, PNG or HEIC photo.") from exc
    img = ImageOps.exif_transpose(img)  # phones store rotation in EXIF
    if min(img.size) < MIN_SIDE:
        raise BadImage("too_small", "The photo is too small to read. Please take a closer, clearer photo.")
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    # Re-encoding also drops EXIF (GPS, device) from what is sent onwards.
    return Prepared(image=img, jpeg=encode_jpeg(img))


def crop(img: Image.Image, box_px: tuple[int, int, int, int], pad: float = 0.03, max_side: int = 1400) -> bytes:
    """JPEG of a region (x1, y1, x2, y2 in pixels, inclusive), with a little padding."""
    w, h = img.size
    x1, y1, x2, y2 = box_px
    px, py = int((x2 - x1) * pad) + 4, int((y2 - y1) * pad) + 4
    region = img.crop((max(0, x1 - px), max(0, y1 - py), min(w, x2 + 1 + px), min(h, y2 + 1 + py)))
    region.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return encode_jpeg(region, quality=85)
