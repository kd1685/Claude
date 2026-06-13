# Ascent Terminal — Windows kit

What's in this folder and how it fits together:

```
download.html          ← the page users land on to get their Windows kit
UPDATE.bat             ← owner's one-click deploy script (edit 3 vars at top)
organise.bat           ← moves Downloads into dated subfolders (utility)
brain/                 ← owner-only research tools (never deployed to VPS)
  edge_lab.py          ← back-tests indicators across MEXC tickers
  mexc_trend_bot.py    ← live daily trend bot (PyQt5 GUI, run locally)
  edge_lab.py
  RUN_EDGE_LAB.bat      ← double-click to run edge_lab.py
bots/
  scalper_bot.py        ← MEXC futures scalper (PyQt5 GUI)
```

## Quick start

### Run the scalper bot (Windows)
1. Install Python 3.11 from python.org (tick "Add to PATH").
2. Open a terminal in this folder and run:
   ```
   pip install PyQt5 pyqtgraph websocket-client requests
   python bots/scalper_bot.py
   ```
3. Paste your MEXC API key + secret when prompted.

### Run the trend bot / edge lab (Windows)
1. Same Python install as above.
2. Install extra deps:
   ```
   pip install PyQt5 pyqtgraph pandas numpy requests
   ```
3. Double-click `brain/RUN_EDGE_LAB.bat` or run:
   ```
   python brain/mexc_trend_bot.py
   python brain/edge_lab.py
   ```

### Deploy an update to the VPS (owner only)
1. Edit the three variables at the top of `UPDATE.bat`:
   - `VPS_HOST` — your server IP or hostname
   - `VPS_USER` — SSH user (usually `root`)
   - `REMOTE_PATH` — path to the project on the VPS
2. Double-click `UPDATE.bat`.
   It will rsync (WSL) or scp the changed files and restart Docker.

## Notes
- `.env` and `keys.json` are **never** uploaded — they stay on your machine / VPS.
- The `brain/` tools talk directly to MEXC; they do **not** go through the web platform.
- `organise.bat` only touches `%USERPROFILE%\Downloads` — safe to run any time.
