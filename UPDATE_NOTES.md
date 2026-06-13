# UPDATE NOTES — Ascent Terminal

All notable changes to this project will be documented here.

Format: `[VERSION] YYYY-MM-DD — Summary`

---

## [1.0.0] 2025-06-01 — Initial release

### Added
- `bots/scalper_bot.py` — PyQt5 GUI trading bot for MEXC Futures
  - Live orderbook, trade tape, and P&L panel
  - Configurable lot size, leverage, and take-profit / stop-loss
  - One-click start / pause / emergency-stop
  - Discord alert on every filled order
  - Licence-key validation against Ascent server on startup

- `brain/edge_lab.py` — multi-strategy back-test harness
  - Supports RSI-mean-reversion, breakout, and VWAP strategies
  - Outputs equity curve PNG and CSV trade log
  - Walk-forward validation with configurable IS/OOS split

- `brain/mexc_trend_bot.py` — trend-following strategy
  - EMA crossover + ATR-based position sizing
  - Live runner mode (paper and live)
  - Sharpe, max-DD, and win-rate reporting

- `brain/swing_backtest.py` — swing strategy back-test
- `brain/swing_oos.py` — out-of-sample validation
- `brain/swing_oos_wide.py` — wider-parameter OOS sweep
- `brain/swing_voltarget.py` — volatility-targeting position-sizing overlay

- `server_launcher/ascent_server.py` — Flask web server
  - `/api/health` — liveness probe
  - `/api/validate` — licence-key validation
  - `/webhook/stripe` — Stripe payment webhook
  - `/subscribe` — Stripe Checkout redirect
  - Static file serving for landing page

- `discord/` — Discord integration suite
  - `discord_role_sync.py` — syncs Stripe subscriber status to Discord roles
  - `discord_post_content.py` — scheduled content poster
  - `add_alerts_channel.py` — one-time channel/role setup

- `forward/` — paper-trade forward-test harness
  - `forward_paper.py` — runs strategy in paper-trade mode
  - `forward_state.json` — persists open positions across restarts

- `installer/AscentTerminal.iss` — Inno Setup script for Windows installer

- `legal/` — legal documents
  - `DISCLAIMER.md`
  - `PRIVACY.md`
  - `TERMS.md`

- `tools/` — developer utilities
  - `DEPLOY_TO_VPS.bat`
  - `GENERATE_SECRETS.bat`
  - `NEW_KEY.bat`
  - `REVOKE_KEY.bat`
  - `RUN_TESTS.bat`
  - `TEST_DISCORD_WEBHOOK.bat`

- `whop_patreon/` — marketplace listing copy
  - `REBRAND_COPY.md`
  - `patreon_setup_prompts.md`
  - `whop_ai_prompts.md`

- Documentation
  - `GO_LIVE_STEPS.md` — complete VPS deployment guide
  - `HANDOFF.md` — architecture overview for new developers
  - `LAUNCH_PLAN.txt` — marketing and monetisation plan
  - `README_WINDOWS_KIT.md` — Windows quick-start guide
  - `WHAT_TO_DO_NOW.txt` — prioritised next-actions
  - `UPDATE_NOTES.md` — this file

---

## [1.0.1] — Planned

### To-do before tagging
- [ ] Code-sign Windows installer
- [ ] Add pytest suite for Flask routes
- [ ] Make symbol list in `mexc_trend_bot.py` config-driven
- [ ] Wire up Patreon webhook for real-time tier changes
- [ ] Rate-limit `/api/validate`
- [ ] Add UptimeRobot / healthcheck endpoint docs

---

## Versioning policy

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** — breaking change to bot / server API
- **MINOR** — new feature, backwards-compatible
- **PATCH** — bug fix or documentation update

Release tags are pushed to GitHub (`git tag v1.0.0 && git push --tags`).

---

## How to update

**Windows users:** double-click `UPDATE.bat`

**VPS / Linux:**
```bash
cd /opt/ascent
git pull origin main
pip3 install -r requirements.txt
sudo systemctl restart ascent
```
