# Windows Kit — AscentTerminal Desktop App

This guide covers building the optional Windows desktop app and installer.
The app is a lightweight wrapper around the web terminal — it opens a native
window showing `http://localhost:8000` (or a remote URL) using pywebview.

---

## Prerequisites (on your Windows PC)

```
pip install pywebview pyinstaller
```

Also install **Inno Setup 6** (free): https://jrsoftware.org/isdl.php

---

## Build steps

### 1. Build the exe

```
cd platform\desktop
python build_desktop.py
```

This runs PyInstaller and creates `dist\AscentTerminal\` (a folder, not a
single file — `--onedir` avoids false-positive AV flags that `--onefile` often
triggers).

### 2. Compile the installer

Open Inno Setup → File → Open → `installer\AscentTerminal.iss` → Compile.

This creates `installer\Output\AscentTerminalSetup.exe`.

### 3. Get the SHA-256

```
certutil -hashfile installer\Output\AscentTerminalSetup.exe SHA256
```

Paste the hash into `platform\static\download.html` where marked.

### 4. Upload to the server

```
scp installer\Output\AscentTerminalSetup.exe root@<SERVER_IP>:/root/AscentTerminal/platform/static/dl/
scp platform\desktop\dist\AscentTerminal.zip  root@<SERVER_IP>:/root/AscentTerminal/platform/static/dl/
```

(Create the `dl/` folder first if it doesn't exist: `mkdir -p /root/AscentTerminal/platform/static/dl/`)

---

## SmartScreen / code-signing

Windows SmartScreen will warn on unsigned executables until they accumulate
enough "reputation". Options:

- **Do nothing** — the warning says "Unknown publisher", users click
  *More info → Run anyway*. Fine for early access.
- **Self-sign** (removes the warning for users who import your cert, not
  recommended for distribution).
- **Buy an OV code-signing cert** (~$70–200/yr from Sectigo, DigiCert, etc.)
  — eliminates the SmartScreen warning for everyone immediately.
  Worth it once you have paying subscribers.

For the icon, export `platform/static/brand/app-icon-ios-1024.png` to
`platform/desktop/icon.ico` using an online converter or ImageMagick:
```
convert app-icon-ios-1024.png -resize 256x256 icon.ico
```

---

## Local dev (no batch files, no AV flags)

To run the terminal locally on your Windows PC without building the exe:

```
python server_launcher\ascent_server.py --setup    # first time only
python server_launcher\ascent_server.py            # subsequent runs
```

This installs dependencies, starts the FastAPI server, and opens your browser.
