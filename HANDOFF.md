# Ascent Terminal — Project Handoff (current as of 2026-06-12, launch build)

Paste this into a new chat as the project brief. Upload the current
`AscentTerminal` zip with it — this file describes the whole system.

---

## What this project is

Ascent Terminal is a subscription SaaS for retail traders:
- **Website** — marketing + auth + Stripe checkout (Flask, hosted on VPS)
- **Desktop app** — Windows tray app that streams live signals (PyQt6)
- **Trading bots** — scalper and swing/trend bots (MEXC exchange, CCXT)
- **Edge lab** — walk-forward backtesting framework to validate signals

Live domain: https://ascentterminal.com  
VPS: Ubuntu 22.04, `/opt/ascent/`  
Python 3.11, venv at `/opt/ascent/venv/`

---

## Folder map

```
AscentTerminal/
├── platform/          # Flask web app
│   ├── app.py         # main Flask app + all routes
│   ├── models.py      # SQLAlchemy models (User, Subscription, Signal)
│   ├── stripe_utils.py
│   ├── email_utils.py
│   ├── templates/     # Jinja2 HTML templates
│   ├── static/        # CSS, JS, images
│   ├── data/          # SQLite DB + uploads (gitignored)
│   └── keys.json      # Stripe + email secrets (gitignored)
├── bots/
│   └── scalper_bot.py # high-frequency scalper (MEXC)
├── brain/
│   ├── edge_lab.py        # walk-forward backtester
│   ├── mexc_trend_bot.py  # swing/trend bot
│   ├── swing_backtest.py  # quick Sharpe screener
│   └── RUN_EDGE_LAB.bat   # Windows launcher for edge lab
├── desktop/
│   └── ascent_desktop.py  # PyQt6 tray app
├── .env               # VPS env vars (gitignored)
├── requirements.txt
└── README_WINDOWS_KIT.md
```

---

## Current state (what was just done)

1. **Scalper bot** fully rewritten — adaptive ATR sizing, fee-aware PnL,
   Redis heartbeat, Prometheus metrics, graceful shutdown.
2. **Edge lab** upgraded — parallel walk-forward, regime filter,
   auto-parameter sweep, CSV + HTML report output.
3. **MEXC trend bot** hardened — Kelly sizing, drawdown circuit-breaker,
   position reconciliation on startup.
4. **Website** — download page wired to real binary, pricing page updated,
   Stripe webhook signature verification fixed.
5. **UPDATE.bat / organise.bat** — deployment helpers for Windows.

---

## What's left before full launch

| # | Task | Who | ETA |
|---|------|-----|-----|
| 1 | Switch Stripe test→live key | Owner | tomorrow |
| 2 | Upload update to VPS (`UPDATE.bat`) | Owner | today |
| 3 | Restart systemd services | Owner | today |
| 4 | Smoke-test website + download | Owner | today |
| 5 | Run edge lab backtest, confirm Sharpe > 1 | Owner | today |

---

## Key env vars (.env on VPS)

```
FLASK_SECRET_KEY=…
STRIPE_SECRET_KEY=sk_live_…   # still sk_test_ until tomorrow
STRIPE_WEBHOOK_SECRET=whsec_…
EMAIL_USER=…
EMAIL_PASS=…
DATABASE_URL=sqlite:///data/ascent.db
REDIS_URL=redis://localhost:6379/0
```

---

## How to continue this project in a new chat

1. Paste this file.
2. Upload the zip (so Claude can read the actual source).
3. Say what you want to do next — the context above is enough to
   pick up without re-explaining the whole project.
