# Ascent Terminal — Handoff Document

## What this project is

Ascent Terminal is a subscription-gated web platform for retail traders.  
Subscribers get access to:

| Feature | Location |
|---|---|
| Live & paper trading dashboard | `platform/` |
| Scalper bot (manual trigger) | `bots/scalper_bot.py` |
| MEXC trend-following bot | `brain/mexc_trend_bot.py` |
| Edge lab (backtest runner) | `brain/edge_lab.py` |
| Swing OOS backtests | `brain/swing_*.py` |
| Forward-test paper runner | `forward/forward_paper.py` |

Access control is enforced by **JWT tokens** issued after a successful  
Stripe or Patreon webhook confirms an active subscription.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Auth | JWT (python-jose) + bcrypt |
| Payments | Stripe Checkout + webhooks |
| Community | Patreon webhooks + Discord bot |
| Frontend | Vanilla JS / Jinja2 templates |
| Server | Uvicorn behind nginx (systemd) |
| Deployment | rsync from Windows via UPDATE.bat |

---

## Repo layout

```
ascent-terminal/
├── platform/          # FastAPI app (main entry-point: ascent_server.py)
│   ├── ascent_server.py
│   ├── templates/
│   └── static/
├── bots/
│   └── scalper_bot.py
├── brain/
│   ├── edge_lab.py
│   ├── mexc_trend_bot.py
│   └── swing_*.py
├── discord/
│   ├── discord_role_sync.py
│   └── discord_post_content.py
├── forward/
│   ├── forward_paper.py
│   └── ascent-forward.service
├── installer/
│   └── AscentTerminal.iss
├── legal/
│   ├── TERMS.md
│   ├── PRIVACY.md
│   └── DISCLAIMER.md
├── tools/
│   └── *.bat
├── whop_patreon/
│   └── *.md
├── .env.example
├── UPDATE.bat
└── GO_LIVE_STEPS.md
```

---

## Environment variables (`.env`)

```
# Server
SECRET_KEY=<random 64-char hex>
ALLOWED_HOSTS=ascentterminal.com,www.ascentterminal.com

# Stripe
STRIPE_SECRET_KEY=sk_live_…
STRIPE_PUBLISHABLE_KEY=pk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_ID=price_…

# Patreon (optional)
PATREON_WEBHOOK_SECRET=…
PATREON_CAMPAIGN_ID=…

# Discord
DISCORD_BOT_TOKEN=…
DISCORD_GUILD_ID=…
DISCORD_SUBSCRIBER_ROLE_ID=…
DISCORD_WEBHOOK_URL=…

# MEXC (for bots)
MEXC_API_KEY=…
MEXC_SECRET_KEY=…
```

---

## Running locally

```bash
pip install -r requirements.txt
uvicorn server_launcher.ascent_server:app --reload --port 8000
```

Then open http://localhost:8000.

---

## Deploying to the VPS

Run `UPDATE.bat` from Windows. It will:
1. rsync everything except `.env`, `keys.json`, `data/`
2. SSH in and restart `ascent-terminal.service`

---

## Tests

```
tools/RUN_TESTS.bat
```

Runs pytest with coverage. All tests live in `tests/`.

---

## Key design decisions

* **No ORM** — plain SQLite via `aiosqlite` keeps the footprint tiny.
* **Single-process** — Uvicorn workers share in-process state; fine for  
  the current traffic level. Move to Redis if you scale horizontally.
* **Stripe as source of truth** — subscription status is written to the  
  local DB only on webhook receipt, never polled.
