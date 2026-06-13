# UPDATE NOTES — Ascent Terminal

---

## v1.1 — Current release

### New
- AI analyst module (`ai_analyst.py`) — GPT-4o powered market commentary,
  gated behind Operator+ tier
- Liquidation heatmap endpoint (`liquidations.py`) — pulls Coinglass data
- Forex macro feed (`forex_data.py`) — DXY, yields, risk-on/off scoring
- Market intel aggregator (`market_intel.py`) — fear & greed, funding rates,
  open interest
- MEXC macro data (`mexc_macro.py`) — top movers, volume leaders
- Walk-forward edge lab (`brain/edge_lab.py`) — automated parameter optimisation
  with CSV output
- Swing strategy backtests (`brain/swing_*.py`)
- Forward paper-trade harness (`forward/forward_paper.py`)
- Discord role sync (`discord/discord_role_sync.py`) — auto-sync Whop/Patreon
  members to Discord roles
- Desktop app build script (`platform/desktop/`)
- Inno Setup installer script (`installer/AscentTerminal.iss`)
- Windows helper scripts (`tools/*.bat`)

### Improved
- `billing.py` — Stripe subscription lifecycle fully handled (created, updated,
  deleted, payment failed)
- `auth.py` — Whop OAuth + API key dual-auth, tier-based access control
- `app.py` — SSE live data feed, orderflow, indicators, exits, all wired up
- `indicators.py` — RSI, MACD, Bollinger Bands, ATR, VWAP, volume profile
- `exits.py` — multi-factor exit signal with confidence scoring
- `key_gen.py` — CLI for creating / revoking member API keys with tier support
- `store_db.py` — webhook event deduplication store
- `webhook_store.py` — persistent webhook event log

### Landing page
- Full redesign — dark theme, animated hero, pricing table, FAQ
- Stripe payment links wired to Observer / Operator / Architect tiers
- Add-on pills: +2 bot slots, +50 AI/day

---

## v1.0 — Initial release

- Basic Flask app with API key auth
- MEXC price feed
- Simple terminal UI
- Discord webhook alerts
