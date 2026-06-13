# HANDOFF — Ascent Terminal

Everything a new operator needs to take over and run this system.

---

## What this is

Ascent Terminal is a subscription trading platform.  Members pay via Stripe (or Whop /
Patreon) to access:

- A browser-based terminal with live market data, order-flow, liquidation heatmaps, AI
  analysis, and forex macro feeds
- A Python scalper bot they can run locally
- Discord alerts channel with auto-posted signals

The backend is a single Python (Flask) process behind Caddy, running in Docker on a
Linux VPS.

---

## Repo layout

```
platform/       Flask app, Docker, Caddy config
  app.py        Main application — routes, auth, data feeds
  billing.py    Stripe checkout + webhook handler
  auth.py       Whop OAuth + API key auth
  key_gen.py    CLI to create/revoke member API keys
  bots.py       Bot config endpoints
  exits.py      Exit-signal logic
  indicators.py TA indicators (RSI, MACD, BB, …)
  exchanges.py  CCXT wrapper (MEXC primary)
  static/       Landing, terminal, download, privacy HTML pages

bots/
  scalper_bot.py  Standalone bot members download + run locally

brain/
  edge_lab.py        Walk-forward parameter optimiser
  mexc_trend_bot.py  Live trend-following bot (server-side)
  swing_*.py         Swing strategy backtests

discord/
  discord_role_sync.py  Sync Whop/Patreon roles → Discord
  discord_post_content.py  Post announcements / signals
  add_alerts_channel.py    One-time channel setup

forward/
  forward_paper.py   Paper-trade forward-test harness

tools/              Windows helper .bat scripts
installer/          Inno Setup script for Windows desktop installer
server_launcher/    Thin wrapper to launch the platform from a shortcut
whop_patreon/       Copy + prompt templates for Whop/Patreon listings
legal/              Terms, Privacy, Disclaimer (Markdown source)
```

---

## Credentials you need

| Secret | Where to find it |
|--------|------------------|
| `SECRET_KEY` | Regenerate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `WHOP_CLIENT_ID` + `WHOP_CLIENT_SECRET` | Whop dashboard → Developer |
| `STRIPE_SECRET_KEY` | Stripe dashboard → API keys |
| `STRIPE_WEBHOOK_SECRET` | Stripe dashboard → Webhooks |
| `DISCORD_WEBHOOK_URL` | Discord channel → Integrations → Webhooks |
| `MEXC_API_KEY` + `MEXC_API_SECRET` | MEXC → API Management |

All go in `platform/.env`.

---

## Day-to-day operations

```bash
# Check everything is up
docker compose ps

# Follow logs
docker compose logs -f

# Deploy an update
git pull && docker compose up -d --build

# Backup member keys
cp platform/keys.json ~/keys_backup_$(date +%Y%m%d).json

# Add a new member key manually
python3 platform/key_gen.py --create --tier operator --note "username"

# Revoke a key
python3 platform/key_gen.py --revoke KEY_VALUE
```

---

## If something breaks

1. `docker compose logs app --tail 50` — check for Python errors
2. `docker compose logs caddy --tail 20` — check for TLS / proxy errors
3. `python3 -m pytest platform/tests/ -v` — run the test suite
4. Check `.env` — a missing or wrong value causes most failures

---

## Contacts / accounts

- Stripe: your Stripe account
- Whop: whop.com/ascentterminal
- Patreon: patreon.com/AscentTerminal
- X: x.com/AscentTerminal
- Support email: support@ascentterminal.com
