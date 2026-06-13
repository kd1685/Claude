════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — GO-LIVE STEPS (final pass · do in order)
════════════════════════════════════════════════════════════════════
This zip is CODE ONLY — your live .env, keys.json and data/ are never
overwritten. Times are realistic. §3 (Stripe) is the one you said
you're doing tomorrow; everything else can be done today.

──────────────────────────────────────────────────────────────────
 §1  UPLOAD THE UPDATE TO THE VPS (10 min)
──────────────────────────────────────────────────────────────────

1.  On your Windows machine, unzip this archive:

        ascent_terminal_final.zip  →  ascent_terminal_final/

2.  Open WinSCP (or FileZilla) and connect to your VPS.

3.  Upload the CONTENTS of ascent_terminal_final/ into the root of
    your existing project folder on the VPS, e.g.

        /root/ascent_terminal/      ← your live folder

    Choose "overwrite" when prompted.  Your .env, keys.json and
    platform/data/ are in .gitignore and will NOT be in the zip, so
    they are safe.

4.  Alternatively, use the Windows batch file UPDATE.bat:
    – edit the three variables at the top (HOST / USER / REMOTE_PATH)
    – double-click it; it calls rsync via WSL or scp

──────────────────────────────────────────────────────────────────
 §2  RESTART THE SERVICES ON THE VPS (5 min)
──────────────────────────────────────────────────────────────────

SSH into the VPS, then:

    cd /root/ascent_terminal          # or wherever your folder lives

    # if you use Docker Compose:
    docker compose pull               # optional – only if images changed
    docker compose down
    docker compose up -d --build

    # if you run without Docker (plain Python / gunicorn / uvicorn):
    pkill -f "gunicorn\|uvicorn\|python.*main"
    source venv/bin/activate
    pip install -r requirements.txt   # picks up any new packages
    gunicorn -w 2 -b 0.0.0.0:8000 platform.main:app &

Check it's alive:

    curl http://localhost:8000/health    # should return {"status":"ok"}

──────────────────────────────────────────────────────────────────
 §3  WIRE UP STRIPE  (do tomorrow — 30 min)
──────────────────────────────────────────────────────────────────

This is the only part that touches money, so take it slowly.

3-a.  Create the products & prices in your Stripe dashboard
      (or use the Stripe CLI — see UPDATE_NOTES.md §3).

3-b.  Copy the price IDs into platform/.env:

        STRIPE_PRICE_MONTHLY=price_xxxx
        STRIPE_PRICE_YEARLY=price_yyyy
        STRIPE_WEBHOOK_SECRET=whsec_xxxx

3-c.  In the Stripe dashboard → Developers → Webhooks, add an
      endpoint:

        https://your-domain.com/api/stripe/webhook

      Events to forward:
        checkout.session.completed
        customer.subscription.updated
        customer.subscription.deleted
        invoice.payment_failed

3-d.  Test with the Stripe CLI:

        stripe listen --forward-to localhost:8000/api/stripe/webhook
        stripe trigger checkout.session.completed

      Confirm the terminal logs show "subscription activated".

3-e.  Flip the "coming soon" flag off in platform/.env:

        PAYMENTS_LIVE=true

      Restart the service (§2 above).

──────────────────────────────────────────────────────────────────
 §4  SMOKE-TEST THE LIVE SITE (10 min)
──────────────────────────────────────────────────────────────────

Open https://your-domain.com and check:

  [ ] Home page loads, no 500 errors in logs
  [ ] /login and /register work
  [ ] Dashboard visible after login
  [ ] At least one bot card shows a live price (WebSocket feeds up)
  [ ] /admin/health returns green for every service

──────────────────────────────────────────────────────────────────
 §5  OPTIONAL EXTRAS (do whenever)
──────────────────────────────────────────────────────────────────

  • Referral system  – already coded; enable with REFERRAL_ENABLED=true
    in .env, then share /ref/<your-code> links.

  • Email alerts     – set SMTP_HOST / SMTP_USER / SMTP_PASS in .env;
    the alert mailer in platform/alerts.py will pick them up.

  • SSL / custom domain – point your DNS A-record to the VPS IP, then
    run:  certbot --nginx -d your-domain.com

════════════════════════════════════════════════════════════════════
 That's it.  Good luck with the launch!
════════════════════════════════════════════════════════════════════
