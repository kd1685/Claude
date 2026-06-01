# Rise of Kingdoms — Kingdom  Tracker & Controller

A self-hosted command center for a Rise of Kingdoms kingdom. It does two jobs:

1. **Tracks in-game data over time** — power, kill points, dead troops, rallies
   and map positions per governor — by *scanning the in-game rankings*.
2. **Controls a RoK account** to act on the kingdom: grant **titles**
   (Justice / Duke / Architect / Scientist), change **alliance ranks** (R1–R5)
   and **locate governors** on the map — by driving a real client over ADB.

On top of that sits the **Kingdom  website**: a dashboard plus dedicated
pages for Power/KP, Dead troops, Rallies, Governors and the Map — every page
has **date selectors** (and date-range gains) so you can review any day's
standings.

> RoK has no public API, so the controller drives the game UI by tapping screen
> coordinates and reads the rankings with OCR. It is designed to run **headless
> on a VPS** against an Android emulator. It ships with a **mock backend** so
> the whole app runs and the website is fully populated *without* a device.

---

## Quick start (no device — mock backend)

```bash
pip install -r requirements.txt
./run.sh --seed          # seeds 24 governors × 30 days of demo data, then serves
# open http://localhost:8000
```

That's it — the dashboard, KP, Dead, Rallies, Governors and Map pages are all
populated, and the **Control** page works against the simulated client (titles,
ranks, locate and scans flow through the real command queue).

Run the tests:

```bash
pip install pytest httpx
pytest -q
```

---

## Architecture

```
┌──────────────┐   HTTP    ┌───────────────────────────┐
│  Website     │ ───────▶  │  FastAPI app (app/)        │
│  (web/, JS)  │           │   • /api/stats  date-filtered leaderboards/totals
└──────────────┘           │   • /api/players /scans /rallies /map
                           │   • /api/control  → command queue
                           │  SQLite (data/rok1685.db)
                           │  Background worker drains the queue one cmd at a time
                           └──────────────┬────────────┘
                                          │ AccountAdapter
                            ┌─────────────┴─────────────┐
                            │ MockAdapter   AdbAdapter   │
                            │ (simulated)   (real ADB) ──┼──▶ Android emulator
                            └────────────────────────────┘     running RoK
```

* **Adapters** (`app/control/`) implement one interface: `give_title`,
  `change_rank`, `locate`, `scan_rankings`. Swapping `mock` ↔ `adb` changes
  nothing else in the app.
* **UI profile** (`app/profiles/rok_720p.json`) holds every tap coordinate, OCR
  region and macro, so adapting to a new resolution is JSON editing, not code.
* **Command queue** — the API enqueues; the worker executes serially (a single
  client can only do one thing at a time) and records result/error per command.

### Key directories
| Path | What |
|------|------|
| `app/main.py` | FastAPI app; serves the API and the website |
| `app/api/` | route handlers (`stats`, `players`, `scans`, `control`, `mapdata`, `rallies`) |
| `app/control/` | adapters, macro engine, OCR scanner, actions, worker |
| `app/profiles/` | calibration profiles (tap coords + OCR regions) |
| `web/` | the Kingdom 1685 website (static HTML/CSS/JS, Chart.js) |
| `scripts/seed.py` | demo data; `scripts/calibrate.py` | calibration helper |
| `deploy/` | Dockerfile, docker-compose (redroid + app), systemd unit |

---

## Running live on a VPS (real RoK client)

The controller needs an Android instance running RoK that `adb` can reach. The
easiest fully-headless option is **redroid** (Android in Docker).

### 1. Bring up Android + the app
```bash
docker compose -f deploy/docker-compose.yml up -d
```
This starts a 1280×720 redroid Android (`android:5555`) and the app with
`CONTROL_BACKEND=adb`.

### 2. Install & log in to RoK (once)
Install the RoK APK into the redroid instance and log into the **controlling
account** (the account that will grant titles / manage ranks — it needs the
in-game permissions for those actions, e.g. be the king or an R4/R5):
```bash
docker compose exec app adb -s android:5555 install /path/to/rok.apk
# then open the game and log in (use scrcpy from your workstation to view/interact)
```

