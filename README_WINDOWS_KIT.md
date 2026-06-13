# Ascent Terminal — Windows kit

What's in this folder and how to get started on a Windows PC.

---

## Quick start (3 steps)

1. **Run `organise.bat`** — sets up the `platform/` folder,
   copies scripts, writes starter `.env` and `requirements.txt`.

2. **Fill in `platform\.env`** — add your MEXC API key/secret
   and Telegram credentials.

3. **Double-click `platform\run_bot.bat`** — starts the scalper.

For the full checklist see `GO_LIVE_STEPS.md`.

---

## Files in this kit

| File / folder | Purpose |
|---|---|
| `organise.bat` | One-click setup |
| `UPDATE.bat` | Pull latest code + upgrade packages |
| `GO_LIVE_STEPS.md` | Step-by-step go-live guide |
| `HANDOFF.md` | Full project overview |
| `UPDATE_NOTES.md` | Change log |
| `LAUNCH_PLAN.txt` | Phased rollout plan |
| `WHAT_TO_DO_NOW.txt` | Cheat-sheet for right now |
| `bots/scalper_bot.py` | 1-min scalper (main bot) |
| `brain/mexc_trend_bot.py` | Daily trend-follower |
| `brain/edge_lab.py` | Parameter research tool |
| `brain/swing_backtest.py` | Swing-trade backtester |
| `brain/RUN_EDGE_LAB.bat` | Launcher for edge_lab |

---

## Python version

Use **Python 3.10 or newer**.
Download from https://www.python.org/downloads/
Tick "Add Python to PATH" during install.

---

## Installing dependencies

After running `organise.bat`:

```
cd platform
pip install -r requirements.txt
```

Packages installed: `ccxt`, `python-dotenv`, `requests`,
`pandas`, `numpy`, `ta`

---

## Telegram setup (5 min)

1. Open Telegram, search **@BotFather**
2. `/newbot` → follow prompts → copy the token
3. Send any message to your new bot
4. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Copy the `id` field under `chat` — that's your chat id

---

## MEXC API setup

1. Log in to mexc.com
2. Profile → API Management → Create API Key
3. Permissions: **Read** + **Trade** (Futures)
4. Copy key and secret into `platform\.env`
5. Do **not** enable withdrawal permission

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip` not found | Re-install Python with "Add to PATH" ticked |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| No Telegram messages | Check token and chat id in `.env` |
| MEXC auth error | Re-generate API key, paste carefully |
| Bot opens and closes instantly | Right-click bat → Run as Administrator |
