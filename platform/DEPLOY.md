# Deploy Guide (Beginner-Friendly)

This guide takes you from a brand-new Ubuntu server to a live, secure
(`https://`) website with **copy-paste commands**. You do not need to know
Docker. Just follow the steps in order.

What you need before you start:

- A small Linux **VPS running Ubuntu** (e.g. from DigitalOcean, Hetzner, Linode,
  Vultr). 1 GB RAM is plenty.
- The VPS's **public IP address** (your provider shows this on the dashboard).
- A **domain name** you own (e.g. `yourdomain.com`).
- A way to log into the server (your provider gives you SSH access, usually
  `ssh root@YOUR_SERVER_IP`).

Throughout this guide, replace:

- `app.yourdomain.com` with the address you actually want to use.
- `YOUR_SERVER_IP` with your VPS's public IP address.

---

## Step 1 — Point your domain at the server (DNS)

1. Log into wherever you bought your domain (e.g. Namecheap, GoDaddy,
   Cloudflare).
2. Find the **DNS settings** for your domain.
3. Add a new **A record**:
   - **Type:** `A`
   - **Name / Host:** `app` (this creates `app.yourdomain.com`).
     If you want to use the bare domain instead, use `@`.
   - **Value / Points to:** `YOUR_SERVER_IP`
   - **TTL:** leave default (or "Automatic").
4. Save. DNS can take a few minutes (sometimes up to an hour) to spread across
   the internet. You can move on to the next steps while you wait.

> Tip: from your own computer you can check it's working with
> `ping app.yourdomain.com` — it should show YOUR_SERVER_IP.

---

## Step 2 — Log into your server

From your own computer's terminal:

```bash
ssh root@YOUR_SERVER_IP
```

(Type `yes` if asked about the fingerprint, then enter your password.)

All the remaining commands are run **on the server** (in that SSH session).

---

## Step 3 — Install Docker

Docker is the tool that runs the app. Install it with the official one-liner:

```bash
curl -fsSL https://get.docker.com | sh
```

This also installs **Docker Compose v2** (the `docker compose` command — note the
space, not a hyphen). You do not need to install anything else.

Verify it worked:

```bash
docker --version
docker compose version
```

Both commands should print a version number.

---

## Step 4 — Open the firewall (ports 80 and 443)

Websites use port **80** (http) and **443** (https). Allow them through the
firewall. Ubuntu uses `ufw`:

```bash
ufw allow 80,443/tcp
ufw allow OpenSSH
ufw --force enable
```

> The `ufw allow OpenSSH` line keeps your SSH login working — don't skip it, or
> you could lock yourself out.

---

## Step 5 — Get the app onto the server

Put the `platform/` folder onto the server. Pick **one** of the two options.

**Option A — using git** (if your code is in a git repository):

```bash
git clone YOUR_REPO_URL platform
cd platform
```

**Option B — uploading from your computer with `scp`**

Run this on **your own computer** (not the server), from the folder that
contains `platform/`:

```bash
scp -r platform root@YOUR_SERVER_IP:/root/platform
```

Then back **on the server**:

```bash
cd /root/platform
```

---

## Step 6 — Create and edit your settings file

The app reads its secrets from a file called `.env`. Create it from the template:

```bash
cp .env.example .env
nano .env
```

`nano` is a simple text editor. Edit these values:

- `DOMAIN=ascentterminal.com` — the exact address from Step 1 (bare domain or
  subdomain — whatever your A record points at).
- `ACCESS_KEYS=` — leave **EMPTY** in production (this kills DEMO-KEY).
  Subscriber keys live in `keys.json` now — see "Issuing subscriber keys"
  below. (Anything you DO put here acts as an owner master key.)
- `TV_WEBHOOK_SECRET=` — long random string; protects the TradingView
  alert receiver.
- `EXECUTE_KEY=` — long random string that arms order execution + bots.
  Leave EMPTY until you actually want trading possible. `EXEC_LIVE=false`
  stays false until you've paper-tested.
- `ANTHROPIC_API_KEY=` — optional; enables the "Claude's read" AI panel.
- `DISCORD_WEBHOOK_URL=` — optional Discord notifications.
- `EXCHANGE=mexc` — leave as is unless you want a different default.

To save in `nano`: press `Ctrl+O`, then `Enter`, then `Ctrl+X` to exit.

---

### Create the subscriber-key file (one-time, before first start)

