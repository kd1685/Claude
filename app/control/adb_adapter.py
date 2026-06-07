"""Real backend: drive a live Rise of Kingdoms client over ADB.

Works against any Android device or emulator reachable by `adb` — including a
headless emulator on a VPS (e.g. redroid in Docker, reached with
`adb connect host:port`). All UI coordinates come from the calibration profile,
so adapting to a new resolution means editing JSON, not code.
"""
from __future__ import annotations

import logging
import subprocess
import time

from ..config import config
from . import ocr
from .adapter import AccountAdapter, ActionResult
from .profile import UIProfile, render

_log = logging.getLogger(__name__)


class AdbError(RuntimeError):
    pass


class AdbDriver:
    """Thin wrapper over the adb CLI for one device."""

    def __init__(self, adb: str, serial: str):
        self.adb = adb
        self.serial = serial

    def _base(self) -> list[str]:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def raw(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run([self.adb, *args], capture_output=True, timeout=timeout)

    def shell(self, *args: str, timeout: int = 30) -> str:
        p = subprocess.run(self._base() + ["shell", *args],
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise AdbError(f"adb shell {' '.join(args)} failed: {p.stderr.strip()}")
        return p.stdout

    def connect(self) -> None:
        if config.ADB_CONNECT:
            self.raw("connect", config.ADB_CONNECT, timeout=20)
        # Block until the device is actually online.
        self.raw("-s", self.serial, "wait-for-device", timeout=30) if self.serial \
            else self.raw("wait-for-device", timeout=30)

    def devices(self) -> list[str]:
        out = self.raw("devices").stdout.decode("utf-8", "ignore")
        return [ln.split("\t")[0] for ln in out.splitlines()[1:]
                if "\tdevice" in ln]

    def screencap(self) -> bytes:
        p = subprocess.run(self._base() + ["exec-out", "screencap", "-p"],
                           capture_output=True, timeout=30)
        if p.returncode != 0 or not p.stdout:
            raise AdbError(f"screencap failed: {p.stderr.decode('utf-8','ignore')}")
        return p.stdout

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))

    def text(self, value: str) -> None:
        # adb input text needs spaces escaped as %s and is picky about symbols.
        safe = value.replace(" ", "%s")
        self.shell("input", "text", safe)

    def keyevent(self, code: int) -> None:
        self.shell("input", "keyevent", str(code))


class AdbAdapter(AccountAdapter):
    name = "adb"

    def __init__(self):
        self.driver = AdbDriver(config.ADB_PATH, config.ADB_SERIAL)
        self.profile = UIProfile.load(config.UI_PROFILE)
        self._connected = False
        # The agent sets this to a callable returning True when the server has
        # asked the running scan to stop. Scanner loops check it between items.
        self.should_stop = None

    # ---- lifecycle -----------------------------------------------------
    def connect(self) -> ActionResult:
        try:
            self.driver.connect()
            online = self.driver.devices()
            self._connected = bool(online)
            if not self._connected:
                return ActionResult(False, "no device online (check ADB_SERIAL / emulator)")
            return ActionResult(True, f"connected to {online}", {"devices": online})
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, f"adb connect failed: {exc}")

    def status(self) -> dict:
        try:
            devs = self.driver.devices()
        except Exception:
            _log.warning("failed to list ADB devices for status check", exc_info=True)
            devs = []
        return {
            "backend": "adb",
            "connected": bool(devs),
            "device": config.ADB_SERIAL or (devs[0] if devs else None),
            "devices": devs,
            "ocr_available": ocr.available(),
            "profile": self.profile.data.get("name"),
        }

    # ---- macro engine --------------------------------------------------
    def run_macro(self, name: str, ctx: dict | None = None) -> dict:
        ctx = dict(ctx or {})
        for step in self.profile.macro(name):
            self._exec_step(step, ctx)
        return ctx

    def _exec_step(self, step: dict, ctx: dict) -> None:
        d = self.driver
        if "tap" in step:
            x, y = self.profile.point(step["tap"])
            d.tap(x, y)
        elif "tap_var" in step:
            pt = ctx[step["tap_var"]]
            d.tap(int(pt[0]), int(pt[1]))
        elif "swipe" in step:
            s = step["swipe"]
            s = self.profile.anchors[s] if isinstance(s, str) else s
            d.swipe(*[int(v) for v in s[:4]], ms=int(s[4]) if len(s) > 4 else 400)
        elif "text" in step:
            d.text(render(step["text"], ctx))
        elif "key" in step:
            d.keyevent(int(step["key"]))
        elif "back" in step:
            d.keyevent(4)
        elif "wait" in step:
            time.sleep(int(step["wait"]) / 1000)
        elif "ocr" in step:
            self._exec_ocr(step["ocr"], ctx)

    def _exec_ocr(self, spec: dict, ctx: dict) -> None:
        import re
        png = self.driver.screencap()
        text = ocr.ocr_region(png, spec.get("region"), digits=spec.get("digits", False))
        into = spec.get("into", "ocr")
        ctx[into] = text.strip()
        pattern = spec.get("pattern")
        if pattern:
            m = re.search(pattern, text)
            if m:
                for key, gi in spec.get("groups", {}).items():
                    try:
                        ctx[key] = int(m.group(gi))
                    except (ValueError, IndexError):
                        ctx[key] = m.group(gi)

    # ---- high-level actions -------------------------------------------
    def give_title(self, *, name, governor_id, x, y, title) -> ActionResult:
        if not self._connected:
            self.connect()
        title_anchor = f"title_{title.lower()}"
        if title_anchor not in self.profile.anchors:
            return ActionResult(False, f"no anchor '{title_anchor}' in profile")
        ctx = {"name": name, "x": x, "y": y,
               "title_point": self.profile.anchors[title_anchor]}
        try:
            # locate_player centres the map on the governor's city; give_title
            # opens the city panel, the title list and taps the chosen title.
            self.run_macro("locate_player", ctx)
            self.run_macro("give_title", ctx)
            return ActionResult(True, f"granted '{title}' to {name}", {"title": title})
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, f"give_title failed: {exc}")

    def change_rank(self, *, name, governor_id, new_rank) -> ActionResult:
        if not self._connected:
            self.connect()
        rank_anchor = f"rank_r{new_rank}"
        if rank_anchor not in self.profile.anchors:
            return ActionResult(False, f"no anchor '{rank_anchor}' in profile")
        ctx = {"name": name, "rank_point": self.profile.anchors[rank_anchor]}
        try:
            self.run_macro("change_rank", ctx)
            return ActionResult(True, f"set {name} to R{new_rank}", {"new_rank": new_rank})
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, f"change_rank failed: {exc}")

    def locate(self, *, name, governor_id) -> ActionResult:
        # RoK has no jump-to-governor search, so we scan the map for the name.
        if not self._connected:
            self.connect()
        from .scanner import find_on_map_via_adb
        return find_on_map_via_adb(self, name=name)

    def scan_rankings(self, *, kind, pages) -> ActionResult:
        if not self._connected:
            self.connect()
        from .scanner import scan_rankings_via_adb
        return scan_rankings_via_adb(self, kind=kind, pages=pages)

    def scan_rallies(self, *, pages) -> ActionResult:
        if not self._connected:
            self.connect()
        from .scanner import scan_rallies_via_adb
        return scan_rallies_via_adb(self, pages=pages)

    def scan_profiles(self, *, count) -> ActionResult:
        if not self._connected:
            self.connect()
        from .scanner import scan_profiles_via_adb
        return scan_profiles_via_adb(self, count=count)
