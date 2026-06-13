# HANDOFF — Ascent Terminal
_Last updated: 2026-06-13_

Everything a new operator (or Claude session) needs to continue from here.

---

## Repositories

| Repo | Purpose | Default branch |
|------|---------|----------------|
| `kd1685/Claude` | Full platform codebase | `claude/compassionate-curie-u20xvy` |
| `mrpacstar-ux/1685` | Public website | `main` |

---

## Current state

### `kd1685/Claude` — platform ✅
Branch `claude/compassionate-curie-u20xvy` is ready to deploy.
Old ROK 1685 bot has been fully removed and replaced with AscentTerminal.

```
platform/        Flask app
  app.py         Routes, SSE live data, auth gate
  billing.py     Stripe subscription lifecycle
  auth.py        Whop OAuth + API key auth
  key_gen.py     CLI: create/revoke member keys
  bots.py        Bot config endpoints
  exits.py       Exit-signal logic
  indicators.py  RSI, MACD, BB, ATR, VWAP
  exchanges.py   CCXT wrapper (MEXC primary)
  ai_analyst.py  Claude AI market commentary
  static/        landing.html, index.html, download.html, legal/, brand/
  .env.example   All required env vars documented
  Dockerfile     Production image
  docker-compose.yml
  Caddyfile      Reverse proxy + auto-TLS

bots/            scalper_bot.py (give to members)
brain/           edge_lab, mexc_trend_bot, swing backtests
discord/         role sync, content posting, alerts setup
forward/         paper trading harness
installer/       AscentTerminal.iss (Inno Setup — Windows installer)
legal/           DISCLAIMER.md, PRIVACY.md, TERMS.md (Markdown source)
server_launcher/ ascent_server.py
tools/           Windows .bat helper scripts
whop_patreon/    Listing copy + AI prompts
GO_LIVE_STEPS.md Step-by-step deploy guide
LAUNCH_PLAN.txt  Phased go-to-market plan
WHAT_TO_DO_NOW.txt Shortest path to first paying member
```

### `mrpacstar-ux/1685` — website ✅ LIVE on main
All pages updated and pushed. All 5 Stripe payment links are live (no test links).

| Page | Status |
|------|--------|
| index.html | ✅ Live Stripe links, contact@ascentterminal.com |
| download.html | ✅ |
| terminal.html | ✅ |
| privacy.html | ✅ contact@ascentterminal.com |
| logo/ | ✅ 7 PNG brand assets |

**Live Stripe payment links (all confirmed via Stripe API):**
| Product | URL |
|---------|-----|
| Observer $15/mo | https://buy.stripe.com/00w6oIdR5fDagwsa7N2oE05 |
| Operator $39/mo | https://buy.stripe.com/00w28seV94Ywa845Rx2oE06 |
| Architect $89/mo | https://buy.stripe.com/bJebJ214j8aIbc8a7N2oE07 |
| +2 Bot Slots $9/mo | https://buy.stripe.com/28E9AU28n3Us7ZWgwb2oE04 |
| +50 AI/day $9/mo | https://buy.stripe.com/aFaaEYeV9ez6gwsgwb2oE00 |

---

## What's still outstanding

| Task | Priority |
|------|----------|
| Deploy platform to VPS (follow `GO_LIVE_STEPS.md`) | 🔴 High |
| Merge `claude/compassionate-curie-u20xvy` → `main` on `kd1685/Claude` | 🔴 High |
| Host installer files at `ascentterminal.com/dl/AscentTerminal-Setup-1.0.0.exe` and `ascentterminal.com/dl/AscentTerminal-1.0.0-portable.zip` | 🟡 Before promoting download page |
| Fill in `platform/.env` on server (copy from `.env.example`) | 🔴 Required for deploy |
| Set up Stripe webhook in Stripe dashboard → `https://ascentterminal.com/billing/webhook` | 🔴 Required for billing |
| Connect Whop OAuth (redirect URI: `https://ascentterminal.com/auth/whop/callback`) | 🔴 Required for member auth |
| Create Discord alerts channel: `python3 discord/add_alerts_channel.py` | 🟡 Before launch |
| Publish Whop listing (copy in `whop_patreon/REBRAND_COPY.md`) | 🟡 Before launch |
| Set up Patreon → Discord role sync (see `discord/PATREON_DISCORD_SETUP.md`) | 🟢 Nice to have |
| Build Windows installer: open `installer/AscentTerminal.iss` in Inno Setup | 🟢 Nice to have |

---

## Credentials needed for .env

| Variable | Where to get it |
|----------|----------------|
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `WHOP_CLIENT_ID` + `WHOP_CLIENT_SECRET` | Whop dashboard → Developer |
| `STRIPE_SECRET_KEY` | Stripe dashboard → API keys (live) |
| `STRIPE_WEBHOOK_SECRET` | Stripe dashboard → Webhooks (after creating endpoint) |
| `DISCORD_WEBHOOK_URL` | Discord → channel → Integrations → Webhooks |
| `MEXC_API_KEY` + `MEXC_API_SECRET` | MEXC → API Management |

---

## Deploy command (once .env is filled)

```bash
cd /root/AscentTerminal/platform
docker compose up -d
```

Full step-by-step: `GO_LIVE_STEPS.md`

---

## Contacts / accounts

| Platform | Handle/URL |
|----------|-----------|
| X | x.com/AscentTerminal |
| Patreon | patreon.com/AscentTerminal |
| Whop | whop.com/ascentterminal |
| Support | support@ascentterminal.com |
| Sales | sales@ascentterminal.com |
| Contact | contact@ascentterminal.com |
