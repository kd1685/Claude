# 2. Put it online on a VPS (with login)

This gets the website live on the internet: **public data pages**, a
**password-protected Control page**, and an Android instance the controller can
drive. Everything runs in Docker.

### You need
- A Linux VPS (Ubuntu works well). 2 vCPU / 4 GB RAM is comfortable.
- Docker + the compose plugin installed:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ```
- (Optional but recommended) a domain name, e.g. `rok.example.com`, with an
  **A record** pointing at your VPS IP. Needed for automatic HTTPS.

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
docker compose -f deploy/docker-compose.yml logs -f app    # watch app logs
docker compose -f deploy/docker-compose.yml restart app    # restart app
docker compose -f deploy/docker-compose.yml down           # stop everything
```
