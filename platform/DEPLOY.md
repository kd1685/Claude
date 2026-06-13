# Deploying Ascent Terminal

This guide covers a production deploy on a single VPS (Ubuntu 22 +) using
Docker Compose + Caddy for automatic HTTPS.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| VPS with public IP | 1 vCPU / 1 GB RAM minimum |
| Domain name | Point an A-record at the VPS IP |
| Docker + Compose v2 | `apt install docker.io docker-compose-plugin` |
| Git | To clone the repo |

---

## 2. Clone & configure

```bash
git clone https://github.com/<you>/ascent-terminal.git
cd ascent-terminal/platform
cp .env.example .env
nano .env          # fill in at minimum: DOMAIN, DB_PASSWORD
```

Required env vars for a minimal working deploy:

```
DOMAIN=ascentterminal.com
DB_PASSWORD=<strong-random-string>
```

Optional but recommended:

```
TV_WEBHOOK_SECRET=   # protect TradingView inbound alerts
EXECUTION_SECRET=   # protect outbound order bridge
OPENAI_API_KEY=     # enable AI Analyst
ANTHROPIC_API_KEY=  # alternative AI provider
STRIPE_SECRET_KEY=  # enable subscription billing
```

---

## 3. Start the stack

```bash
docker compose up -d --build
```

Caddy automatically obtains a Let’s Encrypt certificate for `DOMAIN`.
Check progress:

```bash
docker compose logs -f caddy
docker compose logs -f app
```

Once the app container prints `Uvicorn running on http://0.0.0.0:8000` the
platform is live at `https://<DOMAIN>`.

---

## 4. Generate API keys

```bash
# Inside the running container
docker compose exec app python key_gen.py --tier operator --label "Alice"
```

Tiers: `scout` | `operator` | `architect`

The generated key is written to `keys.json` (persisted via Docker volume).

---

## 5. Cloudflare proxy (optional)

If your domain is orange-clouded through Cloudflare you need the DNS-01
challenge variant. See `Caddyfile.cloudflare` for instructions.

---

## 6. Backups

```bash
bash backup.sh          # dumps DB + keys.json to ./backups/
```

Schedule via cron:

```
0 3 * * * cd /opt/ascent && bash backup.sh
```

---

## 7. Updates

```bash
git pull
docker compose up -d --build
```

The Postgres volume is preserved across rebuilds.

---

## 8. Reverse-proxy / port reference

| Service | Internal port | Exposed externally |
|---|---|---|
| FastAPI app | 8000 | No (behind Caddy) |
| Caddy | 80 / 443 | Yes |
| Postgres | 5432 | No |

---

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `502 Bad Gateway` | App container still starting; wait 10 s |
| Caddy cert error | A-record not yet propagated; check `dig` |
| DB connection refused | Wrong `DB_PASSWORD` or volume permissions |
| Webhook `403 Forbidden` | `TV_WEBHOOK_SECRET` mismatch |
