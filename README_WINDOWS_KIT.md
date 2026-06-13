# AscentTerminal — Windows Kit

This folder ships a **local Windows desktop wrapper** for the Ascent Terminal
server. It lets subscribers (or you) run the platform on a Windows PC without
Docker or a browser tab — the app looks and feels native.

---

## What's included

| Path | What it is |
|---|---|
| `platform/desktop/build_desktop.py` | PyInstaller build script — wraps `server_launcher/ascent_server.py` + pywebview into a single folder |
| `server_launcher/ascent_server.py` | Replaces the old `.bat` launchers. Starts the FastAPI server, opens the webview window. Supports `--setup` for first-run env config. |
| `installer/AscentTerminal.iss` | Inno Setup script — turns the PyInstaller output into a proper Windows installer (Start-menu shortcut, uninstaller, version info) |
| `installer/icon.ico` | App icon (export `brand/app-icon-ios-1024.png` → `.ico` using https://convertico.com or Pillow) |

---

## Build steps (do this on a Windows PC, once per release)

### 1 — Prerequisites
```
pip install pywebview pyinstaller
```
You also need **Inno Setup 6** installed: https://jrsoftware.org/isdl.php

### 2 — Build the exe bundle
```
cd platform\desktop
python build_desktop.py
```
Output: `platform\desktop\dist\AscentTerminal\` — a folder of files, not a
single exe. (Single-file exe is ~3× slower to start and more likely to
trigger SmartScreen.)

### 3 — Compile the installer
Open Inno Setup → File → Open → `installer\AscentTerminal.iss`
Press **Compile** (F9). Output: `installer\Output\AscentTerminalSetup.exe`

### 4 — Upload to the server
```
scp installer\Output\AscentTerminalSetup.exe root@<SERVER_IP>:/root/AscentTerminal/platform/static/dl/
scp platform\desktop\dist\AscentTerminal.zip  root@<SERVER_IP>:/root/AscentTerminal/platform/static/dl/
```
(Zip the dist folder first if you want to offer the portable version too.)

### 5 — Update the download page
Get the SHA-256 of the installer:
```
certutil -hashfile installer\Output\AscentTerminalSetup.exe SHA256
```
Paste it into `platform/static/download.html` at the `data-sha256` attribute
on the installer download button, then redeploy.

---

## SmartScreen / antivirus strategy

Unsigned executables from unknown publishers trigger Windows SmartScreen
("Windows protected your PC"). Options, cheapest first:

1. **Do nothing for now** — subscribers click "More info → Run anyway".
   Fine for a small audience who trust you.
2. **Self-sign** (free): creates a certificate that removes the prompt on
   *your own machines* but not others.
3. **EV code-signing certificate** (~£300/yr, DigiCert / Sectigo) — the
   only option that removes SmartScreen for everyone from day one.
4. **Reputation build** (free, takes ~weeks): Microsoft SmartScreen clears
   the warning automatically once enough users have run the file without
   reporting it. Submit via https://www.microsoft.com/en-us/wdsi/filesubmission
   if it gets flagged as malware (it won't, but submit anyway to accelerate).

Recommended path: ship unsigned for beta, get EV cert when revenue justifies
it.

---

## Local dev on your own PC (no build needed)

```
# First time
python server_launcher\ascent_server.py --setup

# Every time after
python server_launcher\ascent_server.py
```

This starts FastAPI on `http://localhost:8000` and opens a browser window.
No Docker, no `.bat` files, no AV flags.

---

## Updating the kit

The `ascent_server.py` launcher reads `.env` from the platform folder — it
picks up any `.env` changes automatically on the next launch. For a new
release: re-run `build_desktop.py`, recompile the Inno Setup script (version
number is in the `.iss` file under `AppVersion`), upload, update the SHA.
