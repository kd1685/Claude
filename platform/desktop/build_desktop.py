"""build_desktop.py — PyInstaller build script for Ascent Terminal desktop client.

Usage:
    python build_desktop.py

Outputs a standalone executable in dist/AscentTerminal/.
"""

from __future__ import annotations

import subprocess
import sys

SPEC = """
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['ascent_desktop.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['webview', 'webview.platforms.gtk', 'webview.platforms.winforms'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AscentTerminal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AscentTerminal',
)
"""

SPEC_FILE = "AscentTerminal.spec"


def main() -> None:
    with open(SPEC_FILE, "w") as f:
        f.write(SPEC)
    print(f"[build] Wrote {SPEC_FILE}")

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--clean", "--noconfirm"],
        check=False,
    )
    if result.returncode == 0:
        print("[build] Build successful. Output: dist/AscentTerminal/")
    else:
        print("[build] Build FAILED.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
