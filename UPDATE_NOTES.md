════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — UPDATE NOTES (2026-06-11, "website + automation")
════════════════════════════════════════════════════════════════════
This build is CODE ONLY — your live .env, keys.json and data/ are NOT
in the zip and are never overwritten. Upload over the top, then:
  docker compose up -d --build          (on the VPS)

──────────────────────────────────────────────────────────────────
 WHAT'S NEW
──────────────────────────────────────────────────────────────────
WEBSITE
• Landing page now at  /  (hero, features, transparency, pricing,
  about, FAQ, email capture, risk footer). The terminal moved to /app
  (old / bookmarks: /terminal 308-redirects to /app; the desktop app
  now points at /app).
• Download page at /download. Put release files in static/dl/ and
  paste the real SHA-256 into download.html after building the exe
  (see README_WINDOWS_KIT.md — desktop/, installer/, server_launcher/).
• Security headers on every response: CSP, HSTS, nosniff, frame
  protection, referrer + permissions policies.

AUTOMATED KEY DELIVERY — you never run key_gen for a buyer again
• POST /api/whop-webhook  +  POST /api/stripe-webhook (signatures
  verified; replay-protected). Payment → key issued at the right tier
  → emailed to the buyer. Cancellation/refund → key revoked instantly.
  Renewals (Stripe invoice.paid) extend expiry automatically.
• All-or-nothing: if the email can't be sent the key is rolled back
  and the store retries — nobody pays without receiving a key.
• Needs SMTP_* set in .env (see .env.example). Whop products must
  contain observer/operator/architect in the title; Stripe Payment
  Links need metadata tier=<tier>.
• Landing-page form → POST /api/register (mailing list);
  GET /api/register-list?key=<architect key> to read it.

TERMINAL
• AI tab: Claude's read moved out of Signals into its own tab, same
  settings panel. Per-key DAILY QUOTAS by tier (10/30/100 fresh
  analyses; cached results free; shown in the card meta) — bake the
  API cost into your tier pricing, no separate billing needed.
• Indicator PRESETS in the ⚙ drawer: BALANCED · TREND · MOMENTUM ·
  REVERSION · VOL & VOL — one-click starting points; tweak after.
• BOTS tab: run MULTIPLE instances of each bot (＋ ADD TREND BOT /
  ＋ ADD SCALPER, up to 8 total), each with its own name, config,
  positions and event log; ✕ removes one. Your existing bot state
  migrates automatically into the first instance of each kind.
  API moved to /api/bots/create, /api/bots/{id}/start|stop, DELETE
  /api/bots/{id}.
• Asset picker: fixed the bug where tapping WATCHLIST/TOP TRADED/etc
  closed the panel. WATCHLIST is now YOURS — ☆ any asset anywhere
  (top traded, all assets, search) to star it (saved per device,
  seeded from the tracked list on first run). The terminal's EMA30
  signal list lives in its own TREND tab.
• Header tagline → "Climb with clarity". Wording pass: "unvalidated"
  framing replaced with 🧪 RESEARCH LAB and forward-looking copy
  (backtest → paper → live). No claims changed — only tone.
• Trend-bot note now says futures shorting "lands in the web bridge
  soon — available today in the desktop bot".

──────────────────────────────────────────────────────────────────
 ACTION NEEDED (your .env on the VPS, then force-recreate)
──────────────────────────────────────────────────────────────────
1. TV_WEBHOOK_SECRET is currently EMPTY on your server → the alert
   receiver is unprotected. Set it (openssl rand -hex 32) and put the
   same string in your TradingView alert JSON.
2. ROTATE EXECUTE_KEY and your DISCORD_WEBHOOK_URL — they were
   included in the .env you uploaded to chat. Low risk, good hygiene.
3. SMTP_* + WHOP_WEBHOOK_SECRET / STRIPE_WEBHOOK_SECRET when you're
   ready to switch on automated key delivery.
4. Optional: AI_QUOTA_* overrides.

──────────────────────────────────────────────────────────────────
 NEW FILES
