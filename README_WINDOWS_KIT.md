# Ascent Terminal — Windows kit

What's in this folder and how it fits together:

```
download.html                  → the website's /download page
desktop/ascent_desktop.py      → desktop app source (wraps ascentterminal.com)
desktop/build_desktop.py       → builds it into AscentTerminal.exe (run on Windows)
server_launcher/ascent_server.py → replaces run_local.bat (owner tool, pure Python)
installer/AscentTerminal.iss   → Inno Setup script → professional installer .exe
```

## A. Replace your batch files (your own PC) — 2 minutes

The AV flags come from `run_local.bat` / `UPDATE.bat`. Stop using them:

```
cd AscentTerminal
python server_launcher\ascent_server.py --setup     # first time (installs deps)
python server_launcher\ascent_server.py             # every time after
```

Plain `.py` files run through the official Python interpreter and don't
trip antivirus heuristics at all. You can delete the .bat files once this
works. (UPDATE.bat's migration job is one-time and already done for you.)

## B. Build the subscriber desktop app — 15 minutes, on Windows

```
pip install pywebview pyinstaller
cd desktop
python build_desktop.py
```

Test `desktop\dist\AscentTerminal\AscentTerminal.exe`. It opens
https://ascentterminal.com in a native window (set ASCENT_URL=http://localhost:8000
to test against a local server).

Then build the installer:
1. Install Inno Setup (free): https://jrsoftware.org/isinfo.php
2. Open installer\AscentTerminal.iss → Compile
3. Output: installer\installer_output\AscentTerminal-Setup-1.0.0.exe

For the portable zip: just zip the desktop\dist\AscentTerminal folder as
AscentTerminal-1.0.0-portable.zip.

## C. Publish on the website

1. On the VPS: `mkdir -p platform/static/dl`
2. Upload both release files into it (same scp pattern as DEPLOY.md).
3. Add download.html to platform/static/ and serve it at /download
   (route added when the code zip is uploaded to Claude — or temporarily
   link to /static/download.html).
4. Get the real checksum and paste it into download.html:
   `certutil -hashfile AscentTerminal-Setup-1.0.0.exe SHA256`

## D. Antivirus / SmartScreen strategy (honest version)

Unsigned new binaries from unknown publishers ALWAYS start with low
reputation. This kit already does everything free that helps:

- onedir build (not onefile) — the single biggest false-positive cause removed
- real version metadata embedded in the exe (company, product, version)
- a proper Inno Setup installer with uninstall entry — scans better than bare exes
- SHA-256 checksums published on the download page
- user guidance for the SmartScreen prompt on the download page

Two more steps as the product earns money:

1. SUBMIT THE BUILD TO MICROSOFT (free, do this once per release):
   https://www.microsoft.com/en-us/wdsi/filesubmission
   → "Software developer" → upload the Setup exe. Defender false
   positives are usually cleared within a couple of days.

2. CODE SIGNING CERTIFICATE (the real fix, do when revenue justifies it):
   An OV code-signing cert (Certum is the cheapest reputable option for
   individuals, ~£60–80/yr) lets you sign both the app and the installer:
     signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a AscentTerminal-Setup-1.0.0.exe
   Signed + a few hundred clean downloads = the SmartScreen prompt
   disappears entirely. Note: "100% never flagged from day one" requires
   an EV cert (~£250+/yr) — reasonable later, unnecessary now.

## E. Versioning releases

Bump the version in THREE places when you release an update:
- desktop/build_desktop.py (version_info block)
- installer/AscentTerminal.iss (#define AppVersion)
- download.html (file names, meta line, checksum)
