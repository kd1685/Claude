# Ascent Terminal — Update Notes
*(What changed, what you need to do, what stayed the same)*

---

## Build: 2026-06-12  (the launch build)

### What's new / fixed in this build

**Security**
- Proxy-header fix: uvicorn now trusts Caddy's `X-Forwarded-For` so the
  per-IP brute-force lockout works correctly behind a reverse proxy.  
  Ships automatically — `docker compose up -d --build` is enough.
- `TV_WEBHOOK_SECRET` enforcement: the receiver now **rejects** alerts
  that don't include the correct secret. Set the variable (see §2 of
  GO_LIVE_STEPS.md) and add `"secret":"…"` to every TradingView alert JSON.
- `DATA_KEY` (Fernet): customer emails stored in keys.json / the mailing
  list are now encrypted at rest. Generate and add the key (see §13).

**Billing / keys**
- Stripe `invoice.payment_failed` handler: sends a courtesy
  "please update your card" email (throttled, never revokes the key).
- Add-on cancel decrements the key's allowance correctly (was a no-op).
- `/api/register` mailing list: suppression list checked on sign-up.

**Bots**
- Per-key bot allowance: architect keys get `BOT_BASE_ALLOWANCE` instances
  (default 3); `+2 Bot Slots` add-on raises that key's cap by 2. Keys only
  see and control their own bots; env/owner key sees all.
- `delete_kv` + `kv_keys` added to store_db (needed by bot state cleanup).

**Exits (TP/SL watcher)**
- Plans now persist across restarts and RE-ARM automatically (protective
  by design). Suspend when bridge is disarmed; ERROR state stops retries.
- Chart-line drags update armed exit plans (POST `/api/levels` → ADJUST
  audit alert).

**UI**
- Asset picker: click-outside bug fixed (detached-target check).
- Execute panel: watch-TP/SL checkbox wires the protective-exit system.
- Bots tab: dynamic instance cards; ADD buttons gated by allowance.
- TP/SL lines now draggable (operator+) with first-use warning +
  per-commit confirm dialog.
- Tagline updated to "Climb with clarity".
- Gold AT mark v3 (inline SVG `#apexMark`, 1024 px base) in header + lock.

**Legal / compliance**
- `/legal/terms`, `/legal/privacy`, `/legal/disclaimer` now render
  (footer links were broken).
- Terms-acceptance gate on the lock screen (version-stamped, server-side
  record). `TERMS_VERSION` in app.py re-prompts on bump.
- GDPR self-service at `/privacy-tools`: unsubscribe + right-to-erasure
  (emailed confirmation link → revokes key, deletes billing refs,
  suppresses address). Fully automated.

**Public site**
- OG / Twitter social cards (`brand/og-card.png` + meta tags on `/` and
  `/download`).
- `robots.txt` + `sitemap.xml` served.
- `sales@` added to landing footer.

**Brand**
- Logo v3: extruded metallic gold AT mark. Full export pack in
  `platform/static/brand/` (Discord icon/banner, Patreon cover,
  wordmark, OG card, iOS icon).

**Tooling**
- `tools\` folder: one-click `.bat` helpers for secrets, key gen/revoke,
  tests, Discord webhook test, safe VPS deploy.
- Test suite expanded: 12 tests (was 8), ~1s, no network.
- `backup.sh` added (nightly tar of keys.json + data/ + .env).
- `ascent-forward.service` for the forward paper tester.
- `Caddyfile.cloudflare` for Cloudflare origin-cert mode.

**Per-user order caps**
- `EXEC_MAX_USD` in `.env` is now a server-wide ceiling only.
  Each operator+ user sets their own max in the ⚡ Execute panel;
  it applies to all orders from their key (manual, bots, exits).

---

### What you need to do after uploading

See **GO_LIVE_STEPS.md** for the full sequence. The mandatory items:

1. `docker compose up -d --build` (proxy fix + new deps ship in the image).
2. Set `TV_WEBHOOK_SECRET` (currently empty — receiver unprotected).
3. Rotate `EXECUTE_KEY` + `DISCORD_WEBHOOK_URL` (both were in a chat upload).
4. Generate + set `DATA_KEY` for email encryption.
5. `docker compose up -d --force-recreate` after `.env` changes.

Everything else (Stripe, Cloudflare, forward service, Windows kit) is
optional / on your own timeline — see the numbered sections in
GO_LIVE_STEPS.md.

---

### What stayed the same / is unaffected

- Your `.env` (not overwritten by the scp upload).
- `keys.json` and `data/` (mounted outside the container — never touched).
- Your two existing bots return as "Trend bot 1" / "Scalper 1" after restart
  (they come back STOPPED — start them from the BOTS tab).
- TradingView webhook pipe (alerts still land; the only change is the secret
  is now enforced — add it to your alert JSONs).
- All existing subscriber keys and tiers.
- The execution bridge (dry-run default unchanged; EXEC_LIVE stays as set).

---

## Earlier builds

*(Only the launch build is documented here. For the history of the ROK bot
and earlier iterations, see the previous project chat.)*