──────────────────────────────────────────────────────────────────
platform/billing.py            webhooks + email + register endpoints
platform/.env.example          every setting documented
platform/static/landing.html   the site front page  (served at /)
platform/static/download.html  the download page    (served at /download)
platform/static/dl/            put built installers here
platform/desktop/              new desktop client + python build script
installer/AscentTerminal.iss   Inno Setup installer script
server_launcher/ascent_server.py  replaces run_local.bat (no AV flags)
README_WINDOWS_KIT.md          exe/installer build + signing guide
════════════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────────────
 SECOND PASS (same day): pricing, entitlements, brand v3
────────────────────────────────────────────────────────────────────
• Pricing final: site $15/$39/$89 (marketplaces $19/$49/$99) + add-ons
  (+2 bot slots $9/mo · +50 AI analyses/day $9/mo) on the landing page.
• Per-key entitlements enforced server-side: Architect keys run 3 bot
  instances (BOT_BASE_ALLOWANCE); keys see/control only their own bots
  (your env key sees all); AI daily quota = tier base + purchased boost.
  Stripe add-on Payment Links (metadata addon=bots|ai + custom field
  "accesskey") apply and remove boosts automatically; manual:
  key_gen.py addon --key … --bots 2 --ai 50.
• Logo v3: rebuilt mark (depth extrusion, 5-stop metal, specular edges,
  sheen, polished arrow) swapped into the app, landing, download pages;
  ALL brand exports regenerated (static/brand/, incl. new wordmark and
  banners; generator: static/brand/make_brand_v3.py).
• forward/ascent-forward.service — run the live track record 24/7 on
  the VPS (GO_LIVE_STEPS.md §7).
• whop_patreon/REBRAND_COPY.md — paste-ready platform copy + X thread.
• GO_LIVE_STEPS.md — the ordered runbook for everything above.

────────────────────────────────────────────────────────────────────
 THIRD PASS: live tape intelligence (order flow)
────────────────────────────────────────────────────────────────────
New platform/orderflow.py + GET /api/orderflow/{symbol} (observer+) —
four ADAPTIVE live reads from public trade + order-book data, shown as
new tiles in the Positioning & Market Context grid (crypto only):
  • Whale flow — buy/sell imbalance of prints ≥ the 95th percentile of
    recent trade size (self-scales from BTC to microcaps)
  • Taker flow — CVD-style buy vs sell pressure across all trades
    (uses exchange sides; falls back to tick-rule and says so)
  • Book ±2% — resting bid vs ask depth imbalance around mid
  • Wall — biggest resting order ≥8× median level size, either side
Claude's read gains an "ORDER FLOW (LIVE)" context toggle.
Deliberately NOT panel votes: tick/book history isn't freely available,
so these can't be backtested — they're live context, and keeping them
out of the panel keeps the Strategy Lab and edge_lab honest.
Cached ~75s per symbol/exchange; fails soft without ccxt.

────────────────────────────────────────────────────────────────────
 FOURTH PASS: liquidation feed
────────────────────────────────────────────────────────────────────
platform/liquidations.py — streams Binance USDT-perp force orders over
one websocket (auto-reconnect; pure-python websocket-client added to
requirements; disable with LIQ_FEED=false). New gated endpoints
/api/liquidations and /api/liquidations/{symbol}: 5-min + 1-hour long
vs short liq USD (global + per asset), biggest print, and CASCADE
detection (current 5-min total vs trailing baseline → NONE / ELEVATED
/ CASCADE). Two new grid tiles: "Liqs 5m" (per-asset when it has
prints, else global) and a "Liq cascade" warning tile; honest
"warming up" tile during the first hour (the stream has no history).
Claude's ORDER FLOW (LIVE) toggle now includes liquidation stress.
NOTE: requirements changed → deploy needs `docker compose up -d --build`.

────────────────────────────────────────────────────────────────────
 FIFTH PASS: drag-to-adjust TP/SL lines
────────────────────────────────────────────────────────────────────
The dashed TP/SL chart lines are now DRAGGABLE (operator tier+, while
unlocked). First-ever use shows a full warning; every commit shows a
compact old→new confirm; Esc cancels mid-drag; chart pan/zoom pauses
while dragging. Commits POST /api/levels/{symbol} (validated, gated),
stored as a synthetic ADJUST alert — so the change persists across
restarts, shows as an audit row in the Alerts tab, and propagates to
everything that reads the levels (chart, alert context, bots/exec
reference, AI). HONESTY BUILT IN: the warning states plainly that this
does NOT modify orders resting on an exchange — bridge v1 does not
place native exchange TP/SL orders (that remains roadmap item 12).

