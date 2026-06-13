# Ascent Terminal — Project Handoff (current as of June 2025)

## What this repo is

A personal algorithmic-trading toolkit for MEXC Futures.
It replaces the old ROK-coin bot with three independent scripts
that can run simultaneously or stand-alone.

---

## Folder layout (after organise.bat runs)

```
Claude/
├── organise.bat          ← run this first on a new PC
├── UPDATE.bat            ← git-pull + pip upgrade in one click
├── GO_LIVE_STEPS.md      ← step-by-step checklist
├── HANDOFF.md            ← this file
├── UPDATE_NOTES.md       ← version history / change log
├── WHAT_TO_DO_NOW.txt    ← quick-start cheat-sheet
├── README_WINDOWS_KIT.md ← Windows-specific setup notes
├── LAUNCH_PLAN.txt       ← phased go-live plan
│
├── bots/
│   └── scalper_bot.py    ← 1-min scalper (main income bot)
│
├── brain/
│   ├── mexc_trend_bot.py ← daily trend-follower
│   ├── edge_lab.py       ← research / parameter scanner
│   ├── swing_backtest.py ← swing-trade backtester
│   └── RUN_EDGE_LAB.bat  ← launcher for edge_lab
│
└── platform/             ← created by organise.bat
    ├── .env              ← YOUR secrets (never commit)
    ├── requirements.txt
    ├── run_bot.bat
    ├── bots/             ← copy of bots/
    ├── brain/            ← copy of brain/
    ├── data/             ← trade CSVs (git-ignored)
    └── logs/             ← log files  (git-ignored)
```

---

## The three scripts

### 1. `bots/scalper_bot.py` — 1-minute scalper
* Trades MEXC USDT-M futures on a symbol of your choice (default BTC/USDT)
* Signal: EMA-cross + RSI confirmation
* Has full paper-trade mode (`PAPER_TRADE=true` in .env)
* Sends every signal and fill to Telegram
* Writes a trade log to `platform/data/trades.csv`

### 2. `brain/mexc_trend_bot.py` — daily trend-follower
* Longer time-frame bot (4 h / daily candles)
* Uses ADX + EMA trend filter + ATR-based stops
* Good complement to the scalper — different market regimes
* Same .env credentials, same Telegram channel

### 3. `brain/edge_lab.py` — research tool
* NOT a live bot — scans symbols and parameter combos
* Scores each combo by Sharpe / win-rate / profit-factor
* Outputs a ranked CSV you can inspect before going live
* Run via `brain/RUN_EDGE_LAB.bat` or directly:
  `python brain/edge_lab.py`

---

## Key environment variables (.env)

| Variable | Purpose | Default |
|---|---|---|
| MEXC_API_KEY | MEXC API key | — |
| MEXC_API_SECRET | MEXC API secret | — |
| TELEGRAM_BOT_TOKEN | Telegram bot token | — |
| TELEGRAM_CHAT_ID | Your Telegram chat id | — |
| SYMBOL | Futures symbol | BTC/USDT:USDT |
| POSITION_SIZE_USDT | $ per trade | 20 |
| LEVERAGE | Futures leverage | 5 |
| TP_PCT | Take-profit % | 0.8 |
| SL_PCT | Stop-loss % | 0.4 |
| PAPER_TRADE | true = no real orders | true |

---

## Workflow for a new PC

1. `git clone https://github.com/kd1685/Claude.git`
2. Double-click `organise.bat`
3. Fill in `platform/.env`
4. `pip install -r platform/requirements.txt`
5. Double-click `platform/run_bot.bat`

See `GO_LIVE_STEPS.md` for the full checklist.

---

## Updating

Double-click `UPDATE.bat` — it pulls the latest code and
upgrades pip packages in one step.

---

## Known limitations / TODO

* No web dashboard yet — monitoring is Telegram-only
* edge_lab scans only the last 500 candles (fast but shallow)
* trend_bot position sizing is fixed (no Kelly / volatility scaling)
* No multi-exchange support — MEXC only
