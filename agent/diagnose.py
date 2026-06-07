#!/usr/bin/env python3
"""Diagnose deep-scan rank reading.

Open the **Individual Power rankings** in LDPlayer, then run:
    python agent\\diagnose.py

It saves the exact frame the agent sees to captures/diagnose.png and prints what
OCR reads for each row's rank + name, so the rank boxes can be fixed precisely.
Send me captures/diagnose.png AND the printed lines.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / "agent" / "agent.env")
os.environ.setdefault("CONTROL_BACKEND", "adb")
os.environ.setdefault("ADB_SERIAL", "127.0.0.1:5555")
os.environ.setdefault("ADB_CONNECT", os.environ.get("ADB_SERIAL", "127.0.0.1:5555"))

from app.config import config            # noqa: E402
from app.control import ocr              # noqa: E402
from app.control.adb_adapter import AdbAdapter  # noqa: E402


def main() -> int:
    if not ocr.available():
        print("Tesseract OCR not available — install it / set TESSERACT_CMD.")
        return 1
    a = AdbAdapter()
    print("connect:", a.connect().detail)
    png = a.driver.screencap()
    out = config.CAPTURE_DIR / "diagnose.png"
    out.write_bytes(png)
    print(f"Saved {out}  ({len(png)} bytes)")

    cfg = a.profile.data.get("profiles", {})
    rows = cfg.get("rows", [])
    print(f"OWN_GOVERNOR={config.OWN_GOVERNOR!r}   rows={len(rows)}")
    print("Reading each row's rank box + name (should be 1,2,3,... top to bottom):")
    for i, r in enumerate(rows):
        rk = ocr.read_int_region(png, r["rank"]) if r.get("rank") else None
        nm = ocr.read_name_region(png, r["name"]) if r.get("name") else ""
        raw = ""
        if r.get("name"):
            rl = ocr.ocr_region(png, r["name"]).strip().splitlines()
            raw = rl[0].strip() if rl else ""
        print(f"  row {i}: rank={rk!s:<5} name={nm!r}  (raw={raw!r}, rank box {r.get('rank')})")
    print("\nOpen captures\\diagnose.png and send it to me with the lines above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
