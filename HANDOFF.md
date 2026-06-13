# HANDOFF — Ascent Terminal

> Document for any developer (or future-you) picking this project up cold.

---

## What is Ascent Terminal?

Ascent Terminal is a **subscription-gated algorithmic-trading toolkit** for MEXC Futures.

It has three layers:

| Layer | What it does |
|-------|--------------|
| **Research / Brain** | Back-tests and walk-forward scripts (`brain/`) that find edges |
| **Live bot** | A PyQt5 desktop app (`bots/scalper_bot.py`) that runs the winning strategy in real time |
| **Platform** | A Flask web server (`server_launcher/ascent_server.py`) that handles auth, Stripe payments, licence keys, and Discord role-sync |

---

## Repository layout

```
.
├── .gitignore
├── GO_LIVE_STEPS.md        ← step-by-step launch guide
├── HANDOFF.md              ← this file
├── LAUNCH_PLAN.txt         ← marketing / monetisation plan
├── README_WINDOWS_KIT.md   ← how to run everything on Windows
├── UPDATE.bat              ← one-click update script (Windows)
├── UPDATE_NOTES.md         ← changelog / release notes
├── WHAT_TO_DO_NOW.txt      ← prioritised next-actions list
├── organise.bat            ← repo housekeeping script
│
├── bots/
│   └── scalper_bot.py      ← main live-trading GUI bot
│
├── brain/
│   ├── edge_lab.py         ← multi-strategy back-test harness
│   ├── mexc_trend_bot.py   ← trend-following strategy + live runner
│   ├── swing_backtest.py   ← swing strategy back-test
│   ├── swing_oos.py        ← out-of-sample validation
│   ├── swing_oos_wide.py   ← wider-parameter OOS sweep
│   ├── swing_oos_wide-edit.py
│   ├── swing_voltarget.py  ← volatility-targeting overlay
│   └── RUN_EDGE_LAB.bat    ← Windows launcher
│
├── discord/
│   ├── add_alerts_channel.py
│   ├── discord_post_content.py
│   ├── discord_role_sync.py
│   ├── role_sync_setup.bat
│   └── PATREON_DISCORD_SETUP.md
│
├── forward/
│   ├── ascent-forward.service  ← systemd unit
│   ├── forward_paper.py        ← paper-trade forward test
│   ├── forward_paper.bat
│   └── forward_state.json
│
├── installer/
│   └── AscentTerminal.iss  ← Inno Setup installer script
│
├── legal/
│   ├── DISCLAIMER.md
│   ├── PRIVACY.md
│   └── TERMS.md
│
├── server_launcher/
│   └── ascent_server.py    ← Flask app (auth, payments, keys)
│
├── tools/
│   ├── DEPLOY_TO_VPS.bat
│   ├── GENERATE_SECRETS.bat
│   ├── NEW_KEY.bat
│   ├── REVOKE_KEY.bat
│   ├── RUN_TESTS.bat
│   └── TEST_DISCORD_WEBHOOK.bat
│
└── whop_patreon/
    ├── REBRAND_COPY.md
    ├── patreon_setup_prompts.md
    └── whop_ai_prompts.md
```

---

## Key design decisions

### Why PyQt5 for the bot?
The target users are retail traders on Windows. A desktop GUI is more familiar than a CLI and doesn't require them to manage a server.

### Why Flask (not FastAPI)?
Simplicity. The server has ~10 endpoints. Flask's zero-magic routing is easier to audit quickly.

### Why MEXC?
Highest leverage limits available to non-US users (up to 200×), decent API, and the target community already uses it.

### Licence-key model
Keys are UUIDs stored in `platform/keys.json`. On each bot startup the key is validated against the server (`/api/validate`). The server checks Stripe/Whop membership status before returning OK.

---

## Data flow

```
User buys via Stripe / Whop
        │
        ▼
Stripe webhook → ascent_server.py → write key to keys.json
                                   → assign Discord role
        │
        ▼
User downloads installer (AscentTerminal.iss → .exe)
        │
        ▼
Bot starts → POST /api/validate with key
           → server checks keys.json + Stripe sub status
           → returns {"valid": true} or 401
        │
        ▼
Bot connects to MEXC WS → receives orderbook / trades
        │
        ▼
Strategy logic fires signal → places order via REST
        │
        ▼
Discord webhook → #alerts channel post
```

---

## Secrets & credentials

All secrets live in `.env` (never committed). See `GO_LIVE_STEPS.md §1` for the full variable list.

`platform/keys.json` is also gitignored — back it up separately.

---

## Running locally (dev)

```bash
# 1. Clone
git clone https://github.com/kd1685/Claude.git
cd Claude

# 2. Install deps
pip install -r requirements.txt

# 3. Copy and fill .env
cp .env.example .env

# 4. Start the server
python3 server_launcher/ascent_server.py

# 5. Run the bot (separate terminal)
python3 bots/scalper_bot.py
```

---

## Testing

```bash
tools\RUN_TESTS.bat   # Windows
# or
python3 -m pytest tests/ -v
```

There are currently integration-style smoke tests only (no unit tests). PRs adding pytest coverage are welcome.

---

## Deployment

See `GO_LIVE_STEPS.md` for the full VPS deploy walkthrough.

Quick reference:
```bash
bash tools/DEPLOY_TO_VPS.bat   # copies files, restarts service
```

---

## Known issues / TODOs

- [ ] `brain/mexc_trend_bot.py` has a hardcoded symbol list — make it config-driven
- [ ] No automated tests for the Flask routes
- [ ] Installer (`AscentTerminal.iss`) needs code-signing certificate
- [ ] Patreon webhook for real-time tier changes not yet wired up
- [ ] Rate-limit `/api/validate` to prevent key-brute-force

---

## Contact

Project owner: **kd1685** (GitHub)  
Email: mrpacstar@gmail.com
