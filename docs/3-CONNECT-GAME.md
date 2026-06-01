# 3. Connect a real Rise of Kingdoms client

This points the controller at a live RoK client and calibrates the taps so it
can scan rankings and grant titles/ranks. Assumes you finished
**[2-VPS-SETUP.md](2-VPS-SETUP.md)** (the `android` + `app` containers are up).

> Why calibration? RoK has no API. The controller works by tapping screen
> coordinates and reading the rankings with OCR. Those coordinates depend on the
> screen, so you set them once in a JSON profile.

A shortcut for all the commands below:
```bash
dc() { docker compose -f deploy/docker-compose.yml "$@"; }
```

### Step 1 — install RoK into the Android container
Get the RoK APK onto the VPS (e.g. `scp rok.apk you@vps:~/`), then:
```bash
dc exec app adb -s android:5555 connect android:5555
dc cp ~/rok.apk app:/tmp/rok.apk
dc exec app adb -s android:5555 install /tmp/rok.apk
```

### Step 2 — log into the controlling account
The VPS is headless, so to log the game in you **mirror the emulator's screen to
your own computer** and click around with your mouse. You only do this once.

**Which account?** The one that will grant titles / change ranks — it needs
those in-game rights (king, or an R4/R5). Log it in with a **Lilith Game account
(email + password)**, not Google/Facebook: redroid has no Google Play Services,
and an email login is something you can type directly. If your controlling
account is currently bound only to Google, open RoK on your phone first →
**Settings → Account** → add a Lilith/email login.

**On your own computer**, install `adb` (Android platform-tools) and
[`scrcpy`](https://github.com/Genymobile/scrcpy), then reach the VPS emulator
over a secure SSH tunnel (never expose ADB to the internet):
```bash
# 1) tunnel the emulator's ADB port to your computer
ssh -L 5555:localhost:5555 youruser@YOUR_VPS_IP

# 2) in a second terminal on your computer
adb connect localhost:5555
scrcpy                       # opens a window mirroring the emulator
```
In the scrcpy window: open RoK, log in with the email account, clear any
first-run prompts, and leave it on the **map/city** screen. It stays logged in;
close scrcpy when done — the bot keeps running on the VPS.

> If `adb connect` shows "offline", give the emulator a minute after boot, then
> `adb disconnect && adb connect localhost:5555`.

### Step 3 — calibrate the tap coordinates
Take a screenshot and read pixel positions from it:
```bash
dc exec app python -m scripts.calibrate screenshot   # saves captures/calibrate.png
dc cp app:/app/captures/calibrate.png ./calibrate.png # copy it out to view
dc exec app python -m scripts.calibrate tap 640 360   # test-tap a point
```
**Pick the profile that matches your emulator resolution** (set `UI_PROFILE` in
`deploy/.env`):
- **1280×720** → `app/profiles/rok_720p.json` (default; redroid uses 720p in the
  compose file)
- **1920×1080** → `app/profiles/rok_1080p.json`

```bash
# in deploy/.env — only if your emulator runs at 1080p
UI_PROFILE=app/profiles/rok_1080p.json
```

Open `calibrate.png`, read the x,y of each button, and edit that profile:
- **anchors** — the tap points (search button, title buttons, rank buttons, the
  rankings tabs, alliance/members buttons …).
- **rankings.rows** — the screen regions where each ranking row's name and value
  appear (for OCR).

Both profiles are sensible starting points, not pixel-perfect — calibrate
against your own screenshot. The 1080p profile is the 720p one scaled ×1.5.

Restart the app after editing so it reloads the profile:
```bash
dc restart app
```

### Step 4 — verify the connection
On the website: **Control → Connect / refresh**. You should see
`"connected": true` and your device listed.

### Step 5 — first real scan
Control → **Scan rankings** → pick *Power* → Start. Watch the **Command queue**;
when it says done, the **Power & KP** page fills with real numbers. Repeat for
*Kill Points* and *Dead*.

### Step 6 — automate it
Control → **Automatic scans** (admin) → add e.g. Power at `02:00`, KP at `02:10`,
Dead at `02:20`. **Times are UTC.** Now the kingdom history fills itself daily.

✅ Done. See **[4-DAILY-USE.md](4-DAILY-USE.md)** for everyday tasks.

### If the emulator won't run on your VPS
`deploy/preflight.sh` said "no binder support" (common on OpenVZ/LXC VPSes)?
The website, API, charts and accounts all still work — only the live scan/control
actions need a reachable Android instance. Pick one:

1. **Use a host where you control the kernel** — bare-metal or a KVM VPS whose
   kernel has `CONFIG_ANDROID_BINDERFS` (most do). Re-run the preflight there.
2. **Full Android emulator on a KVM host** (needs `/dev/kvm`) — heavier than
   redroid but works where binder modules are available.
3. **Point ADB at a real Android phone/tablet** running RoK on your network:
   ```bash
   # in deploy/.env
   CONTROL_BACKEND=adb
   ADB_CONNECT=PHONE_IP:5555      # enable "Wireless debugging" on the phone
   ADB_SERIAL=PHONE_IP:5555
   ```
   Drop the `android` service from the compose file (or just ignore it) and the
   `app` container talks to your phone instead. Everything else is identical.

### Troubleshooting
- **`connected: false`** — the emulator isn't reachable. `dc exec app adb devices`
  should list `android:5555`. If not: `dc restart android` and wait a minute.
- **Scan returns 0 rows / garbage** — OCR isn't available or regions are off.
  The Docker image already includes `tesseract`; re-check the `rankings.rows`
  coordinates against your screenshot.
- **Taps land in the wrong place** — your resolution differs from the profile;
  re-read coordinates from `calibrate.png` and update the anchors.