### 3. Calibrate the UI profile
Coordinates differ per build/skin, so calibrate once:
```bash
docker compose exec app python -m scripts.calibrate screenshot   # saves captures/calibrate.png
docker compose exec app python -m scripts.calibrate tap 640 360   # test a tap
```
Open the screenshot, read the pixel coordinates for each button/region, and
edit `app/profiles/rok_720p.json` (`anchors`, `macros`, and the `rankings`
row regions). Verify with the **Control** page → *Connect / refresh*.

### 4. Use it
Open `http://<vps>:8000`. From **Control** you can run rankings scans (which
populate every data page) and grant titles / change ranks / locate governors.

### Public on the internet (locked Control)

The data pages (Dashboard, Power/KP, Dead, Rallies, Governors, Map) are
**public**. The **Control** page — and every `/api/control/*` endpoint —
requires a **per-officer login**: each officer has their own username/password,
and every title/rank/locate/scan command is recorded against the officer who
issued it (the queue doubles as an **audit log**). Set the first admin account
and (ideally) HTTPS:

```bash
cd deploy
cat > .env <<EOF
SITE_ADDRESS=rok.example.com     # a domain pointed at this VPS (A record)
ADMIN_USERNAME=yourname
ADMIN_PASSWORD=pick-a-strong-one
CONTROL_SECRET=$(openssl rand -hex 32)
COOKIE_SECURE=true
EOF
docker compose up -d
```

The included **Caddy** reverse proxy then serves the site at
`https://rok.example.com` with an automatic Let's Encrypt certificate. Leave
`SITE_ADDRESS` unset to serve plain HTTP on port 80 instead (fine behind a
private tunnel/VPN, but use HTTPS for a truly public site).

**Managing officers:** log in to `/control.html` as the admin. An **Officers**
panel (admins only) lets you add accounts, set `officer` or `admin` roles,
reset passwords, and disable accounts — disabling takes effect immediately, even
mid-session. Officers see only the control actions; they cannot manage accounts.
Passwords are stored as salted PBKDF2 hashes.

> Charts are vendored locally (`web/js/vendor/chart.umd.min.js`) so the site
> renders with no external CDN.

### Without Docker
Install Python deps + the ADB/OCR extras and run under systemd:
```bash
pip install -r requirements.txt -r requirements-adb.txt   # needs `tesseract` + `adb` on PATH
cp .env.example .env       # set CONTROL_BACKEND=adb, ADB_SERIAL, ADB_CONNECT
sudo cp deploy/rok1685.service /etc/systemd/system/ && sudo systemctl enable --now rok1685
```

---

## Configuration (`.env`)
| Var | Default | Meaning |
|-----|---------|---------|
| `CONTROL_BACKEND` | `mock` | `mock` or `adb` |
| `ADB_SERIAL` | `127.0.0.1:5555` | device adb talks to |
| `ADB_CONNECT` | `127.0.0.1:5555` | `adb connect` target on startup (redroid/remote) |
| `UI_PROFILE` | `app/profiles/rok_720p.json` | calibration profile |
| `TESSERACT_CMD` | `tesseract` | OCR binary path |
| `KINGDOM_ID` | `1685` | shown in the website header |
| `DB_PATH` | `data/rok1685.db` | SQLite location |
| `PORT` / `HOST` | `8000` / `0.0.0.0` | web server |
| `ADMIN_USERNAME` | `admin` | first admin officer (created on first run only) |
| `ADMIN_PASSWORD` | `changeme1685` | first admin's password — **change it** |
| `CONTROL_SECRET` | random | stable secret so logins survive restarts |
| `COOKIE_SECURE` | `false` | set `true` when served over HTTPS |
| `SITE_ADDRESS` | _(unset)_ | domain for the Caddy proxy → auto-HTTPS (compose only) |

---

## Data model
Each rankings scan upserts one **snapshot per governor per day**, coalescing
columns (a power scan fills power+KP, a dead scan fills deads, …). The website
queries:

* `GET /api/stats/leaderboard?metric=&date=&from=` — standings on a date, plus
  the gain since `from`.
* `GET /api/stats/kingdom-totals?metric=&from=&to=` — per-day totals for charts.
* `GET /api/stats/summary?date=` — dashboard headline numbers.
* `GET /api/rallies`, `GET /api/map/positions`, `GET /api/players/{id}` — etc.

Full interactive API docs are at `/docs` (FastAPI/Swagger) when running.

---

## Responsible use
This automates a game client you control to manage **your own** kingdom/account.
Automating a game may conflict with its Terms of Service — you are responsible
for how you use it. Don't point it at accounts you don't own or administer.