The app stores subscriber keys (hashed) in `keys.json`, mounted into the
container so you can manage keys from the host with **no restarts**:

```bash
cd ~/AscentTerminal/platform
python3 key_gen.py new --tier architect --note "owner"
```

Copy the key it prints — that's your own login. (If `python3` is missing:
`apt install -y python3`.)

---

## Step 7 — Start everything

```bash
docker compose up -d --build
```

- `--build` builds your app into a container the first time.
- `-d` runs it in the background so it keeps running after you log out.

The first build takes a minute or two. When it finishes, the app and the Caddy
web server (which handles HTTPS automatically) are both running.

---

## Step 8 — Verify it's live

Open a browser and visit:

```
https://app.yourdomain.com
```

The first time, Caddy automatically requests a free HTTPS certificate from
Let's Encrypt. This usually takes about **30 seconds**. If you see a security
warning at first, wait half a minute and refresh — once the certificate is
issued you'll get the secure padlock.

You should see your dashboard. That's it — you're live!

---

## Everyday operations

Run these from inside the `platform/` folder on the server.

**See the app's live logs** (press `Ctrl+C` to stop watching):

```bash
docker compose logs -f web
```

**See Caddy / HTTPS logs** (useful if the certificate isn't issuing):

```bash
docker compose logs -f caddy
```

**Update to a new version of your code:**

```bash
git pull
docker compose up -d --build
```

(If you uploaded with `scp` instead of git, re-run the `scp` command from Step 5,
then `docker compose up -d --build`.)

**Restart everything:**

```bash
docker compose restart
```

**Stop everything** (the site goes offline):

```bash
docker compose down
```

**Start it again later:**

```bash
docker compose up -d
```

**Change a setting** (e.g. add a subscriber key): edit `.env` with
`nano .env`, then apply it:

```bash
docker compose up -d
```

---

## Troubleshooting

**The HTTPS certificate isn't being issued / browser shows "not secure".**

- DNS may not have spread yet. Run `ping app.yourdomain.com` from your computer
  and confirm it shows `YOUR_SERVER_IP`. If not, wait and try again.
- Make sure ports 80 and 443 are open (Step 4). Caddy needs port **80** open to
  prove it owns the domain — if it's blocked, no certificate is issued.
- Check Caddy's logs: `docker compose logs -f caddy`. Look for messages about
  "certificate obtained" (good) or DNS/connection errors.
- Confirm `DOMAIN` in your `.env` exactly matches the address you're visiting.

**The page won't load at all.**

- Check the app logs: `docker compose logs -f web`. Errors there usually point
  to the cause.
- Make sure the containers are running: `docker compose ps`. Both `web` and
  `caddy` should show as running/up.

**Signals show "401 Unauthorized" or won't unlock.**

- This is **expected** without a valid access key. Keys are managed with
  `key_gen.py` (see below) and take effect instantly — if a subscriber can't
  get in, run `python3 key_gen.py list` and check their key isn't revoked or
  expired. Ten failed attempts locks an IP out for 15 minutes (HTTP 429) —
  that's the brute-force shield working.

**I edited `.env` but nothing changed.**

- You must re-apply it: `docker compose up -d` (it recreates the containers with
  the new values). `keys.json` is the exception — key changes are picked up
  live with no restart.

---

## Issuing subscriber keys in production

All on the server, from `~/AscentTerminal/platform` — changes are live
within a second, **no restart ever needed**:

```bash
python3 key_gen.py new --tier observer  --days 31 --note "whop order 123"
python3 key_gen.py new --tier operator  --days 31 --note "patron @alice"
python3 key_gen.py new --tier architect --days 31 --note "vip @bob"
python3 key_gen.py list
python3 key_gen.py revoke --key XXXXX-XXXXX-XXXXX-XXXXX
```

Tiers: observer = signals/charts/analysis · operator = + backtest +
execution bridge · architect = + bots. Keys are stored **hashed** — the
plaintext is shown once at creation, so copy it then.

---

## Updating the live server (new code version)

From your own computer, upload the changed project (same `scp` as Step 5),
then on the server:

```bash
cd ~/AscentTerminal/platform
docker compose up -d --build
```

Your `.env`, `keys.json` and `data/` (alerts, execution log, bot state)
are kept — they live outside the container. Bots come back **stopped**
after any restart by design; re-arm them from the BOTS tab.