────────────────────────────────────────────────────────────────────
 SIXTH PASS: performance audit
────────────────────────────────────────────────────────────────────
• Caddy now compresses responses (encode zstd gzip, both Caddyfiles):
  terminal page 134→36 KB, landing 45→13 KB (~73% smaller, the single
  biggest real-world load-time win). Caddy must restart to pick it up:
  docker compose up -d --force-recreate
• Liquidation summaries: 5-second cache (6.4 ms → ~0.001 ms per call at
  worst-case ring size) + the event ring now time-prunes to a 2-hour
  horizon instead of only count-capping.
• Watchlist stars no longer JSON-parse localStorage per row (one
  Set per picker render — mattered at 400 rows in ALL ASSETS).
• Billing sign-up rate-limit map prunes stale IPs (no unbounded growth).
• Measured in-process p95 latency after changes: every hot endpoint
  (health, alerts, bots, liquidations, both pages) under 4 ms.

────────────────────────────────────────────────────────────────────
 SEVENTH PASS: roadmap item 12 (half a) — protective TP/SL exits
────────────────────────────────────────────────────────────────────
platform/exits.py + /api/exits endpoints + UI. Tick "🛡 watch TP/SL
after fill" in the ⚡ Execute panel: after a BUY fills, the server
watches price (~10s) and market-SELLs the filled amount through the
execution bridge (every gate intact) the moment TP or SL is touched.
Dragging the chart TP/SL lines moves the ARMED triggers live (the
drag warning says so). New "Protective exits" card on the Alerts tab
(status, cancel); plans persist and RE-ARM after restarts (a stop
should not vanish because the server rebooted); bridge disarmed ⇒
plans suspend with the reason shown, re-arm automatically. Works on
every ccxt exchange — server-watched, NOT exchange-held: if the
server is down it cannot fire (stated in the UI). Native exchange
OCO (half b) remains: needs live per-exchange verification with the
owner's keys post-launch.

────────────────────────────────────────────────────────────────────
 EIGHTH PASS: personal-data encryption + automated GDPR
────────────────────────────────────────────────────────────────────
platform/privacy.py + /privacy-tools page + /api/gdpr/* endpoints.
All stored customer emails encrypted at rest (Fernet, DATA_KEY env);
key notes/billing events carry anonymous HMAC tags, never addresses;
owner mailing-list endpoint returns a count only. Self-service:
instant unsubscribe with permanent suppression, and two-step right-
to-erasure (signed 24h email link → revokes keys, deletes billing
refs + mailing entry, suppresses tag). Key-delivery emails link to
/privacy-tools. New dep: cryptography (deploy with --build). Suite
now 15 tests incl. "no plaintext email anywhere on disk".

────────────────────────────────────────────────────────────────────
 NINTH PASS: per-user order caps
────────────────────────────────────────────────────────────────────
EXEC_MAX_USD demoted to optional server-wide ceiling (0 = none).
Each key now carries its own per-order cap: GET/POST /api/user-cap
(operator+), "🧢 Your max per order" field in the Execute panel,
enforced on every order path from that key — manual tv-execute, bot
instances (via bot.owner), protective exits (plans store their
creator). User cap clamps to the server ceiling when one is set;
0 = no personal cap. Suite now 18 tests.

────────────────────────────────────────────────────────────────────
 TENTH PASS: payment-failed courtesy emails
────────────────────────────────────────────────────────────────────
Whop invoice_past_due + Stripe invoice.payment_failed now send the
customer a friendly "renewal didn't go through — update your card"
email (decrypted only at send time; throttled to one per membership
per 3 days; transactional so it sends regardless of marketing
unsubscribe; never revokes — deactivation still handles that).
Whop events to tick are now FOUR: membership_activated,
membership_deactivated, invoice_paid, invoice_past_due. Suite: 20.
