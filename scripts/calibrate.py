"""Interactive calibration helper for the ADB UI profile.

Pulls a screenshot from the connected device and lets you record tap
coordinates by clicking on the game UI, then prints anchor JSON you can paste
into your profile. Requires the adb backend + a connected device.

Usage:
    python -m scripts.calibrate screenshot          # save current screen to captures/
    python -m scripts.calibrate tap <x> <y>         # send a test tap
    python -m scripts.calibrate devices             # list adb devices
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import config  # noqa: E402
from app.control.adb_adapter import AdbDriver  # noqa: E402


def main(argv: list[str]) -> int:
    driver = AdbDriver(config.ADB_PATH, config.ADB_SERIAL)
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "devices":
        driver.connect()
        print("devices:", driver.devices())
    elif cmd == "screenshot":
        png = driver.screencap()
        out = config.CAPTURE_DIR / "calibrate.png"
        out.write_bytes(png)
        print(f"saved {out} ({len(png)} bytes). Open it and read pixel coords.")
    elif cmd == "tap" and len(argv) == 3:
        driver.tap(int(argv[1]), int(argv[2]))
        print(f"tapped ({argv[1]}, {argv[2]})")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
