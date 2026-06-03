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


def scan_rallies_via_adb(adapter, *, pages: int) -> ActionResult:
    """Read the alliance war/rally reports and return one row per rally."""
    if not ocr.available():
        return ActionResult(False, "OCR not available (install requirements-adb.txt + tesseract)")
    cfg = adapter.profile.data.get("war_reports")
    if not cfg or "rows" not in cfg:
        return ActionResult(False, "profile has no 'war_reports' calibration block")

    driver = adapter.driver
    adapter.run_macro("open_war_reports", {})
    import re
    import time

    seen: dict[str, dict] = {}
    scroll = cfg.get("scroll")
    for _ in range(pages):
        png = driver.screencap()
        for row in cfg["rows"]:
            leader = ocr.ocr_region(png, row["leader"]).strip().splitlines()
            leader = leader[0].strip() if leader else ""
            if not leader:
                continue
            target = ""
            if row.get("target"):
                t = ocr.ocr_region(png, row["target"]).strip().splitlines()
                target = t[0].strip() if t else ""
            status = "win"
            if row.get("status"):
                s = ocr.ocr_region(png, row["status"]).lower()
                status = "loss" if ("def" in s or "loss" in s or "lost" in s) else "win"
            key = f"{leader}|{target}"
            seen[key] = {"leader_name": leader, "target_label": target, "status": status}
        if scroll:
            driver.swipe(*[int(v) for v in scroll[:4]],
                         ms=int(scroll[4]) if len(scroll) > 4 else 600)
            time.sleep(0.8)

    try:
        adapter.run_macro("close_rankings", {})
    except Exception:
        driver.keyevent(4)
    rows = list(seen.values())
    return ActionResult(True, f"read {len(rows)} rallies", {"rows": rows})


# Profile fields read from the Governor Profile / More Info screens.
_PROFILE_FIELDS = ("power", "kill_points", "t1_kills", "t2_kills", "t3_kills",
                   "t4_kills", "t5_kills", "deads", "rss_assist", "rss_gathered")


def scan_profiles_via_adb(adapter, *, pages: int) -> ActionResult:
    """Deep scan (Statsmaster-style): open each governor's profile + More Info and
    OCR the full stat block, including DEAD troops which the list view lacks."""
    if not ocr.available():
        return ActionResult(False, "OCR not available (install requirements-adb.txt + tesseract)")
    cfg = adapter.profile.data.get("profiles")
    if not cfg or "row_taps" not in cfg:
        return ActionResult(False, "profile has no 'profiles' deep-scan calibration block")

    driver = adapter.driver
    import time
    # Open the Power ranking (same entry point as the list scan).
    adapter.run_macro("open_rankings", {"tab_point": adapter.profile.anchors["tab_power"]})

    pfields = cfg.get("profile_fields", {})
    mfields = cfg.get("more_fields", {})
    back_n = int(cfg.get("back_to_list", 2))
    seen: dict[str, dict] = {}

    for _ in range(pages):
        for tap in cfg["row_taps"]:
            driver.tap(int(tap[0]), int(tap[1]))
            time.sleep(1.4)                       # governor profile opens
            png = driver.screencap()
            row = {}
            if pfields.get("name"):
                nm = ocr.ocr_region(png, pfields["name"]).strip().splitlines()
                row["name"] = nm[0].strip() if nm else ""
            for f in ("power", "kill_points"):
                if pfields.get(f):
                    row[f] = ocr.parse_int(ocr.ocr_region(png, pfields[f], digits=True))
            # Open "More Info" for the detailed stats (incl. deads).
            try:
                adapter.run_macro("open_more_info", {})
                time.sleep(1.0)
                png2 = driver.screencap()
                for f in _PROFILE_FIELDS:
                    if mfields.get(f):
                        row[f] = ocr.parse_int(ocr.ocr_region(png2, mfields[f], digits=True))
            except Exception:
                pass
            if row.get("name"):
                seen[row["name"]] = row
            for _ in range(back_n):
                driver.keyevent(4)
                time.sleep(0.6)
        scroll = cfg.get("scroll")
        if scroll:
            driver.swipe(*[int(v) for v in scroll[:4]],
                         ms=int(scroll[4]) if len(scroll) > 4 else 600)
            time.sleep(0.8)

    try:
        adapter.run_macro("close_rankings", {})
    except Exception:
        driver.keyevent(4)
    rows = list(seen.values())
    return ActionResult(True, f"deep-scanned {len(rows)} profiles", {"rows": rows})
