"""OCR helpers. Heavy deps (PIL/pytesseract) are imported lazily so the rest of
the app works even when they are not installed (e.g. mock backend on a laptop).
"""
from __future__ import annotations

import io
import re

from ..config import config

_AVAILABLE: bool | None = None


def available() -> bool:
    """True if Pillow + pytesseract + the tesseract binary are usable."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        if config.TESSERACT_CMD and config.TESSERACT_CMD != "tesseract":
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
        _AVAILABLE = True
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


def _preprocess(img):
    """Grayscale + upscale + threshold; helps tesseract on game fonts."""
    from PIL import Image, ImageOps
    img = ImageOps.grayscale(img)
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.LANCZOS)
    img = img.point(lambda p: 255 if p > 140 else 0)
    return img


def ocr_region(png_bytes: bytes, region: list[int] | None = None,
               digits: bool = False) -> str:
    """OCR a screenshot (optionally a [x, y, w, h] crop). Returns raw text."""
    if not available():
        return ""
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if region:
        x, y, w, h = region
        img = img.crop((x, y, x + w, y + h))
    img = _preprocess(img)
    cfg = "--psm 6"
    if digits:
        cfg += " -c tessedit_char_whitelist=0123456789,."
    return pytesseract.image_to_string(img, config=cfg)


def parse_int(text: str) -> int | None:
    """Pull the first integer out of OCR text (strips thousands separators)."""
    m = re.search(r"[\d][\d.,\s]*", text)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(0))
    return int(digits) if digits else None
