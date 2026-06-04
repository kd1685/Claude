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
    """Deep scan (Statsmaster-style): tap each governor in the rankings, open
    More Info, and read the full stat block by LABEL (Dead, Resource Assistance,
    …) so it works regardless of exact pixel positions. This is how dead troops
    are captured."""
    if not ocr.available():
        return ActionResult(False, "OCR not available (install requirements-adb.txt + tesseract)")
    cfg = adapter.profile.data.get("profiles")
    if not cfg or "row_taps" not in cfg:
        return ActionResult(False, "profile has no 'profiles' deep-scan calibration block")

    import time
    driver = adapter.driver
    adapter.run_macro("open_rankings", {"tab_point": adapter.profile.anchors["tab_power"]})

    labels = cfg.get("labels", {})
    name_region = cfg.get("name_region")
    back_n = int(cfg.get("back_to_list", 2))
    seen: dict[str, dict] = {}

    for _ in range(pages):
        for tap in cfg["row_taps"]:
            driver.tap(int(tap[0]), int(tap[1]))
            time.sleep(1.4)                       # governor profile opens
            try:
                adapter.run_macro("open_more_info", {})
                time.sleep(1.0)
            except Exception:
                pass
            png = driver.screencap()
            row = dict(ocr.read_labeled_values(png, labels))   # power, kp, deads, rss…
            if name_region:
                nm = ocr.ocr_region(png, name_region).strip().splitlines()
                row["name"] = nm[0].strip() if nm else ""
            if row.get("name") and len(row) > 1:
                seen[row["name"]] = row
            # Close back to the rankings list by tapping the X buttons (back-key
            # is unreliable on these panels): More Info -> profile -> list.
            a = adapter.profile.anchors
            mi_close = a.get("more_info_close", a.get("close_x", [1115, 43]))
            prof_close = a.get("profile_view_close", a.get("profile_close", mi_close))
            driver.tap(int(mi_close[0]), int(mi_close[1]))
            time.sleep(0.8)
            driver.tap(int(prof_close[0]), int(prof_close[1]))
            time.sleep(0.8)
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


def find_on_map_via_adb(adapter, *, name: str, passes: int | None = None) -> ActionResult:
    """Scan the map for one governor by name: pan across the map, watch for the
    nameplate, and when found tap the city to read its coordinates. Best-effort —
    if OCR can't read the nameplate on any pass, it won't be found."""
    if not ocr.available():
        return ActionResult(False, "OCR not available (install requirements-adb.txt + tesseract)")
    cfg = adapter.profile.data.get("map_scan")
    if not cfg:
        return ActionResult(False, "profile has no 'map_scan' calibration block")

    import re
    import time
    driver = adapter.driver
    passes = passes or int(cfg.get("passes", 24))
    pan = cfg.get("pan", [1000, 400, 280, 400, 500])
    coords_region = cfg.get("coords_region")

    if "recenter" in adapter.profile.macros:
        try:
            adapter.run_macro("recenter", {})
        except Exception:
            pass

    for _ in range(passes):
        png = driver.screencap()
        hit = ocr.find_text(png, name)
        if hit:
            driver.tap(hit[0], hit[1])
            time.sleep(1.6)                       # city panel opens
            txt = ocr.ocr_region(driver.screencap(), coords_region) if coords_region else ""
            m = re.search(r"(\d{1,4})\D+(\d{1,4})", txt)
            driver.keyevent(4)                    # close the panel
            if m:
                return ActionResult(True, f"found {name}",
                                    {"kingdom": 1685, "x": int(m.group(1)), "y": int(m.group(2))})
            return ActionResult(True, f"spotted {name} but could not read coords",
                                {"raw": txt})
        driver.swipe(*[int(v) for v in pan[:4]], ms=int(pan[4]) if len(pan) > 4 else 500)
        time.sleep(0.6)

    return ActionResult(False, f"{name} not found after {passes} map passes")
