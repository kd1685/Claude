════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — GO-LIVE STEPS (final pass · do in order)
════════════════════════════════════════════════════════════════════
This zip is CODE ONLY — your live .env, keys.json and data/ are never
overwritten. Times are realistic. §3 (Stripe) is the one you said
you're doing tomorrow; everything else can be done today.

──────────────────────────────────────────────────────────────────
 §1  UPLOAD THE UPDATE TO THE VPS (10 min)
──────────────────────────────────────────────────────────────────
From your PC (same scp pattern as DEPLOY.md — adjust paths):
    scp -r AscentTerminal root@<SERVER_IP>:/root/
On the server:
    cd /root/AscentTerminal/platform
    docker compose up -d --build
Nothing else changes yet — your existing keys and data carry over,
and your two existing bots reappear as "Trend bot 1" / "Scalper 1".

──────────────────────────────────────────────────────────────────
 §2  .env — SECURITY FIXES (5 min, nano .env on the server)
──────────────────────────────────────────────────────────────────
a) TV_WEBHOOK_SECRET is EMPTY right now → your TradingView receiver
   accepts alerts from anyone. Generate + set:
       openssl rand -hex 32
   …and put the SAME string inside each TradingView alert's JSON
   ("secret":"…").
b) ROTATE EXECUTE_KEY (new random string) — and re-enter it once in
   the UI when prompted. Also recreate your Discord webhook and update
   DISCORD_WEBHOOK_URL (both values were in the .env you uploaded to
   chat — low risk, cheap fix).
c) Apply:   docker compose up -d --force-recreate
   (.env is only read at container start — nano alone does nothing.)

──────────────────────────────────────────────────────────────────
 §3  STRIPE — DIRECT CHECKOUT + AUTOMATED KEYS (30 min, tomorrow)
──────────────────────────────────────────────────────────────────
1. EMAIL FIRST (keys are delivered by email; webhooks refuse without
   it). Easiest: resend.com free tier → verify your domain → SMTP
   credentials → put in .env:
       SMTP_HOST=smtp.resend.com   SMTP_PORT=587
       SMTP_USER=resend            SMTP_PASS=<api key>
       SMTP_FROM=support@ascentterminal.com
2. PRODUCTS (Stripe dashboard → Product catalogue): create 5 monthly
   recurring products:
       Observer $15 · Operator $39 · Architect $89
       +2 Bot Slots $9 · +50 AI Analyses/day $9
3. PAYMENT LINKS — one per product. CRITICAL settings on each link:
   • Tiers: add metadata     key: tier     value: observer|operator|architect
   • Add-ons: add metadata   key: addon    value: bots   (or: ai)
     AND add a required custom text field with field key  accesskey
     labelled "Your Ascent Terminal access key" (the add-on attaches
     to that key automatically).
4. WEBHOOK (Developers → Webhooks → Add endpoint):
       URL:    https://ascentterminal.com/api/stripe-webhook
       Events: checkout.session.completed · invoice.paid ·
               customer.subscription.deleted · invoice.payment_failed
               (the last one sends the customer a courtesy
               "update your card" email — throttled, never revokes)
   Copy the signing secret (whsec_…) → .env STRIPE_WEBHOOK_SECRET.
5. Paste the 5 Payment Link URLs into static/landing.html:
   the three tier buttons are marked data-checkout="observer|operator|
   architect"; put the add-on links on the two .addon-pill spans
   (wrap them in <a href="…">). Re-upload, force-recreate.
6. TEST with Stripe test mode first: a test checkout should land a
   key in your inbox within seconds; cancelling the test subscription
   should kill the key (check: /api/check?key=… or just try unlocking).

WHOP (optional, same automation): Developer → Webhooks → endpoint
https://ascentterminal.com/api/whop-webhook → copy the secret to .env
WHOP_WEBHOOK_SECRET. Name products with observer/operator/architect in
the title at $19/$49/$99 (copy in whop_patreon/REBRAND_COPY.md).
PATREON: no reliable per-tier webhook → keep manual key_gen there, or
phase it out in favour of Stripe + Whop.

──────────────────────────────────────────────────────────────────
 §4  NEW ALLOWANCES — what subscribers get (already enforced)
