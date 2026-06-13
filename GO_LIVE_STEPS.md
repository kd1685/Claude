══════════════════════════════════════════════════
 GO-LIVE CHECKLIST — Ascent Terminal
══════════════════════════════════════════════════

Complete these steps IN ORDER before you run any bot
with real money.

──────────────────────────────────────────────────
STEP 1 — Clone / pull the repo on your Windows PC
──────────────────────────────────────────────────
  git clone https://github.com/kd1685/Claude.git   (first time)
  — OR —
  git pull                                           (update)

──────────────────────────────────────────────────
STEP 2 — Run the organiser
──────────────────────────────────────────────────
  Double-click  organise.bat

  What it does
  • Creates the folder layout under  platform/
  • Copies bots and brain scripts into the right places
  • Writes a starter  .env  file  (platform/.env)
  • Writes  platform/requirements.txt
  • Writes  platform/run_bot.bat  (launcher)

──────────────────────────────────────────────────
STEP 3 — Fill in your credentials
──────────────────────────────────────────────────
  Open  platform\.env  in Notepad and fill in:

    MEXC_API_KEY=<your key>
    MEXC_API_SECRET=<your secret>
    TELEGRAM_BOT_TOKEN=<token from @BotFather>
    TELEGRAM_CHAT_ID=<your chat id>

  How to get each value
  ┌─────────────────────────────────────────────────┐
  │ MEXC API key                                    │
  │   mexc.com → Profile → API Management          │
  │   Permissions needed: Read + Trade (Futures)   │
  │   Whitelist: leave blank for now                │
  └─────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────┐
  │ Telegram bot token                              │
  │   Open Telegram → search @BotFather            │
  │   /newbot → follow prompts → copy token        │
  └─────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────┐
  │ Telegram chat id                                │
  │   Start your new bot, send it any message      │
  │   Visit:                                        │
  │   https://api.telegram.org/bot<TOKEN>/getUpdates│
  │   Copy the "id" field under "chat"             │
  └─────────────────────────────────────────────────┘

──────────────────────────────────────────────────
STEP 4 — Install Python dependencies
──────────────────────────────────────────────────
  Open a terminal inside  platform/  and run:

    pip install -r requirements.txt

  Required packages (organiser writes them for you):
    ccxt, python-dotenv, requests, pandas, numpy, ta

──────────────────────────────────────────────────
STEP 5 — Paper-trade first (STRONGLY recommended)
──────────────────────────────────────────────────
  In  platform\.env  make sure:

    PAPER_TRADE=true

  Run the bot:
    Double-click  platform\run_bot.bat
    — or —
    python bots/scalper_bot.py          (from platform/)

  Watch the Telegram channel.  You should see
  "[PAPER] BUY / SELL" messages instead of real orders.

  Let it run for at least 24 h before going live.

──────────────────────────────────────────────────
STEP 6 — Switch to live trading
──────────────────────────────────────────────────
  Change in  platform\.env:

    PAPER_TRADE=false

  Start with a SMALL position size:

    POSITION_SIZE_USDT=10

  Restart the bot.  First live Telegram message will
  confirm it connected to MEXC.

──────────────────────────────────────────────────
STEP 7 — Monitor & tune
──────────────────────────────────────────────────
  Log file:   platform/logs/scalper.log
  Trades CSV: platform/data/trades.csv   (auto-created)

  Tune in .env:
    POSITION_SIZE_USDT   — dollars per trade
    TP_PCT               — take-profit %  (default 0.8)
    SL_PCT               — stop-loss %   (default 0.4)
    RSI_OVERSOLD         — entry RSI     (default 35)
    RSI_OVERBOUGHT       — exit RSI      (default 65)

══════════════════════════════════════════════════
 DONE — you are live
══════════════════════════════════════════════════
