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


def _preprocess(img, invert: bool = False, soft: bool = False, scale: int = 2):
    """Grayscale + upscale + (threshold | autocontrast); helps tesseract on game
    fonts. `soft` keeps glyph shapes (better for stylized names); the hard
    threshold is better for clean digits."""
    from PIL import Image, ImageOps
    img = ImageOps.grayscale(img)
    w, h = img.size
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    if soft:
        img = ImageOps.autocontrast(img)
    else:
        img = img.point(lambda p: 255 if p > 140 else 0)
    if invert:                       # black-on-white reads better for some fonts
        img = ImageOps.invert(img)
    return img


def ocr_region(png_bytes: bytes, region: list[int] | None = None,
               digits: bool = False, invert: bool = False,
               soft: bool = False, scale: int = 2) -> str:
    """OCR a screenshot (optionally a [x, y, w, h] crop). Returns raw text."""
    if not available():
        return ""
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if region:
        x, y, w, h = region
        img = img.crop((x, y, x + w, y + h))
    img = _preprocess(img, invert=invert, soft=soft, scale=scale)
    if digits:
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,."
    else:
        cfg = "--psm 7"
    return pytesseract.image_to_string(img, config=cfg)


def read_name_region(png_bytes: bytes, region: list[int]) -> str:
    """Read a governor name as accurately as we can: try a few preprocessing
    variants and keep the one with the most letters (stylized RoK font)."""
    best = ""
    for soft in (True, False):
        for inv in (True, False):
            t = ocr_region(png_bytes, region, invert=inv, soft=soft, scale=3)
            line = t.strip().splitlines()
            line = line[0].strip() if line else ""
            letters = sum(c.isalnum() for c in line)
            if letters > sum(c.isalnum() for c in best):
                best = line
    return best


def read_int_region(png_bytes: bytes, region: list[int]) -> int | None:
    """Read a number from a region, trying both polarities (yellow rank numbers
    on a blue row read much better inverted)."""
    for inv in (False, True):
        v = parse_int(ocr_region(png_bytes, region, digits=True, invert=inv))
        if v is not None:
            return v
    return None


def parse_int(text: str) -> int | None:
    """Pull the first integer out of OCR text (strips thousands separators)."""
    m = re.search(r"[\d][\d.,\s]*", text)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(0))
    return int(digits) if digits else None


def find_text(png_bytes: bytes, target: str, min_ratio: float = 0.72):
    """Locate `target` text anywhere in a screenshot. Returns (x, y) device-pixel
    centre of the best-matching word, or None. Used to spot a governor's
    nameplate while panning the map."""
    if not available() or not target:
        return None
    import difflib

    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    proc = _preprocess(img)            # upscaled x2 in _preprocess
    data = pytesseract.image_to_data(proc, output_type=pytesseract.Output.DICT)
    target_l = re.sub(r"[^a-z0-9]", "", target.lower())
    best, best_r = None, 0.0
    for i, word in enumerate(data["text"]):
        w = re.sub(r"[^a-z0-9]", "", word.lower())
        if len(w) < 3:
            continue
        r = difflib.SequenceMatcher(None, w, target_l).ratio()
        if r > best_r:
            best_r = r
            cx = (data["left"][i] + data["width"][i] / 2) / 2   # /2: undo upscale
            cy = (data["top"][i] + data["height"][i] / 2) / 2
            best = (int(cx), int(cy))
    return best if best and best_r >= min_ratio else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def read_labeled_values(png_bytes: bytes, labels: dict[str, str]) -> dict[str, int]:
    """Statsmaster-style label-based reading: for each {field: 'Label Text'}, find
    the on-screen row containing that label and return the number to its right.
    Resolution/layout independent — no fixed pixel regions."""
    if not available() or not labels:
        return {}
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    d = pytesseract.image_to_data(_preprocess(img), output_type=pytesseract.Output.DICT)

    # Group recognised words into screen lines, sorted left-to-right.
    from collections import defaultdict
    lines: dict = defaultdict(list)
    for i, raw in enumerate(d["text"]):
        if raw.strip():
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            lines[key].append((d["left"][i], raw))

    out: dict[str, int] = {}
    for field, label in labels.items():
        ltoks = [_norm(t) for t in label.split() if _norm(t)]
        if not ltoks:
            continue
        for words in lines.values():
            toks = [(lx, _norm(t), t) for lx, t in sorted(words)]
            for i in range(len(toks) - len(ltoks) + 1):
                if all(ltoks[j] in toks[i + j][1] for j in range(len(ltoks))):
                    digits = ""
                    for _lx, ntok, raw in toks[i + len(ltoks):]:
                        if re.search(r"\d", raw):
                            digits += re.sub(r"[^0-9]", "", raw)
                        elif digits:                 # number ended
                            break
                    if digits:
                        out[field] = int(digits)
                    break
            if field in out:
                break
    return out
