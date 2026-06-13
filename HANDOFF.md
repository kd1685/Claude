# Ascent Terminal — Project Handoff (current as of 2026-06-12, launch build)

Paste this into a new Claude conversation whenever you want to continue work.

---

## What this project is

Ascent Terminal is a **self-hosted, subscription-gated trading-bot dashboard**.
Users register, pay via Stripe, and get access to a web UI that runs two live
bots (MEXC futures scalper + daily trend-follower) and shows real-time P&L,
trade history, and risk controls.  The owner has a private `/admin` panel.

Stack: Python 3.11 · FastAPI · Jinja2 · SQLite (via SQLAlchemy) · Stripe ·
WebSockets · Docker Compose · Nginx · Let's Encrypt.

---

## Folder layout (top of repo)

```
ascent_terminal/
├── platform/          ← FastAPI app (routes, models, templates, static)
│   ├── main.py        ← app factory + lifespan
│   ├── routes/        ← auth, dashboard, admin, stripe, bots, referral
│   ├── models.py      ← SQLAlchemy ORM (User, Subscription, Trade, …)
│   ├── stripe_client.py
│   ├── alerts.py      ← email / webhook alerting
│   ├── templates/     ← Jinja2 HTML
│   └── static/        ← CSS / JS / icons
├── bots/
│   └── scalper_bot.py ← MEXC futures WebSocket scalper (PyQt5 GUI + headless)
├── brain/             ← owner-only research tools (never deployed)
│   ├── edge_lab.py
│   ├── mexc_trend_bot.py
│   └── swing_backtest.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env               ← secrets (never in repo)
└── keys.json          ← MEXC API keys (never in repo)
```

---

## Current state (what is done)

| Area | Status |
|------|--------|
| FastAPI app skeleton | ✅ done |
| Auth (register / login / JWT cookies) | ✅ done |
| Stripe checkout + webhook handler | ✅ done |
| Subscription gating middleware | ✅ done |
| Dashboard with live WebSocket feed | ✅ done |
| Scalper bot (headless mode for server) | ✅ done |
| Trend bot (daily cron via APScheduler) | ✅ done |
| Admin panel (/admin/health, /admin/users) | ✅ done |
| Referral system | ✅ done |
| Email alerts | ✅ done |
| Docker Compose + Nginx config | ✅ done |
| Stripe products / webhook endpoint | ⏳ do tomorrow (see GO_LIVE_STEPS §3) |
| Point domain + SSL cert | ⏳ whenever ready |

---

## Secrets that must exist on the VPS (never committed)

```
platform/.env
    SECRET_KEY=<random 32-char hex>
    DATABASE_URL=sqlite:///./data/ascent.db
    STRIPE_SECRET_KEY=sk_live_…
    STRIPE_PUBLISHABLE_KEY=pk_live_…
    STRIPE_PRICE_MONTHLY=price_…
    STRIPE_PRICE_YEARLY=price_…
    STRIPE_WEBHOOK_SECRET=whsec_…
    MEXC_API_KEY=…
    MEXC_API_SECRET=…
    ADMIN_EMAIL=you@example.com
    SMTP_HOST=smtp.example.com
    SMTP_USER=you@example.com
    SMTP_PASS=…
    REFERRAL_ENABLED=false
    PAYMENTS_LIVE=false

platform/keys.json   ← {"api_key": "…", "api_secret": "…"}
```

---

## How to continue in a new conversation

1. Paste this file.
2. Say which part you want to work on.
3. Claude will ask for the relevant source files if needed.

Useful prompts:
- "Show me the Stripe webhook handler and help me test it."
- "Add a 7-day free trial to the subscription flow."
- "Write a smoke-test script that hits every route."
- "Help me set up the Nginx + Let's Encrypt config."
