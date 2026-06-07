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

    Robust traversal: we DON'T rely on reading the little rank numbers (the medal
    circles for 1-3 barely OCR). Instead we de-duplicate each visible row by its
    POWER VALUE — big clean white digits that OCR reliably — and always scroll
    with overlap. That makes skips and double-scans structurally impossible: even
    if a scroll overshoots or the list snaps back, a row we've already done is
    recognised by its value and skipped. Names are read from the large, clean
    rankings-list font (far more accurate than the small More Info name). The
    controlling account's own row is skipped.
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

    def read_rows(png):
        """[(key, rowcfg, value), ...] for visible rows, top to bottom. `key`
        de-dups a row across overlapping scrolls: the power value when readable
        (most reliable), else the normalised name."""
        out = []
        for rc in rows_cfg:
            val = ocr.read_int_region(png, rc["value"]) if rc.get("value") else None
            key = str(val) if val is not None else ""
            if not key and rc.get("name"):
                nm = ocr.ocr_region(png, rc["name"]).strip().splitlines()
                key = ocr._norm(nm[0]) if nm else ""
            if key:
                out.append((key, rc, val))
        return out

    seen: dict[str, dict] = {}
    scanned: set[str] = set()      # row keys already handled
    guard = 0
    stagnant = 0
    while len(seen) < count and guard < count * 6 + 80:
        guard += 1
        if _stop(adapter):
            break
        png = driver.screencap()
        rows = read_rows(png)

        # Topmost visible row we haven't handled yet.
        target = next((t for t in rows if t[0] not in scanned), None)
        if target is None:
            # Everything on screen is already scanned — scroll for more.
            driver.swipe(*[int(v) for v in scroll[:4]],
                         ms=int(scroll[4]) if len(scroll) > 4 else 1100)
            time.sleep(1.0)
            after = read_rows(driver.screencap())
            if after and all(k in scanned for k, _, _ in after):
                stagnant += 1
                if stagnant >= 3:        # list isn't advancing -> bottom reached
                    break
            else:
                stagnant = 0
            continue

        stagnant = 0
        key, rc, val = target
        scanned.add(key)

        listname = ocr.read_name_region(png, rc["name"]) if rc.get("name") else ""
        alliance, listname = _split_alliance(listname)
        if own and listname and own in ocr._norm(listname):
            continue                      # skip our own account

        driver.tap(int(rc["tap"][0]), int(rc["tap"][1]))
        time.sleep(1.4)
        # The profile screen (before More Info) has the Governor ID plus clean,
        # labelled Power / Kill Points. Read those here, then let More Info add
        # the dead troops + resource stats (merged on top).
        ppng = driver.screencap()
        row = dict(ocr.read_labeled_values(ppng, labels))
        if id_region:
            gid = ocr.read_int_region(ppng, id_region)
            if gid:
                row["governor_id"] = str(gid)
        try:
            adapter.run_macro("open_more_info", {})
            time.sleep(1.0)
        except Exception:
            pass
        mpng = driver.screencap()
        row.update(ocr.read_labeled_values(mpng, labels))
        # Prefer the large, clean rankings-list name; fall back to More Info.
        row["name"] = listname or (ocr.read_name_region(mpng, name_region) if name_region else "")
        if alliance:
            row["alliance"] = alliance
        if val is not None and not row.get("power"):
            row["power"] = val
        if (row.get("name") or row.get("governor_id")) and len(row) > 1:
            dkey = row.get("governor_id") or row["name"]
            seen[dkey] = row
        _close_profile_to_list(adapter, driver, title_region)

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
