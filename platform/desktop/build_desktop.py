"""
Build the Ascent Terminal desktop client into a Windows app.

Run on a Windows machine:

    pip install pywebview pyinstaller
    python build_desktop.py

Output:  dist/AscentTerminal/AscentTerminal.exe   (whole folder is the app)

Why --onedir and not --onefile:
  onefile exes self-extract to a temp dir at launch — the single biggest
  trigger of antivirus false positives. onedir starts faster and gets
  flagged far less. The Inno Setup script in ../installer packages the
  folder into a single professional installer for distribution.

Optional icon: place icon.ico next to this script (256px multi-size .ico,
exported from brand/ascent-mark). It is picked up automatically.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "icon.ico")

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",                      # see note above — do not switch to onefile
    "--windowed",                    # no console window
    "--name", "AscentTerminal",
    os.path.join(HERE, "ascent_desktop.py"),
]
if os.path.exists(ICON):
    cmd += ["--icon", ICON]

# Version metadata makes the exe look (and scan) like real software,
# not an anonymous binary. PyInstaller reads it from a version file.
VERSION_FILE = os.path.join(HERE, "version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as f:
    f.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1, 0, 0, 0), prodvers=(1, 0, 0, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Ascent Terminal'),
      StringStruct('FileDescription', 'Ascent Terminal desktop client'),
      StringStruct('FileVersion', '1.0.0.0'),
      StringStruct('InternalName', 'AscentTerminal'),
      StringStruct('LegalCopyright', 'Copyright Ascent Terminal'),
      StringStruct('OriginalFilename', 'AscentTerminal.exe'),
      StringStruct('ProductName', 'Ascent Terminal'),
      StringStruct('ProductVersion', '1.0.0.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")
cmd += ["--version-file", VERSION_FILE]

print("Building:", " ".join(cmd))
result = subprocess.run(cmd, cwd=HERE)
if result.returncode != 0:
    sys.exit("PyInstaller failed — see output above.")

out = os.path.join(HERE, "dist", "AscentTerminal")
print("\nDone.")
print("App folder :", out)
print("Run it     :", os.path.join(out, "AscentTerminal.exe"))
print("\nNext steps:")
print(" 1. Test the exe on this machine.")
print(" 2. (Recommended) sign it:  signtool sign /fd SHA256 /a AscentTerminal.exe")
print(" 3. Build the installer: open ../installer/AscentTerminal.iss in Inno Setup -> Compile.")
