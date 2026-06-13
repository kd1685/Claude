# Ascent Terminal — Project Handoff (current as of 2026-06-12, launch build)

Paste this into a new chat as the project brief. Upload the current
`AscentTerminal` zip with it — this file describes the code, it doesn't
contain it.

## What it is
A **non-custodial, multi-asset trading platform** at https://ascentterminal.com.
Site: landing page at `/`, terminal app at `/app`, downloads at `/download`,
legal pages at `/legal/*`. Terminal: charts + signals + 26-indicator toolkit +
live order-flow/liquidation intel + alerts + AI analyst + proof panel +
execution bridge + multi-instance bots. We never hold user funds or keys.

## The one hard-won truth (KEEP THIS GUARDRAIL)
Rigorously proven (40-coin out-of-sample): **indicator scalping has NO
fee-beating edge**. The ONE validated edge is **EMA30 daily trend** (~26%
CAGR / 34% DD). Indicators = analysis tools + alerts + backtestable; the
proof panel shows the validated edge; we NEVER market indicators as
guaranteed signals or promise profits. Wording style: honest but
forward-looking — "🧪 RESEARCH LAB", "prove it before you trust it" — the
owner's rule: no lies, no negative framing.

## Architecture (platform/ = the deployed app; Docker context is platform/ ONLY)
- **app.py** — FastAPI. Security-headers middleware (CSP/HSTS/nosniff),
  brute-force lockout (per-IP; uvicorn runs `--proxy-headers` so real IPs
  survive Caddy/Cloudflare), tier gates, all routes.
- **auth.py / key_gen.py** — SHA-256-hashed keys in keys.json (hot-reload,
  no restarts), tiers observer < operator < architect, per-key `addons`
  {bots, ai}. CLI: `new`, `revoke`, `list`, `addon --key ... --bots N --ai N`.
- **billing.py** — automated key delivery. `/api/whop-webhook` +
  `/api/stripe-webhook` (signature-verified): payment -> key issued at tier ->
  emailed (SMTP_*; refuses + rolls back if email fails, store retries);
  cancel -> revoke; Stripe `invoice.paid` -> renew. Add-on Payment Links
  (metadata `addon=bots|ai` + custom field `accesskey`) raise per-key
  allowances; cancel decrements. `/api/register` mailing list.
- **execution.py** — the bridge. Gates for LIVE: EXECUTE_KEY + EXEC_LIVE=true +
  explicit dry_run:false + notional <= EXEC_MAX_USD + user creds. Accepts
  `quote_amount` or base `amount`. Exec log ring -> SQLite write-through.
- **bots.py** — MULTI-INSTANCE registry (create/delete, max 8 server-wide).
  TrendBot (EMA30 daily, the validated edge) + ScalperBot (user's indicator
  config — research lab). Per-key: architect base 3 instances
  (BOT_BASE_ALLOWANCE) + addons; keys see/control only their own bots;
  env/owner keys see all. Restart => bots return STOPPED (deliberate).
- **exits.py** — protective TP/SL watcher (roadmap 12 half-a, DONE): after a
  BUY, the server polls price (~10s) and market-SELLs the filled qty through
  the bridge when TP/SL is touched. Plans persist and RE-ARM on restart
  (protective by design); suspend when bridge disarmed; ERROR stops retries.
  Server-watched, NOT exchange-held (stated in UI). Chart-line drags move
  armed triggers.
- **orderflow.py** — live tape (crypto): adaptive Whale flow (p95 prints),
  Taker flow/CVD, Book +/-2% imbalance, Wall detector (>=8x median). 75s cache.
- **liquidations.py** — Binance perp force-order WEBSOCKET feed (LIQ_FEED env,
  websocket-client dep): 5m/1h long-vs-short liq USD global+per-asset,
  cascade detection (NONE/ELEVATED/CASCADE), 5s summary cache, 2h ring.
- **ai_analyst.py** — Claude analyst, own AI tab, user-toggleable context
  (incl. ORDER FLOW (LIVE)), per-key DAILY quotas: tier base (10/30/100,
  AI_QUOTA_*) + ai addon; cache hits free.
- **indicators.py** — 26-indicator registry; panel score = sum(w*vote)/sum(w)*10.
- **backtest.py** — in-app Strategy Lab (gated, fees, no lookahead, always
  benchmarked vs EMA30 + buy&hold, guardrail note verbatim).
- **webhook_store.py / store_db.py** — alert rings + SQLite write-through
  (alerts, exec log, bot state, exit plans, kv). `delete_kv`, `kv_keys` added.
