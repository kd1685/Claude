# Ascent Terminal — Windows Kit

This folder contains everything needed to run and manage Ascent Terminal from a
Windows machine.

---

## What's included

```
tools/
  DEPLOY_TO_VPS.bat      Deploy latest code to your VPS
  GENERATE_SECRETS.bat   Generate SECRET_KEY and MEXC keys helper
  NEW_KEY.bat            Issue a new member API key
  REVOKE_KEY.bat         Revoke a member API key
  RUN_TESTS.bat          Run the test suite
  TEST_DISCORD_WEBHOOK.bat  Send a test Discord alert

brain/
  RUN_EDGE_LAB.bat       Run the walk-forward parameter optimiser

bots/
  scalper_bot.py         The scalper bot (give this to members)

installer/
  AscentTerminal.iss     Inno Setup script — build the Windows installer

server_launcher/
  ascent_server.py       Thin wrapper — launches platform in a console window

forward/
  forward_paper.bat      Run paper-trade forward test
  forward_paper.py       Forward test harness
```

---

## Prerequisites

- Python 3.11+ in PATH
- `pip install -r platform/requirements.txt` already run
- SSH key configured for your VPS (for DEPLOY_TO_VPS.bat)
- `.env` file in `platform/` with all secrets filled in

---

## Quick start

1. Clone or unzip this repo
2. `cd platform && pip install -r requirements.txt`
3. `cp .env.example .env` then fill it in
4. Run `tools\\GENERATE_SECRETS.bat` to generate a SECRET_KEY
5. Double-click `tools\\RUN_TESTS.bat` to verify setup
6. Double-click `server_launcher\\ascent_server.py` (or run via Python) to start locally

---

## Building the Windows installer

1. Install [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Open `installer/AscentTerminal.iss` in Inno Setup
3. Build → Output is `AscentTerminal-Setup-x.x.x.exe`
4. Upload to `ascentterminal.com/dl/`
