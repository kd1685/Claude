# 6. Run the game on your PC (LDPlayer) with the agent

Rise of Kingdoms is too heavy to run on a plain VPS (no graphics card, no Google
services). The reliable way is to run the game on your **PC in LDPlayer** (a free
Android emulator that runs RoK perfectly) and let a small **agent** connect it to
your live site.

```
 Your VPS (always on)                 Your PC (on when scanning)
 ───────────────────                  ─────────────────────────
 website + API + database  ◀── tasks/results ──▶  agent.py ──ADB──▶ LDPlayer (RoK)
 kd1685.com
```

The website, domain, logins — everything you built — stays exactly the same. You
just switch the server to "remote" mode and run the agent on your PC.

---

## Part A — switch the server to remote mode (one time, in your VPS SSH window)

```bash
cd ~/rok1685
echo "CONTROL_BACKEND=remote" >> deploy/.env
echo "AGENT_TOKEN=$(openssl rand -hex 32)" >> deploy/.env
grep AGENT_TOKEN deploy/.env          # <-- COPY this token, you'll need it on the PC
docker compose -f deploy/docker-compose.yml up -d        # restart with new settings
docker compose -f deploy/docker-compose.yml stop android # (optional) free the unused emulator
```

Copy the long `AGENT_TOKEN=...` value somewhere — you'll paste it on your PC.

## Part B — set up LDPlayer + RoK (on your PC)

1. Install **LDPlayer** from https://www.ldplayer.net and open it.
2. Inside LDPlayer, open the **Play Store**, sign in with any Google account, and
   install **Rise of Kingdoms** (this "just works" here — graphics + Google
   services are built in).
3. Open RoK and **log in with your controlling email/Lilith account** (king or
   R4/R5), and leave it on the **map** screen.
4. Turn on ADB: LDPlayer **Settings → Other settings → ADB debugging → "Open
   local connection (127.0.0.1)"**, then save. (LDPlayer's ADB is `127.0.0.1:5555`.)

## Part C — install the agent (on your PC)

1. Install **Python 3** from https://www.python.org — tick **"Add python.exe to
   PATH"** during install.
2. Install **Tesseract OCR** (Windows build):
   https://github.com/UB-Mannheim/tesseract/wiki — default path is
   `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. Get the project on your PC (in a Command Prompt):
   ```
   git clone https://github.com/kd1685/claude.git rok1685
   cd rok1685
   pip install -r agent/requirements.txt
   ```
4. Make your settings file:
   ```
   copy agent\agent.env.example agent\agent.env
   notepad agent\agent.env
   ```
   Set these (save and close Notepad after):
   - `SERVER_URL=https://kd1685.com`
   - `AGENT_TOKEN=` → paste the token from Part A
   - `ADB_SERIAL=127.0.0.1:5555`
   - `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`
   - `UI_PROFILE=app/profiles/rok_720p.json` (use `rok_1080p.json` if LDPlayer is 1080p)

## Part D — run it

Double-click **`agent\run-agent.bat`** (or run `python agent\agent.py`). You should see:
```
Kingdom 1685 agent → https://kd1685.com
Emulator: connected to ['127.0.0.1:5555']
Waiting for tasks…
```
Leave that window open. On your site, open **Control** → it now shows the agent
**online** (`backend: remote, connected: true`).

## Part E — calibrate + first scan

The agent taps screen coordinates, so calibrate them for LDPlayer once — exactly
like **[3-CONNECT-GAME.md → Step 3](3-CONNECT-GAME.md)**, but on your PC and
pointed at LDPlayer (`ADB_SERIAL=127.0.0.1:5555`). Edit `app/profiles/rok_720p.json`
to match what you see in a screenshot.

Then on the website: **Control → Scan rankings → Power → Start**. Watch the agent
window run it in LDPlayer; when it finishes, the **Power & KP** page fills with
real data. 🎉 Titles, ranks, locates and rotations all work the same way now —
the agent performs them in LDPlayer.

> Keep the agent window (and LDPlayer) running whenever you want scans, scheduled
> scans, or rotations to happen. Close them and the site still serves all your
> data — it just pauses live actions until the agent is back.
