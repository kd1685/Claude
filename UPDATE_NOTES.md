════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — UPDATE NOTES (2026-06-11, "website + automation")
════════════════════════════════════════════════════════════════════

This update touches four areas: the scalper bot, the brain/edge lab,
the MEXC trend bot, and small website + tooling fixes.
Nothing in platform/data/, .env, or keys.json is changed.

──────────────────────────────────────────────────────────────────
 1  SCALPER BOT  (bots/scalper_bot.py)
──────────────────────────────────────────────────────────────────

What changed
  • Complete rewrite for production hardening.

Key improvements
  ┌─────────────────────────────────────────────────────────────┐
  │ Feature                  │ Before        │ After            │
  ├─────────────────────────────────────────────────────────────┤
  │ Position sizing          │ fixed USDT    │ ATR-adaptive     │
  │ Fee accounting           │ ignored       │ taker fee baked  │
  │ Heartbeat / monitoring   │ none          │ Redis + Prom.    │
  │ Shutdown                 │ SIGKILL       │ graceful drain   │
  │ Logging                  │ print()       │ structlog JSON   │
  │ Error recovery           │ crash         │ retry + backoff  │
  └─────────────────────────────────────────────────────────────┘

No configuration changes required — it reads the same .env keys.

──────────────────────────────────────────────────────────────────
 2  EDGE LAB  (brain/edge_lab.py  +  brain/RUN_EDGE_LAB.bat)
──────────────────────────────────────────────────────────────────

What changed
  • Walk-forward engine now runs folds in parallel (ProcessPool).
  • Regime filter added (ADX threshold gates trading).
  • Auto parameter sweep: tests ±20 % around your base params.
  • Output: CSV as before + new HTML report (edge_report.html).
  • RUN_EDGE_LAB.bat updated — opens HTML report when done.

Expected run time
  Local (8-core Windows): ~12 min for 3-year BTC/USDT daily.
  VPS (4-core):           ~25 min.

──────────────────────────────────────────────────────────────────
 3  MEXC TREND BOT  (brain/mexc_trend_bot.py)
──────────────────────────────────────────────────────────────────

What changed
  • Kelly Criterion position sizing (replaces fixed %).
  • Drawdown circuit-breaker: halts trading if DD > threshold.
  • Position reconciliation on startup (reads open orders from
    exchange, so a restart doesn't double-up positions).
  • Cleaner logging, same .env keys.

──────────────────────────────────────────────────────────────────
 4  WEBSITE + TOOLING
──────────────────────────────────────────────────────────────────

  • UPDATE.bat   — new deployment script (see README_WINDOWS_KIT).
  • organise.bat — sorts Downloads folder into subfolders by type.
  • GO_LIVE_STEPS.md / LAUNCH_PLAN.txt — owner runbooks.
  • WHAT_TO_DO_NOW.txt — condensed action list.
  • HANDOFF.md — full project brief for continuing in a new chat.

──────────────────────────────────────────────────────────────────
 NOTHING ELSE CHANGED
──────────────────────────────────────────────────────────────────

Files NOT touched (safe to deploy over live):
  platform/app.py, platform/models.py, platform/stripe_utils.py,
  platform/templates/**, platform/static/**,
  desktop/ascent_desktop.py,
  requirements.txt, .env, keys.json, data/**
