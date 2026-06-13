══════════════════════════════════════════════════
 UPDATE NOTES — Ascent Terminal
══════════════════════════════════════════════════

──────────────────────────────────────────────────
v3.0 — June 2025  (current)
──────────────────────────────────────────────────
Major rewrite — replaces the old ROK-coin bot.

What's new
  • scalper_bot.py — brand-new 1-min EMA/RSI scalper
      - Full paper-trade mode  (PAPER_TRADE=true)
      - Telegram alerts on every signal + fill
      - Trade log CSV  (platform/data/trades.csv)
      - Configurable via .env — no code changes needed

  • mexc_trend_bot.py — new daily trend-follower
      - ADX + EMA trend filter
      - ATR-based dynamic stops
      - Designed to run alongside the scalper

  • edge_lab.py — new research / optimisation tool
      - Scans multiple symbols and RSI param combos
      - Scores by Sharpe, win-rate, profit-factor
      - Outputs ranked CSV for offline review

  • swing_backtest.py — new backtester
      - Tests daily trend-following strategy
      - Equity curve + drawdown output

  • organise.bat — one-click Windows setup
      - Creates platform/ folder layout
      - Writes starter .env and requirements.txt
      - Copies all scripts into the right places

  • UPDATE.bat — one-click updater
      - git pull + pip upgrade + re-organise

  • Full documentation suite
      - GO_LIVE_STEPS.md
      - HANDOFF.md
      - LAUNCH_PLAN.txt
      - README_WINDOWS_KIT.md
      - WHAT_TO_DO_NOW.txt

Breaking changes
  • Old bot files removed — start fresh with organise.bat
  • .env format changed — see GO_LIVE_STEPS.md Step 3

──────────────────────────────────────────────────
v2.x — 2024  (retired)
──────────────────────────────────────────────────
ROK-coin focused bot.  Worked for ROK but too
niche — hard to adapt to other symbols.

Retired because:
  • ROK/USDT liquidity dropped
  • No paper-trade mode made testing risky
  • Hard-coded parameters — no .env configuration
  • No Telegram integration
  • No trade logging

──────────────────────────────────────────────────
v1.x — 2023  (retired)
──────────────────────────────────────────────────
First attempt — basic price-action bot.
Retired: no risk management, no logging.

══════════════════════════════════════════════════
 END OF UPDATE NOTES
══════════════════════════════════════════════════