──────────────────────────────────────────────────────────────────
• Bots: each Architect key runs up to 3 instances (BOT_BASE_ALLOWANCE
  in .env). Each "+2 Bot Slots" purchase raises THAT key by 2. Keys
  only see and control their own bots; your env/owner key sees all.
• AI: fresh analyses/day — Observer 10 · Operator 30 · Architect 100
  (AI_QUOTA_* in .env). "+50 AI/day" purchases stack on the key.
  Cached results never count.
• Manual grants anytime:
      python key_gen.py addon --key <key|hash-prefix> --bots 2 --ai 50

──────────────────────────────────────────────────────────────────
 §5  REBRAND THE LIVE PLATFORMS (20 min)
──────────────────────────────────────────────────────────────────
Open whop_patreon/REBRAND_COPY.md — paste-ready: announcement post,
tier descriptions at the new prices, X launch thread for your bot,
one-liners. Graphics: platform/static/brand/ (all regenerated with
the new logo): discord-server-icon-512.png, discord-banner-1200x300,
patreon-cover-1600x400, ascent-wordmark.png.

──────────────────────────────────────────────────────────────────
 §6  DISCORD WEBHOOK FIX — get signal posts working (5 min)
──────────────────────────────────────────────────────────────────
How it works: the platform posts EMA30 trend FLIPS (LONG↔SHORT on
tracked coins) to ONE Discord webhook URL — the DISCORD_WEBHOOK_URL
in .env. You deleted that webhook, so flips post nowhere. (Your
"alerts" that still work are TradingView→platform — different pipe,
unaffected.)
1. Discord → your #signals channel (create it if needed) → Edit
   channel → Integrations → Webhooks → New Webhook → name it
   "Ascent Signals", set the avatar to brand/ascent-icon-128.png →
   Copy Webhook URL.
2. .env on the server:  DISCORD_WEBHOOK_URL=<that URL>
3. docker compose up -d --force-recreate
4. It posts on the next trend flip. The scripts in discord/ are for
   one-time channel/content setup, not needed here.

──────────────────────────────────────────────────────────────────
 §7  FORWARD TESTER ON THE VPS — your live track record (5 min)
──────────────────────────────────────────────────────────────────
Runs OUTSIDE docker as a tiny systemd service, acts once per UTC day:
    apt install -y python3-requests
    cp /root/AscentTerminal/forward/ascent-forward.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now ascent-forward
    systemctl status ascent-forward          # should say active (running)
Logs:  journalctl -u ascent-forward -f
Track record accrues in /root/AscentTerminal/forward/forward_log.csv —
timestamped daily equity, your "live since <date>" receipts.
(If your install path differs, edit the two paths inside the .service.)

──────────────────────────────────────────────────────────────────
 §8  WINDOWS APP + DOWNLOAD PAGE (when ready, ~20 min on your PC)
──────────────────────────────────────────────────────────────────
README_WINDOWS_KIT.md has the full detail. Short version:
    pip install pywebview pyinstaller
    cd platform\desktop && python build_desktop.py
    → Inno Setup: compile installer\AscentTerminal.iss
    → upload both files to the server's platform/static/dl/
    → paste the SHA-256 into static/download.html
    (icon: export brand/app-icon-ios-1024.png to .ico for icon.ico)
Local dev on your PC (no batch files, no AV flags):
    python server_launcher\ascent_server.py --setup    (first time)
    python server_launcher\ascent_server.py            (after)

──────────────────────────────────────────────────────────────────
 §9  GO-LIVE CHECKS, THEN FIRE THE TWEET BOT
──────────────────────────────────────────────────────────────────
□ https://ascentterminal.com → landing page, padlock, new logo
□ /app unlocks with your architect key; /download renders
□ AI tab analyses + shows "n/100 analyses today"
□ BOTS tab: your two old bots present · ＋ ADD works · 4th bot on a
  fresh architect test key is refused with the add-on message
