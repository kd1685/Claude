# Ascent Terminal — Project Handoff (current as of 2026-06-12, launch build)

## What this project is

Ascent Terminal is a self-hosted, single-page crypto trading terminal.
The user opens a browser tab, enters an access key, and gets:

* Live multi-asset chart (TradingView Lightweight Charts)
* A 26-indicator signal panel with configurable weights
* A backtester (EMA30 baseline + custom indicator config)
* Claude AI commentary tab (uses the owner's Anthropic key)
* TradingView alert ingestion via webhook
* Paper + live order execution via CCXT bridge
* Server-watched TP/SL exit plans
* Automated bots (EMA30 trend-follower, MEXC scalper)
* Fear & Greed index, macro/positioning data

The back-end is a single FastAPI app (`platform/main.py`).
The front-end is a single HTML file (`platform/static/index.html`).
All state is in-memory (alerts, orders, bots reset on restart).

---

## Repo layout

```
.env                     secrets (never committed)
.gitignore
requirements.txt         pip deps
platform/
  main.py                FastAPI app — all routes
  static/
    index.html           entire front-end (one file)
bots/
  scalper_bot.py         standalone MEXC scalper (run separately)
brain/
  edge_lab.py            signal-research / walk-forward tool
  mexc_trend_bot.py      EMA30 trend-bot for MEXC futures
  swing_backtest.py      simple daily-bar backtest helper
  RUN_EDGE_LAB.bat       Windows launcher for edge_lab
```

---

## How to run

1. Copy `.env.example` → `.env`, fill in `ACCESS_KEY` and `ANTHROPIC_API_KEY`.
2. `pip install -r requirements.txt`
3. `uvicorn platform.main:app --reload`
4. Open `http://localhost:8000`, enter your key.

Full checklist: see `GO_LIVE_STEPS.md`.

---

## Key design decisions

| Decision | Reason |
|---|---|
| Single HTML file | Zero build step; edit and reload |
| In-memory state | No DB dependency; simple to host |
| CCXT for execution | Supports 100+ exchanges; non-custodial |
| EMA30 daily as the edge | Independently backtested; receipts on PROOF tab |
| Claude for AI tab | Owner supplies key; responses cached 15 min |

---

## What's working (launch build)

- [x] Asset picker: crypto spot + perps, forex, stocks, indices, metals
- [x] Chart: candles + EMA overlays + TP/SL lines from alerts
- [x] Signals: 26 indicators, configurable weights, composite score
- [x] Strategy Lab backtester with equity curve chart
- [x] AI tab: Claude analysis, settings panel, 15-min cache
- [x] Alerts: TradingView webhook ingestion, real-time push to UI
- [x] Execution: paper + live orders via CCXT
- [x] TP/SL watcher: server-side polling every ~10 s
- [x] Bots: EMA30 trend bot + MEXC scalper, both in the UI
- [x] Fear & Greed + macro/positioning cards
- [x] Indicator settings drawer with presets
- [x] Watchlist / favourites (localStorage)
- [x] Mobile-responsive layout
- [x] Lock screen with TOS checkbox

---

## Known limitations / next steps

- State is in-memory → alerts, orders, bots reset on server restart.
  *Next: SQLite persistence layer.*
- TP/SL watcher is server-polled, not exchange-native.
  *Next: native exchange conditional orders via CCXT.*
- Single-worker server; bots run in background threads.
  *Next: Celery or asyncio task queue for robustness.*
- No multi-user support (one ACCESS_KEY, one EXECUTE_KEY).
  *Next: per-user keys + JWT.*

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ACCESS_KEY` | yes | gates the UI |
| `ANTHROPIC_API_KEY` | yes | Claude AI tab |
| `EXECUTE_KEY` | no | gates /api/execute |
| `AUTO_EXECUTE` | no | auto-fire BUY/SELL alerts |
| `DEFAULT_EXCHANGE` | no | ccxt id, default mexc |
| `USER_CAP_USD` | no | per-order $ cap |
| `MEXC_API_KEY` | no | MEXC market-data override |
| `MEXC_API_SECRET` | no | MEXC market-data override |

---

## Updating

Windows: run `UPDATE.bat`
Linux: `git pull && pip install -r requirements.txt -q && sudo systemctl restart ascent`
