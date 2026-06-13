# GO LIVE STEPS — Ascent Terminal

Copy this file somewhere safe. Work through it top-to-bottom before you open the
doors.

---

## 0 · Before you start

| What | Where |
|------|-------|
| VPS (Ubuntu 22 LTS, 2 vCPU / 4 GB min) | Hetzner / DigitalOcean / Vultr |
| Domain pointing to VPS IP | Cloudflare (proxy **off** for first TLS cert, turn on after) |
| Stripe account (live mode) | stripe.com |
| Whop listing ready | whop.com |
| Discord server | discord.com |

---

## 1 · Server setup

```bash
# SSH into fresh VPS
ssh root@YOUR_VPS_IP

# Run the one-shot setup
bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/main/platform/deploy/setup.sh)
```

Or manually:

```bash
apt update && apt upgrade -y
apt install -y docker.io docker-compose git
git clone https://github.com/YOUR_REPO.git /root/AscentTerminal
cd /root/AscentTerminal/platform
cp .env.example .env
```

---

## 2 · Fill in .env

Open `/root/AscentTerminal/platform/.env` and set every value.  
See `.env.example` for descriptions.  Critical ones:

```
SECRET_KEY=          # python -c "import secrets; print(secrets.token_hex(32))"
WHOP_CLIENT_ID=      # from Whop dashboard → Developer → OAuth
WHOP_CLIENT_SECRET=  # same place
STRIPE_SECRET_KEY=   # Stripe dashboard → API keys → Secret (live)
STRIPE_WEBHOOK_SECRET= # after step 5
DISCORD_WEBHOOK_URL= # Discord channel → Edit → Integrations → Webhooks
```

---

## 3 · Generate API keys file

```bash
cd /root/AscentTerminal
python3 platform/key_gen.py --init
```

This creates `platform/keys.json`. Back it up immediately.

---

## 4 · DNS

In Cloudflare (or your DNS provider) add an **A record**:

```
ascentterminal.com  →  YOUR_VPS_IP
```

If using a subdomain for the platform (e.g. `app.ascentterminal.com`) add that too.

Wait for propagation (~1-5 min with Cloudflare).

---

## 5 · First run (HTTP only, get TLS cert)

```bash
cd /root/AscentTerminal/platform
# Edit Caddyfile — replace YOUR_DOMAIN with ascentterminal.com
nano Caddyfile

docker compose up -d
```

Caddy will auto-obtain a Let's Encrypt certificate.  
Check: `docker compose logs caddy -f`  
You should see `certificate obtained successfully`.

---

## 6 · Stripe webhook

In Stripe dashboard → Developers → Webhooks → Add endpoint:

```
https://ascentterminal.com/billing/webhook
```

Events to listen for:
- `checkout.session.completed`
- `customer.subscription.deleted`
- `customer.subscription.updated`
- `invoice.payment_failed`

Copy the **Signing secret** → paste into `.env` as `STRIPE_WEBHOOK_SECRET`  
Then restart: `docker compose restart app`

---

## 7 · Whop OAuth

In Whop dashboard → Your product → Developer:

- Redirect URI: `https://ascentterminal.com/auth/whop/callback`
- Scopes: `openid email profile memberships`

Paste Client ID + Secret into `.env`.

---

## 8 · Smoke test

```bash
cd /root/AscentTerminal
python3 -m pytest platform/tests/ -v
```

All green? Visit https://ascentterminal.com — you should see the landing page.

---

## 9 · Create first admin key

```bash
python3 platform/key_gen.py --create --tier architect --note "founder"
```

Log in with that key to confirm the terminal loads.

---

## 10 · Discord alerts

```bash
python3 discord/add_alerts_channel.py
```

Follow the prompts. Post a test alert to confirm it lands in your channel.

---

## 11 · Open the doors

- [ ] Flip Stripe payment links from test → live in `platform/static/landing.html`
- [ ] Publish Whop listing
- [ ] Announce on X / Discord
- [ ] Celebrate 🎉

---

## Ongoing

| Task | Command |
|------|---------|
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Update code | `git pull && docker compose up -d --build` |
| Backup keys | `cp platform/keys.json ~/keys_backup_$(date +%Y%m%d).json` |
| Run tests | `python3 -m pytest platform/tests/ -v` |
