════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — UPDATE NOTES
════════════════════════════════════════════════════════════════════
Version: launch-build · Date: 2026-06-12

This document explains every change made in this update so you know
exactly what landed and why.  It also doubles as a reference for the
things you still need to do before going live.

────────────────────────────────────────────────────────────────────
 §1  WHAT CHANGED IN THIS UPDATE
────────────────────────────────────────────────────────────────────

1.1  platform/routes/stripe.py  — full Stripe integration
     • /api/stripe/checkout  creates a Checkout Session (monthly or yearly)
     • /api/stripe/webhook   handles completed checkout, subscription
       updates/deletions, and failed payments
     • Subscription row in DB is created/updated/cancelled automatically
     • 7-day grace period on failed payments before access is revoked

1.2  platform/routes/auth.py  — registration + login hardened
     • Passwords hashed with bcrypt (passlib)
     • JWT access token stored in HttpOnly cookie (30-day expiry)
     • /register now sends a welcome email via platform/alerts.py
     • Rate-limit stub added (plug in slowapi if you want hard limits)

1.3  platform/routes/dashboard.py  — live data feed
     • WebSocket endpoint /ws/prices streams MEXC ticker prices
     • REST endpoint /api/portfolio returns current open positions
     • Subscription-gating middleware applied — 402 if not subscribed

1.4  platform/routes/admin.py  — owner panel
     • /admin/health  — status of DB, bots, Stripe webhook, MEXC WS
     • /admin/users   — paginated user list with subscription status
     • /admin/toggle-bot  — start/stop bots without restarting Docker
     • Protected by ADMIN_EMAIL env var + separate admin JWT claim

1.5  platform/routes/referral.py  — referral system
     • Every user gets a unique /ref/<code> link on registration
     • Referrer earns a 1-month credit when referee converts to paid
     • Credits applied automatically at next billing cycle via Stripe
       customer balance
     • Enable with REFERRAL_ENABLED=true in .env

1.6  platform/alerts.py  — email + webhook alerting
     • Sends email on: new registration, subscription start/cancel,
       failed payment, bot error, daily P&L summary
     • Optional Discord/Slack webhook: set ALERT_WEBHOOK_URL in .env
     • All sends are fire-and-forget (asyncio.create_task) so they
       never block a request

1.7  bots/scalper_bot.py  — headless mode added
     • Pass --headless on the command line to run without PyQt5
     • Server uses headless mode; GUI still works on Windows
     • Position sizing now respects MAX_POSITION_USDT env var

1.8  brain/mexc_trend_bot.py  — owner research tool updated
     • EMA crossover logic cleaned up
     • CSV export of daily signals added
     • Not deployed to the VPS — runs locally on Windows only

────────────────────────────────────────────────────────────────────
 §2  NGINX CONFIG (paste into /etc/nginx/sites-available/ascent)
────────────────────────────────────────────────────────────────────

    server {
        listen 80;
        server_name your-domain.com www.your-domain.com;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        server_name your-domain.com www.your-domain.com;

        ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
        include /etc/letsencrypt/options-ssl-nginx.conf;
        ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

        location / {
            proxy_pass         http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_set_header   Host $host;
            proxy_set_header   X-Real-IP $remote_addr;
            proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto $scheme;
        }
    }

────────────────────────────────────────────────────────────────────
 §3  STRIPE SETUP (do tomorrow)
────────────────────────────────────────────────────────────────────

3.1  Install Stripe CLI (Windows):
     winget install Stripe.StripeCLI
     stripe login

3.2  Create products:
     stripe products create --name "Ascent Terminal Monthly"
     stripe prices create --product <id> --unit-amount 2900 --currency usd \
         --recurring-interval month

     stripe products create --name "Ascent Terminal Yearly"
     stripe prices create --product <id> --unit-amount 24900 --currency usd \
         --recurring-interval year

3.3  Copy the price IDs into platform/.env on the VPS:
     STRIPE_PRICE_MONTHLY=price_xxxx
     STRIPE_PRICE_YEARLY=price_yyyy

3.4  Register webhook:
     stripe webhooks create \
         --url https://your-domain.com/api/stripe/webhook \
         --events checkout.session.completed,customer.subscription.updated,customer.subscription.deleted,invoice.payment_failed

     Copy the signing secret → STRIPE_WEBHOOK_SECRET=whsec_…

3.5  Test end-to-end:
     stripe listen --forward-to localhost:8000/api/stripe/webhook
     stripe trigger checkout.session.completed

────────────────────────────────────────────────────────────────────
 §4  ENVIRONMENT VARIABLES REFERENCE
────────────────────────────────────────────────────────────────────

  SECRET_KEY              random 32-char hex (generate: openssl rand -hex 32)
  DATABASE_URL            sqlite:///./data/ascent.db
  STRIPE_SECRET_KEY       sk_live_… (or sk_test_… while testing)
  STRIPE_PUBLISHABLE_KEY  pk_live_…
  STRIPE_PRICE_MONTHLY    price_…
  STRIPE_PRICE_YEARLY     price_…
  STRIPE_WEBHOOK_SECRET   whsec_…
  MEXC_API_KEY            from MEXC → API Management
  MEXC_API_SECRET         from MEXC → API Management
  ADMIN_EMAIL             your login email for /admin routes
  SMTP_HOST               e.g. smtp.mailgun.org
  SMTP_USER               SMTP username
  SMTP_PASS               SMTP password
  ALERT_WEBHOOK_URL       Discord/Slack webhook (optional)
  REFERRAL_ENABLED        true / false  (default false)
  PAYMENTS_LIVE           true / false  (default false)
  MAX_POSITION_USDT       max notional per scalper trade (default 100)

════════════════════════════════════════════════════════════════════
