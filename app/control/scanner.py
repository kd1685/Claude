"""OCR rankings scanner for the ADB backend.

Opens the in-game rankings list (Power / Kill Points / Dead), screenshots each
visible page, OCRs the per-row name + value regions defined in the calibration
profile, scrolls, and repeats. Returns de-duplicated rows ready to ingest as a
scan.
"""
from __future__ import annotations

from . import ocr
from .adapter import ActionResult

# Which snapshot column a rankings tab maps onto.
KIND_FIELD = {"power": "power", "killpoints": "kill_points", "dead": "deads"}


def scan_rankings_via_adb(adapter, *, kind: str, pages: int) -> ActionResult:
    if not ocr.available():
        return ActionResult(
            False,
            "OCR not available: install requirements-adb.txt and the tesseract "
            "binary, or set TESSERACT_CMD.",
        )

    rank_cfg = adapter.profile.rankings
    if not rank_cfg or "rows" not in rank_cfg:
        return ActionResult(False, "profile has no 'rankings' calibration block")

    tab_anchor = f"tab_{kind}"
    if tab_anchor not in adapter.profile.anchors:
        return ActionResult(False, f"no anchor '{tab_anchor}' in profile")

    field = KIND_FIELD.get(kind, "power")
    driver = adapter.driver

    # Open rankings and select the right tab.
    adapter.run_macro("open_rankings", {"tab_point": adapter.profile.anchors[tab_anchor]})

    seen: dict[str, dict] = {}
    scroll = rank_cfg.get("scroll")
    import time

    for _ in range(pages):
        png = driver.screencap()
        for row in rank_cfg["rows"]:
            name = ocr.ocr_region(png, row["name"]).strip().splitlines()
            name = name[0].strip() if name else ""
            if not name:
                continue
            value = ocr.parse_int(ocr.ocr_region(png, row["value"], digits=True))
            if value is None:
                continue
            seen[name] = {"name": name, field: value}
        if scroll:
            driver.swipe(*[int(v) for v in scroll[:4]],
                         ms=int(scroll[4]) if len(scroll) > 4 else 600)
            time.sleep(0.8)

    rows = sorted(seen.values(), key=lambda d: d.get(field, 0), reverse=True)
    # Close the rankings panel.
    try:
        adapter.run_macro("close_rankings", {})
    except Exception:
        driver.keyevent(4)
    return ActionResult(True, f"scanned {len(rows)} rows ({kind})", {"rows": rows})
