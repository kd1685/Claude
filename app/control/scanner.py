"""OCR rankings scanner for the ADB backend.

Opens the in-game rankings list (Power / Kill Points / Dead), screenshots each
visible page, OCRs the per-row name + value regions defined in the calibration
profile, scrolls, and repeats. Returns de-duplicated rows ready to ingest as a
scan.
"""
from __future__ import annotations

from . import ocr
from .adapter import ActionResult

import re

# Leading alliance tag like "[WW85] Name" or "(WW85) Name".
_TAG_RE = re.compile(r"^\s*[\[\(]\s*([A-Za-z0-9]{2,4})\s*[\]\)]\s*(.+)$")


def _split_alliance(raw: str):
    """Split a rankings name into (alliance_tag, name). RoK shows '[WW85] Name';
    returns (None, name) when there's no recognisable tag."""
    m = _TAG_RE.match(raw or "")
    if m:
        return m.group(1), m.group(2).strip()
    return None, (raw or "").strip()


# Which snapshot column a rankings tab maps onto.
KIND_FIELD = {"power": "power", "killpoints": "kill_points", "dead": "deads"}


def _stop(adapter) -> bool:
    cb = getattr(adapter, "should_stop", None)
    try:
        return bool(cb and cb())
    except Exception:
        return False


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
        if _stop(adapter):
            break
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
        if _stop(adapter):
            break
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


def _close_profile_to_list(adapter, driver, title_region):
    """More Info X -> profile X, verifying via the title (the profile re-appears
    with an animation that can absorb an early tap). Returns when on the list."""
    import time
    a = adapter.profile.anchors
    mi_close = a.get("more_info_close", a.get("close_x", [1113, 44]))
    prof_close = a.get("profile_view_close", a.get("profile_close", mi_close))
    driver.tap(int(mi_close[0]), int(mi_close[1]))
    time.sleep(1.6)
    driver.tap(int(prof_close[0]), int(prof_close[1]))
    time.sleep(1.4)
    for _ in range(3):
        title = ocr.ocr_region(driver.screencap(), title_region).lower()
        if "governor" in title or "more" in title:   # still on a profile
            driver.tap(int(prof_close[0]), int(prof_close[1]))
            time.sleep(1.2)
        else:
            break


def scan_profiles_via_adb(adapter, *, count: int) -> ActionResult:
    """Deep scan the top `count` governors, top-to-bottom, reading the DEAD-troop
    stat block from each one's More Info screen.

    Traversal is driven by ROW POSITION, not by reading the changing numbers:
    each screen we open every visible row in turn (box 1, 2, 3, ... top to
    bottom), and de-duplicate by the GOVERNOR ID read on each profile screen
    (the one identifier that OCRs reliably). Then we scroll down with overlap and
    repeat. Because we always step through every box and dedup by a stable ID:
      * nothing is skipped (every box is opened; overlap re-shows boundary rows),
      * nothing is double-counted (a governor whose ID we've seen is closed
        immediately), and
      * we can't get stuck on one row (we never re-pick the same box in a loop).
    Names come from the large, clean rankings-list font; the controlling
    account's own row is skipped.
    """
    if not ocr.available():
        return ActionResult(False, "OCR not available (install requirements-adb.txt + tesseract)")
    cfg = adapter.profile.data.get("profiles")
    if not cfg or "rows" not in cfg:
        return ActionResult(False, "profile has no 'profiles' deep-scan calibration block (rows)")

    import time
    from ..config import config as _cfg
    own = ocr._norm(_cfg.OWN_GOVERNOR) if _cfg.OWN_GOVERNOR else ""

    driver = adapter.driver
    adapter.run_macro("open_rankings", {"tab_point": adapter.profile.anchors["tab_power"]})

    rows_cfg = cfg["rows"]
    labels = cfg.get("labels", {})
    name_region = cfg.get("name_region")
    id_region = cfg.get("id_region")          # Governor ID on the profile screen
    title_region = cfg.get("title_region", [360, 40, 560, 55])
    scroll = cfg.get("scroll", [640, 540, 640, 250, 1100])

    seen: dict[str, dict] = {}
    seen_keys: set[str] = set()    # governor IDs + names already handled
    guard = 0
    no_new = 0
    while len(seen) < count and guard < count * 8 + 100:
        guard += 1
        if _stop(adapter):
            break
        png = driver.screencap()
        progressed = False

        for rc in rows_cfg:                       # open every visible box, in order
            if len(seen) >= count or _stop(adapter):
                break
            listname = ocr.read_name_region(png, rc["name"]) if rc.get("name") else ""
            alliance, listname = _split_alliance(listname)
            nkey = ocr._norm(listname)
            if not nkey:
                continue                          # blank row position (past list end)
            if nkey in seen_keys:
                continue                          # overlap row we already did — skip cheaply
            if own and own in nkey:
                seen_keys.add(nkey)
                continue                          # our own account

            val = ocr.read_int_region(png, rc["value"]) if rc.get("value") else None
            driver.tap(int(rc["tap"][0]), int(rc["tap"][1]))
            time.sleep(1.4)
            # Profile screen: Governor ID + clean labelled Power / Kill Points.
            ppng = driver.screencap()
            gid = ocr.read_int_region(ppng, id_region) if id_region else None
            gkey = str(gid) if gid else ""
            if gkey and gkey in seen_keys:        # already scanned (caught by ID)
                seen_keys.add(nkey)
                _close_profile_to_list(adapter, driver, title_region)
                png = driver.screencap()
                continue

            row = dict(ocr.read_labeled_values(ppng, labels))
            try:
                adapter.run_macro("open_more_info", {})
                time.sleep(1.0)
            except Exception:
                pass
            mpng = driver.screencap()
            row.update(ocr.read_labeled_values(mpng, labels))   # adds deads etc.
            if gkey:
                row["governor_id"] = gkey
            row["name"] = listname or (ocr.read_name_region(mpng, name_region)
                                       if name_region else "")
            if alliance:
                row["alliance"] = alliance
            if val is not None and not row.get("power"):
                row["power"] = val

            if (row.get("name") or gkey) and len(row) > 1:
                dkey = gkey or row["name"]
                seen[dkey] = row
                seen_keys.update(k for k in (gkey, nkey, ocr._norm(row["name"])) if k)
                progressed = True
            _close_profile_to_list(adapter, driver, title_region)
            png = driver.screencap()              # refresh after returning to the list

        if len(seen) >= count or _stop(adapter):
            break
        # Scroll down (with overlap) to bring the next set of governors into view.
        driver.swipe(*[int(v) for v in scroll[:4]],
                     ms=int(scroll[4]) if len(scroll) > 4 else 1100)
        time.sleep(1.0)
        if progressed:
            no_new = 0
        else:
            no_new += 1
            if no_new >= 2:                        # nothing new across scrolls -> bottom
                break

    try:
        adapter.run_macro("close_rankings", {})
    except Exception:
        driver.keyevent(4)
    rows = list(seen.values())
    return ActionResult(True, f"deep-scanned {len(rows)} governors", {"rows": rows})


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
        if _stop(adapter):
            break
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
