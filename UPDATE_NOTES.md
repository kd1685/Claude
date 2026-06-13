════════════════════════════════════════════════════════════════════
  UPDATE NOTES  —  AscentTerminal
  Latest entry at the top
════════════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────────────
2026-06-12  ·  LAUNCH BUILD  (v1.0)
────────────────────────────────────────────────────────────────────

This is the first production-ready build.  Everything below is what
was built, fixed, and validated in the pre-launch sprint.

NEW FEATURES

  Chart
  • TradingView Lightweight Charts v4 — candle + EMA overlays
  • TP/SL lines drawn automatically from incoming TV alerts
  • Segment selector: spot vs perps/futures
  • Multi-exchange support (MEXC, Binance, Bybit, OKX, Kraken,
    Coinbase, KuCoin, Gate.io, Bitget, HTX)
  • Forex, stocks, indices, metals & energy asset classes

  Signals
  • 26-indicator panel: trend, momentum, volatility, volume,
    market-structure, multi-timeframe, funding/OI, sentiment
  • Configurable weights + on/off toggles per indicator
  • Indicator settings drawer with 3 presets (Conservative,
    Balanced, Aggressive)
  • Strategy Lab backtester: your config vs EMA30 baseline
    vs buy & hold — equity curve chart included
  • Macro/positioning card: funding rate, OI, long/short ratio,
    liquidations, basis, VWAP, ATR

  AI
  • Claude AI tab: sends indicator panel + positioning + Fear &
    Greed + price action to Claude and displays structured analysis
  • Settings: context toggles, depth (brief/standard/deep),
    style (plain/pro), include outlook + risks
  • Auto-run option (analyses on tab open)
  • 15-minute per-asset cache to limit API spend

  Alerts & Execution
  • TradingView webhook ingestion (/api/tv-webhook)
  • Real-time alert push to UI via WebSocket
  • Paper + live order execution via CCXT (100+ exchanges)
  • Execute button on BUY/SELL alerts
  • Server-watched TP/SL watcher (~10 s polling)
  • Execution log (paper & live, newest first)
  • Protective exits panel with draggable chart lines
  • USER_CAP_USD per-order safety cap
  • AUTO_EXECUTE flag for hands-free alert execution

  Bots
  • EMA30 trend bot: configurable symbol, timeframe, risk %,
    leverage, max positions
  • MEXC scalper bot: momentum-based, configurable params
  • Bot events log in UI
  • BOTS tab badge shows running count

  UX
  • Asset picker: multi-market-type, search, favourites/watchlist
  • Fear & Greed index in header
  • Lock screen with TOS checkbox
  • Mobile-responsive layout
  • Indicator tooltip on hover in settings drawer
  • Preset row (Conservative / Balanced / Aggressive)

BUG FIXES (pre-launch)

  • Fixed WebSocket disconnect loop on Firefox
  • Fixed EMA calculation off-by-one on first candle
  • Fixed paper order amount not applying USER_CAP_USD
  • Fixed bot badge not clearing when last bot is deleted
  • Fixed picker z-index under the lock overlay
  • Fixed MEXC perps segment returning spot data
  • Fixed funding rate sign inversion (positive = longs pay)
  • Fixed AI cache key not including indicator config hash
  • Fixed Strategy Lab showing NaN when no trades taken
  • Fixed TP/SL chart lines not removing on asset switch

KNOWN ISSUES

  • State is in-memory → alerts, orders, bots reset on restart
    (SQLite persistence is the next planned feature)
  • TP/SL watcher is server-polled; won't fire if server is down
  • Single-worker server; bots run in threads, not async tasks
  • No multi-user support (one access key)

────────────────────────────────────────────────────────────────────
2026-05-XX  ·  PRE-LAUNCH SPRINT
────────────────────────────────────────────────────────────────────

  • Migrated from ROK bot prototype to AscentTerminal architecture
  • Replaced ccxt-based data fetcher with direct exchange REST calls
    for lower latency on the chart pane
  • Added multi-exchange support in the asset picker
  • Rebuilt indicator engine from scratch (26 indicators vs 8)
  • Added Claude AI tab (was a stub in the prototype)
  • Added Strategy Lab backtester (new)
  • Added TP/SL watcher (new)
  • Added bots UI panel (was CLI-only)
  • Rewrote front-end as a single self-contained HTML file
  • Added TOS / lock screen
  • Added mobile layout

════════════════════════════════════════════════════════════════════
END OF UPDATE NOTES
════════════════════════════════════════════════════════════════════
