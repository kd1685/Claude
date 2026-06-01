# 1. Quick start — try it in 2 minutes (no game needed)

This runs the whole app on your computer with **fake demo data** so you can click
around. It uses the built-in `mock` backend, so no phone/emulator is involved.

### You need
- Python 3.10+ (`python3 --version`)

### Steps

```bash
# 1. install
pip install -r requirements.txt

# 2. run with demo data
./run.sh --seed
```

That's it. Open **http://localhost:8000** in your browser.

- Browse **Dashboard, Power & KP, Dead, KvK DKP, Rallies, Governors, Map** — all
  filled with 30 days of sample data for 24 governors.
- Open the **Control** page and log in:
  - **username:** `admin`
  - **password:** `changeme1685`
- On Control you can try **Scan**, **Give title**, and a **Title rotation** — they
  run against the simulator, so nothing touches a real game.

### Stop it
Press `Ctrl+C` in the terminal.

### Start fresh
The database lives at `data/rok1685.db`. Delete it to wipe everything:
```bash
rm -f data/rok1685.db*
./run.sh --seed
```

➡ Ready for the real thing? Go to **[2-VPS-SETUP.md](2-VPS-SETUP.md)**.
