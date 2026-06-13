# Ascent Terminal — Windows kit

What's in this folder and how it fits together:

```
download.html                  → the website's /download page
desktop/ascent_desktop.py      → desktop app source (PyQt6)
UPDATE.bat                     → deploy code updates to VPS
organise.bat                   → sort Downloads folder by type
bots/scalper_bot.py            → scalper bot (run on VPS)
brain/edge_lab.py              → backtester (run locally or on VPS)
brain/mexc_trend_bot.py        → trend/swing bot
brain/swing_backtest.py        → quick Sharpe screener
brain/RUN_EDGE_LAB.bat         → Windows launcher for edge lab
```

## Quick-start (Windows)

1. Install Python 3.11 from python.org (tick "Add to PATH")
2. Open a terminal in this folder:
   ```
   pip install -r requirements.txt
   ```
3. To run the edge lab backtest:
   ```
   brain\RUN_EDGE_LAB.bat
   ```
   Results → `brain/edge_results.csv`

4. To deploy an update to the VPS:
   ```
   UPDATE.bat
   ```
   (Requires rsync — install via Git for Windows or WSL)

## Environment variables

Copy `.env.example` to `.env` and fill in your keys before running
any bot locally. The VPS already has its own `.env`.

## Support

Open an issue or email support@ascentterminal.com
