# 2. Put it online on a VPS (with login)

**One box does everything** — no GitHub/Netlify needed. The same VPS serves the
**website**, the **API**, the **database**, and runs the **bot** (an Android
emulator the controller drives). Caddy puts it all on **one URL**:

```
https://rok.example.com/            ← public data pages
https://rok.example.com/control.html ← officers (login)
https://rok.example.com/api/...      ← API (same origin, no CORS needed)
```

### You need
- A Linux VPS where **you control the kernel** — bare-metal or a KVM VPS, *not*
  OpenVZ/LXC. 2 vCPU / 4 GB RAM is comfortable. (This kernel requirement is only
  for the Android emulator/bot; the website+API run anywhere.)
- Docker + the compose plugin:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ```
- (Recommended) a domain, e.g. `rok.example.com`, with an **A record** to your
  VPS IP — enables automatic HTTPS.

### Step 0 — preflight: can this VPS run the bot?
```bash
bash deploy/preflight.sh
```
- **All ✓** → great, the bot (Android emulator) will run here; continue below.
- **"no binder support"** → the website/API will still run, but the emulator
  won't. See **[3-CONNECT-GAME.md](3-CONNECT-GAME.md) → "If the emulator won't
  run on your VPS"** for alternatives (KVM host, or point ADB at a real phone).

### Easiest: one command on a fresh VPS
```bash
git clone <your-repo-url> rok1685 && cd rok1685
sudo bash deploy/activate.sh
```
This installs **Docker**, sets up the **firewall** (allows only SSH/80/443), runs
the **preflight**, asks for your domain + admin login, writes `deploy/.env`
(generating the session secret), and **starts everything**. When it finishes,
skip to **Step 4 — open it**, then do **[3-CONNECT-GAME.md](3-CONNECT-GAME.md)**.

> Already have Docker installed? You can run `bash deploy/setup.sh` instead — it
> does everything except install Docker / configure the firewall.

Prefer to do each step by hand? Continue below.

### Step 1 — get the code
```bash
git clone <your-repo-url> rok1685
cd rok1685
```

### Step 2 — write your settings
Create `deploy/.env`:
```bash
cat > deploy/.env <<EOF
# Public address. A domain -> automatic HTTPS. Remove this line for plain http on :80.
SITE_ADDRESS=rok.example.com

# First admin login (change these!)
ADMIN_USERNAME=yourname
ADMIN_PASSWORD=use-a-strong-password

# Keeps logins working across restarts
CONTROL_SECRET=$(openssl rand -hex 32)

# true only if you set a domain above (HTTPS)
COOKIE_SECURE=true
EOF
```

### Step 3 — start everything
```bash
docker compose -f deploy/docker-compose.yml up -d
```
This launches three containers:
- **android** — a headless Android (redroid) for the game,
- **app** — the tracker + website,
- **caddy** — the public web server (HTTPS).

### Step 4 — open it
- With a domain: **https://rok.example.com**
- Without: **http://YOUR_VPS_IP**

Log in to **Control** with the `ADMIN_USERNAME` / `ADMIN_PASSWORD` you set.

### Step 5 — add your officers
On the Control page (as admin) → **Officers** panel → add each officer with a
temporary password. They'll be forced to set their own password on first login.

> At this point the data is still empty and the controller has no game to drive
> yet. Continue to **[3-CONNECT-GAME.md](3-CONNECT-GAME.md)**.

### Handy commands
```bash
bash deploy/update.sh                                      # pull latest code + restart
docker compose -f deploy/docker-compose.yml logs -f app    # watch app logs
docker compose -f deploy/docker-compose.yml restart app    # restart app
docker compose -f deploy/docker-compose.yml down           # stop everything
```
Your data and `deploy/.env` survive updates (they're in Docker volumes / gitignored).