- **static/index.html** — the terminal. Tabs CHART | SIGNALS | AI | ALERTS |
  BOTS | PROOF. Picker: WATCHLIST (user stars, per-device) | TREND (server
  EMA30 list) | TOP TRADED | GAINERS | LOSERS | ALL ASSETS; SPOT/PERPS pills;
  click-outside bug fixed (detached-target check). Drawer has PRESETS
  (Balanced/Trend/Momentum/Reversion/Vol&Vol). TP/SL lines DRAGGABLE
  (operator+; first-use warning + per-commit confirm; POST /api/levels ->
  ADJUST audit alert; moves armed exit plans). Execute panel: watch-TP/SL
  checkbox. Bots tab: dynamic instance cards + ADD buttons. Tagline "Climb
  with clarity". Header/lock use gold AT mark v3 (inline #apexMark, 1024).
- **static/landing.html / download.html / legal/** — public site (gold/black,
  Chakra Petch + IBM Plex), OG/Twitter cards (brand/og-card.png), robots.txt
  + sitemap.xml routes. Pricing: direct $15/$39/$89 + add-ons (+2 bots $9,
  +50 AI/day $9); marketplaces $19/$49/$99.
- **static/brand/** — logo v3 (extruded metallic gold AT) + full export pack;
  regenerate with `make_brand_v3.py`.
- **tests/test_platform.py** — pytest suite (12 tests, ~1s, mocked network,
  throwaway DB): run `python -m pytest tests -q` before EVERY deploy.
- **Deploy** — Docker + Caddy (`encode zstd gzip` on). `Caddyfile.cloudflare`
  = Cloudflare mode (origin cert in certs/, CF IPs as trusted_proxies).
  `backup.sh` nightly (keys.json+data+.env). NEVER run uvicorn --workers>1
  (in-process state). Single source of truth runbook: **GO_LIVE_STEPS.md**.

## Outside platform/ (owner-only, never deployed)
- **brain/edge_lab.py** — owner's mass-combination backtester: precomputed
  vote matrix (~1000x faster, verified == compute_panel), modes
  single/pairs/random/greedy/full, TRAIN(70)/TEST(30) split, basket-median
  ranking, luck-line (expected best Sharpe from noise given N tries).
  Survivors -> BOTS tab paper for weeks. brain/ also holds the original
  research + validated trend bot.
- **forward/** — forward paper tracker + `ascent-forward.service` (systemd,
  runs 24/7 on the VPS = the live track record).
- **installer/ + platform/desktop/ + server_launcher/** — Windows kit:
  pywebview desktop app -> PyInstaller (--onedir) -> Inno Setup installer;
  `ascent_server.py` replaces the .bat files (AV-clean). README_WINDOWS_KIT.md
  covers signing/SmartScreen strategy.
- **whop_patreon/REBRAND_COPY.md** — paste-ready platform copy + X launch
  thread. **legal/** — TERMS/PRIVACY/DISCLAIMER (England & Wales) — also
  rendered to platform/static/legal/*.html (regenerate if the md changes).

## Tiers & entitlements (server-enforced)
observer = signals/charts/panel/positioning/tape/AI 10/day ·
operator = + backtests, execution bridge, exits, draggable TP/SL, AI 30/day ·
architect = + bots (3 instances), AI 100/day. Add-ons stack per key.

## ROADMAP (post-launch)
1. **Native exchange-held TP/SL (OCO)** — item 12 half-b. Needs the OWNER:
   live verification per exchange (~$15 test trades), start Binance spot.
   exits.py is the integration point (add mode "native" beside the watcher).
2. **Live streaming charts** — websocket klines/trades -> tick the last candle
   (liquidations.py shows the ws-thread pattern to reuse).
3. Perp execution routing; landing-page product screenshots; Cloudflare
   Bot-Fight WAF skip rules if enabled.

## Launch state / owner to-dos (see GO_LIVE_STEPS.md sections 1-11)
Live on VPS. Outstanding for the owner: TV_WEBHOOK_SECRET (currently empty —
receiver unprotected!), rotate EXECUTE_KEY + Discord webhook (were in a chat
upload), Stripe setup (Payment Links + webhook + Stripe Tax + 14-day digital
waiver), SMTP, Cloudflare (section 11), backups cron, forward service, Windows
exe build, real screenshots, marketplace rebrand paste, fire the X thread.

## How to run / test
Local: `python server_launcher/ascent_server.py --setup` then without flag ->
http://localhost:8000 (landing) / /app (terminal). Tests: `cd platform &&
python -m pytest tests -q`. Deploy/update: scp + `docker compose up -d
--build` (requirements changed recently — --build matters).
