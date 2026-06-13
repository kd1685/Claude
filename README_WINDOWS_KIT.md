# Ascent Terminal — Windows Kit

Everything you need to run Ascent Terminal on a Windows 10/11 machine.

---

## Quick start

1. **Install Python 3.11+** from https://python.org (tick "Add to PATH")
2. **Clone or download** this repository
3. **Double-click `UPDATE.bat`** — it installs all dependencies and checks your environment
4. **Fill in `.env`** with your MEXC API keys and licence key (see below)
5. **Double-click `bots/scalper_bot.py`** — or run `python bots/scalper_bot.py` in a terminal

---

## What each `.bat` file does

| File | Purpose |
|------|---------|
| `UPDATE.bat` | Pulls latest code from GitHub, installs/upgrades pip deps |
| `organise.bat` | Housekeeping — cleans `__pycache__`, old logs, temp files |
| `brain/RUN_EDGE_LAB.bat` | Runs the full back-test suite (`brain/edge_lab.py`) |
| `forward/forward_paper.bat` | Runs the paper-trade forward test |
| `tools/DEPLOY_TO_VPS.bat` | Deploys latest code to your VPS via SCP |
| `tools/GENERATE_SECRETS.bat` | Generates a new `SECRET_KEY` for `.env` |
| `tools/NEW_KEY.bat` | Creates a new subscriber licence key |
| `tools/REVOKE_KEY.bat` | Revokes a subscriber licence key |
| `tools/RUN_TESTS.bat` | Runs the test suite |
| `tools/TEST_DISCORD_WEBHOOK.bat` | Sends a test message to your Discord #alerts channel |

---

## Environment variables

Create a file called `.env` in the root of this repository (copy from `.env.example`):

```
MEXC_API_KEY=your_mexc_api_key
MEXC_SECRET_KEY=your_mexc_secret_key
LICENCE_KEY=your_ascent_terminal_licence_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SERVER_URL=https://ascent-terminal.com
```

---

## Running the back-tests

```bat
brain\RUN_EDGE_LAB.bat
```

Or from a terminal:
```bash
python brain/edge_lab.py --symbol BTCUSDT --days 90
```

Results are saved to `brain/results/`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Re-install Python 3.11+ and tick "Add to PATH" |
| `ModuleNotFoundError` | Run `UPDATE.bat` to reinstall dependencies |
| Bot won't connect | Check MEXC API key permissions (Futures read + trade) |
| Licence invalid | Check `SERVER_URL` in `.env`; contact support |
| Discord alerts not working | Re-run `tools/TEST_DISCORD_WEBHOOK.bat` to diagnose |

---

## Support

Join the Discord server (link in your Whop / Patreon membership area) and post in #support.
