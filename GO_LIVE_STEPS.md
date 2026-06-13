# GO LIVE STEPS — Ascent Terminal

> Last updated: June 2025  
> Status: READY TO LAUNCH

---

## 0 · Pre-flight checklist (do once)

| # | Task | Done? |
|---|------|---------|
| 1 | Buy / point domain `ascent-terminal.com` to your VPS IP | ☐ |
| 2 | Spin up VPS (Ubuntu 22 LTS, 2 vCPU / 4 GB RAM minimum) | ☐ |
| 3 | SSH in, run `sudo apt update && sudo apt install -y python3-pip nginx certbot python3-certbot-nginx git` | ☐ |
| 4 | Clone this repo to `/opt/ascent` | ☐ |
| 5 | `cp .env.example .env` and fill every value (see §1 below) | ☐ |
| 6 | `pip3 install -r requirements.txt` | ☐ |
| 7 | Run `tools/GENERATE_SECRETS.bat` (Windows) **or** `python3 tools/generate_secrets.py` on VPS to create `platform/keys.json` | ☐ |
| 8 | Configure Nginx reverse-proxy (see §2) | ☐ |
| 9 | Obtain TLS cert: `sudo certbot --nginx -d ascent-terminal.com` | ☐ |
| 10 | Install systemd service (see §3) | ☐ |
| 11 | Connect Stripe webhook (see §4) | ☐ |
| 12 | Invite Discord bot, run role-sync (see §5) | ☐ |
| 13 | Smoke-test end-to-end (see §6) | ☐ |
| 14 | Flip Whop / Patreon listings to **Live** | ☐ |

---

## 1 · Environment variables (`.env`)

```
# ── Server ──────────────────────────────────────────────
SECRET_KEY=<random 64-char hex>          # flask session signing
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
DEBUG=false

# ── MEXC ────────────────────────────────────────────────
MEXC_API_KEY=<your key>
MEXC_SECRET_KEY=<your secret>

# ── Discord ─────────────────────────────────────────────
DISCORD_BOT_TOKEN=<bot token>
DISCORD_GUILD_ID=<your server ID>
DISCORD_WEBHOOK_URL=<#alerts channel webhook>
DISCORD_ALERT_ROLE_ID=<role to ping>

# ── Stripe ──────────────────────────────────────────────
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_MONTHLY=price_...
STRIPE_PRICE_ID_ANNUAL=price_...

# ── Whop ────────────────────────────────────────────────
WHOP_API_KEY=<whop bearer token>
WHOP_PRODUCT_ID=<prod_...>

# ── Patreon ─────────────────────────────────────────────
PATREON_ACCESS_TOKEN=<creator access token>
PATREON_CAMPAIGN_ID=<campaign id>
```

---

## 2 · Nginx config

Create `/etc/nginx/sites-available/ascent` with:

```nginx
server {
    listen 80;
    server_name ascent-terminal.com www.ascent-terminal.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Then:
```bash
sudo ln -s /etc/nginx/sites-available/ascent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 3 · Systemd service

```bash
sudo cp forward/ascent-forward.service /etc/systemd/system/ascent.service
# Edit the file: set User= and WorkingDirectory= to match your VPS paths
sudo systemctl daemon-reload
sudo systemctl enable ascent
sudo systemctl start ascent
sudo systemctl status ascent
```

---

## 4 · Stripe webhook

1. Go to **Stripe Dashboard → Developers → Webhooks → Add endpoint**
2. URL: `https://ascent-terminal.com/webhook/stripe`
3. Events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
4. Copy the **Signing secret** → paste as `STRIPE_WEBHOOK_SECRET` in `.env`
5. Restart the service: `sudo systemctl restart ascent`

---

## 5 · Discord role-sync

```bash
# On your Windows dev machine:
discord\role_sync_setup.bat

# Or on VPS:
pip3 install discord.py
python3 discord/discord_role_sync.py
```

The bot needs these permissions in your server:
- Manage Roles
- Read Messages / Send Messages
- View Audit Log

---

## 6 · Smoke tests

### 6a — API health
```bash
curl https://ascent-terminal.com/api/health
# Expected: {"status": "ok", "version": "1.0.0"}
```

### 6b — Paper-trade forward test (5 min)
```bash
python3 forward/forward_paper.py --symbol BTCUSDT --minutes 5
```
Expected output: no exceptions, prints at least one signal line.

### 6c — Discord webhook
```bash
tools\TEST_DISCORD_WEBHOOK.bat
```
Expected: test message appears in #alerts.

### 6d — Stripe test checkout
1. Open `https://ascent-terminal.com/subscribe`
2. Use Stripe test card `4242 4242 4242 4242`
3. Complete checkout → confirm webhook fires (check server logs)
4. Confirm Discord role assigned

### 6e — Key generation
```bash
tools\NEW_KEY.bat
# or
python3 tools/new_key.py
```
Expected: prints a new UUID licence key, writes to `platform/keys.json`.

---

## 7 · Post-launch

- [ ] Enable Whop listing (copy from `whop_patreon/whop_ai_prompts.md`)
- [ ] Enable Patreon tiers (copy from `whop_patreon/patreon_setup_prompts.md`)
- [ ] Schedule weekly Discord posts (`discord/discord_post_content.py`)
- [ ] Monitor VPS memory: `htop` or set up Datadog/UptimeRobot
- [ ] Review `UPDATE_NOTES.md` before each release

---

## 8 · Emergency rollback

```bash
cd /opt/ascent
git log --oneline -10        # find the last good commit
git checkout <commit-hash>
sudo systemctl restart ascent
```

---

*Questions? See `HANDOFF.md` for architecture overview, or open a GitHub issue.*