□ Picker: view tabs don't close it · ☆ stars persist · TREND tab live
□ Stripe test purchase → key by email → unlocks · cancel → key dead
□ TradingView test alert lands (with the new secret)
□ Discord #signals webhook set · forward service active
□ Whop/Patreon/Discord rebranded (REBRAND_COPY.md)
…then fire the thread (it's §5 of REBRAND_COPY.md) and open the doors.

Stuck anywhere → screenshot/paste the error and I'll fix it.
════════════════════════════════════════════════════════════════════

──────────────────────────────────────────────────────────────────
 §10  ADDED IN THE FINAL AUDIT (do with §1)
──────────────────────────────────────────────────────────────────
• PROXY FIX (in this build's Dockerfile): uvicorn now trusts Caddy's
  X-Forwarded-For — without it the brute-force lockout treated ALL
  visitors as one IP (one attacker could lock everyone out). Ships
  automatically with `docker compose up -d --build`.
• BACKUPS: platform/backup.sh tars keys.json + data/ + .env nightly.
    chmod +x /root/AscentTerminal/platform/backup.sh
    crontab -e   →   0 4 * * * /root/AscentTerminal/platform/backup.sh
  Copy /root/backups off the box weekly (scp/rclone) — keys.json IS
  your subscriber base; a dead disk must not be able to take it.
• MONITORING: free UptimeRobot monitor on
  https://ascentterminal.com/api/health (5-min checks, email alert) —
  know the site is down before a customer tells you.

──────────────────────────────────────────────────────────────────
 §11  CLOUDFLARE IN FRONT (free DDoS/WAF + hides the VPS, ~25 min)
──────────────────────────────────────────────────────────────────
Order matters — do the certificate BEFORE flipping the proxy on, and
the whole thing AFTER the site already works directly (§1–§2).

1. ACCOUNT + SITE: dash.cloudflare.com → Add a site →
   ascentterminal.com → Free plan. It imports your DNS records —
   confirm the two A records (@ and www → your VPS IP) are there,
   but set them to GREY cloud (DNS only) for now.
2. NAMESERVERS: at your registrar, replace the nameservers with the
   two Cloudflare gives you. Wait until CF emails "site is active"
   (minutes to a few hours). Site keeps working as before meanwhile.
3. ORIGIN CERTIFICATE (the 15-year cert Caddy will serve to CF):
   CF → SSL/TLS → Origin Server → Create Certificate → defaults
   (RSA, ascentterminal.com + *.ascentterminal.com, 15 years).
   Copy the two PEM blocks onto the server:
       nano /root/AscentTerminal/platform/certs/origin.pem      (cert)
       nano /root/AscentTerminal/platform/certs/origin-key.pem  (key)
4. SSL MODE: CF → SSL/TLS → Overview → set "Full (strict)".
   (Never "Flexible" — that causes redirect loops.)
5. SWITCH CADDY to the Cloudflare config:
       cd /root/AscentTerminal/platform
       cp Caddyfile Caddyfile.direct
       cp Caddyfile.cloudflare Caddyfile
       docker compose up -d --force-recreate
6. FLIP THE PROXY: CF → DNS → set @ and www to ORANGE cloud.
   https://ascentterminal.com should load with a Cloudflare-issued
   edge certificate (padlock → cert says Cloudflare/Google Trust).
7. CF SETTINGS THAT MATTER FOR THIS APP:
   • SSL/TLS → Edge Certificates → "Always Use HTTPS" = ON
   • Security → Bots → Bot Fight Mode = OFF  ← important: it can
     block Stripe/Whop/TradingView webhook POSTs (they're "bots").
     If you later want it on, first add a WAF skip rule:
     Security → WAF → Custom rules → "Skip" when URI Path is in
     {/api/tv-webhook, /api/stripe-webhook, /api/whop-webhook}.
   • Caching: leave defaults — /api/* responses aren't cached by CF
     (no cache headers), static assets get cached automatically.
8. VERIFY REAL-IP SECURITY STILL WORKS: from your PHONE on mobile
   data, enter a wrong key 10× → phone gets locked out (429) but the
   site keeps working on your desktop. If BOTH lock out, the proxy
   chain is misconfigured — check step 5 applied and re-run it.
9. Notes: SSH/scp still use the raw VPS IP (CF doesn't proxy port 22).
   The IP was public before today, so treat hiding it as best-effort;
   the firewall (ufw 22/80/443) is the real protection. The original
   direct config is kept as Caddyfile.direct — copying it back and
   grey-clouding DNS reverts everything.

──────────────────────────────────────────────────────────────────
 §12  ADDED SOLO (no action needed, just know it exists)
──────────────────────────────────────────────────────────────────
• /legal/terms, /legal/privacy, /legal/disclaimer now EXIST (the
  footer links were broken) — branded pages rendered from legal/*.md.
  Optional: independent legal review of the documents whenever convenient (review pack: AscentTerminal_legal_for_review.pdf).
• Social cards: brand/og-card.png + OG/Twitter meta on / and
  /download — your launch tweet now unfurls with a proper gold card.
  robots.txt + sitemap.xml are served too.
• TEST SUITE: before every future deploy, from platform/:
      pip install pytest httpx     (once)
      python -m pytest tests -q    → expect "12 passed"
• HANDOFF.md fully rewritten to the current build — replace the copy
  in your Claude project knowledge with this version.

──────────────────────────────────────────────────────────────────
 §13  PERSONAL DATA — encryption + automated GDPR (do with §2)
──────────────────────────────────────────────────────────────────
1. Generate the data-encryption key and add to .env on the server:
       python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
       → .env:  DATA_KEY=<that value>
   Then: docker compose up -d --build  (new dependency: cryptography)
   KEEP THIS KEY SAFE with your other secrets — losing it makes the
   stored (encrypted) addresses unreadable; that's the point.
2. What it does: every stored customer email (mailing list, billing
   references) is encrypted at rest; key notes and event logs carry
   anonymous tags instead of addresses; the owner mailing-list
   endpoint shows a COUNT only. You never see customer data.
3. Self-service page at /privacy-tools (linked in site footers and
   every key email): instant unsubscribe (+ permanent suppression),
   and right-to-erasure via emailed confirmation link — revokes keys,
   deletes billing refs + mailing entry, suppresses the address.
   Fully automated; no action from you, ever.
4. ICO registration (~£50/yr, ico.org.uk, 10 min) — you process
   Optional: independent legal review of the documents whenever convenient (review pack: AscentTerminal_legal_for_review.pdf).
5. Sending a mailout later (when you want to email the list): ask
   Claude for a send script — it decrypts addresses only in memory
   at send time via privacy.list_addresses().

──────────────────────────────────────────────────────────────────
 §14  TERMS ACCEPTANCE (already live in this build)
──────────────────────────────────────────────────────────────────
• Terminal: first unlock per device requires ticking "I agree to the
  Terms / Privacy / Disclaimer" on the lock screen; acceptance
  (version + timestamp, hashed key id only) is recorded server-side.
  Bumping TERMS_VERSION in app.py re-prompts everyone after a change.
• Stripe (§3): on each Payment Link ALSO enable "Require customers to
  accept your terms of service" with URL
  https://ascentterminal.com/legal/terms — that covers contractual
  acceptance at purchase, alongside the immediate-supply waiver box.
• Legal docs finalized: liability carve-outs, AI + experimental
  features, sanctions, transfers, general provisions; all contacts
  → support@ascentterminal.com (make sure that inbox forwards!).
  You also have sales@ (now on the landing footer — partnerships) and
  contact@ — make sure all three actually deliver somewhere you read.
  SMTP_FROM stays support@; never publish your personal mrobinson@..

──────────────────────────────────────────────────────────────────
 §15  tools\ — ONE-CLICK HELPERS (on your PC)
──────────────────────────────────────────────────────────────────
GENERATE_SECRETS.bat   make TV_WEBHOOK_SECRET / EXECUTE_KEY / DATA_KEY
NEW_KEY.bat            issue a subscriber key (prompts tier/days/note)
REVOKE_KEY.bat         revoke a key + show the list
RUN_TESTS.bat          pre-deploy test suite (expect "17 passed")
TEST_DISCORD_WEBHOOK.bat  prove a webhook works before using it
DEPLOY_TO_VPS.bat      safe upload + rebuild (edit your IP inside once;
                       never touches the server's .env/keys/data)

──────────────────────────────────────────────────────────────────
 §16  PER-USER ORDER CAPS (product change — know this)
──────────────────────────────────────────────────────────────────
The per-order cap now belongs to each USER, not to you: everyone with
operator+ sets "Your max per order" in the ⚡ Execute panel, and it
applies to ALL orders from their key — manual, bots, protective exits.
EXEC_MAX_USD in .env is now only an optional SERVER-WIDE ceiling
(abuse guard) that clamps everyone; set it to 0 for no ceiling, or a
high number (e.g. 50000) as a sanity bound. Users who never touch the
setting inherit the ceiling as their default.
