# AscentTerminal — Update Notes

This file documents every meaningful change made to the platform since the
initial ROK-bot handoff. Most recent first.

---

## 2026-06-12 — Launch Build (current)

### Stripe direct checkout + automated key delivery
- `billing.py`: new `/api/stripe-webhook` endpoint. Handles
  `checkout.session.completed`, `invoice.paid`,
  `customer.subscription.deleted`, `invoice.payment_failed`.
- Payment Links with `tier` metadata → key issued and emailed on purchase;
  cancel → immediate revoke.
- Add-on Payment Links (`addon=bots|ai` metadata + `accesskey` custom field)
  raise per-key allowances; cancellation decrements them.
- Stripe signature verification (`STRIPE_WEBHOOK_SECRET`).
- `invoice.payment_failed` sends a courtesy "update your card" email
  (throttled, never revokes).

### Per-user order caps
- Operator+ users set their own `max_per_order` limit in the ⚡ Execute panel.
- `EXEC_MAX_USD` in `.env` is now a server-wide ceiling only (abuse guard).
- Setting is persisted per-key in `keys.json` and respected by bots and
  protective exits.

### Protective TP/SL (exits.py) — server-watched watcher
- After a BUY, the server polls price (~10s) and fires a market SELL when
  TP or SL is touched.
- Plans survive restart (re-arm on boot), suspend when bridge is disarmed,
  ERROR state stops retries.
- Execute panel: new "Watch TP/SL" checkbox wires the filled order into exits.
- Chart-line drags (operator+) move armed plans in real time.

### Draggable TP/SL lines
- Operator+ can drag the TP/SL lines on the chart.
- First-use warning modal; per-drag confirm before committing.
- `POST /api/levels` → ADJUST audit alert.

### Multi-instance bots
- `bots.py` rewritten: create/delete instances (max 8 server-wide).
- Per-key allowance: architect base 3 (`BOT_BASE_ALLOWANCE` in `.env`) +
  `bots` addon; keys see/control only their own bots; env/owner key sees all.
- Two bot types: TrendBot (EMA30 daily) + ScalperBot (indicator config).
- Bots return STOPPED on restart (deliberate — never auto-trade after reboot).

### AI quotas + addon
- Per-key daily quotas: observer 10 / operator 30 / architect 100
  (`AI_QUOTA_*` in `.env`).
- `+50 AI/day` add-on stacks on the key.
- Cache hits are free.

### Legal pages
- `legal/TERMS.md`, `PRIVACY.md`, `DISCLAIMER.md` rendered to
  `platform/static/legal/*.html`.
- Footer links now resolve (were broken in previous build).
- Terms acceptance gate on lock screen: first unlock per device requires
  ticking agreement; acceptance recorded server-side with version + timestamp.
- `TERMS_VERSION` in `app.py` re-prompts everyone on bump.

### GDPR / data encryption
- Customer emails encrypted at rest (`DATA_KEY` in `.env`, Fernet).
- Self-service `/privacy-tools`: instant unsubscribe + right-to-erasure
  (emailed confirmation link → revoke key + delete billing refs + suppress).

### Proxy / brute-force fix
- `Dockerfile` passes `--proxy-headers` to uvicorn so Caddy's
  `X-Forwarded-For` is trusted; brute-force lockout now works per real IP.

### Cloudflare support
- `Caddyfile.cloudflare`: Cloudflare origin cert mode (`trusted_proxies` set
  to CF IP ranges).
- `GO_LIVE_STEPS.md §11` covers the full CF setup sequence.

### Social / SEO
- `brand/og-card.png` + OG/Twitter meta on `/` and `/download`.
- `robots.txt` + `sitemap.xml` served.

### Backups
- `platform/backup.sh`: nightly tar of `keys.json + data/ + .env`.
- Instructions in `GO_LIVE_STEPS.md §10`.

### Test suite
- `tests/test_platform.py`: 12 pytest tests (~1s, mocked network, throwaway DB).
- `tools/RUN_TESTS.bat` runs it.

### Tools
- `tools/GENERATE_SECRETS.bat` — generate TV/EXECUTE/DATA keys.
- `tools/NEW_KEY.bat` / `REVOKE_KEY.bat` — key management.
- `tools/TEST_DISCORD_WEBHOOK.bat` — validate webhook before use.
- `tools/DEPLOY_TO_VPS.bat` — safe upload + rebuild (never touches server
  `.env`/`keys`/`data`).

---

## 2026-05-XX — Bots + Execution Bridge

### Execution bridge
- `execution.py`: LIVE gate (EXECUTE_KEY + EXEC_LIVE=true + dry_run:false +
  notional check + user creds).
- Accepts `quote_amount` or base `amount`.
- Exec log ring → SQLite write-through.

### Multi-broker support
- ccxt integration: Binance, Bybit, OKX, KuCoin, Gate, Bitget, Kraken.
- MEXC native remains the default.

### Scalper bot standalone
- `bots/scalper_bot.py`: full standalone scalper for users who want to run
  the bot outside the platform.

---

## 2026-04-XX — Terminal v2

### Order-flow + liquidations
- `orderflow.py`: live tape (Whale flow, Taker CVD, Book imbalance, Wall
  detector).
- `liquidations.py`: Binance perp WebSocket feed, cascade detection.

### Asset picker
- WATCHLIST / TREND / TOP TRADED / GAINERS / LOSERS / ALL ASSETS views.
- SPOT/PERPS pills.
- Click-outside bug fixed.

### AI analyst
- `ai_analyst.py`: Claude, own AI tab, toggleable context.

### Indicator presets
- Drawer: Balanced / Trend / Momentum / Reversion / Vol&Vol.

---

## 2026-03-XX — Initial handoff from ROK bot

- FastAPI platform scaffolded from ROK bot codebase.
- SHA-256-hashed keys in keys.json.
- TradingView webhook → ALERTS tab.
- EMA30 trend signal + proof panel (validated out-of-sample, 40 coins).
- Discord webhook for trend-flip posts.
