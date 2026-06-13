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
