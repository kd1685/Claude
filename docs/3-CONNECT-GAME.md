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
This is the account that will grant titles / change ranks, so it needs those
in-game rights (king, or an R4/R5 with the relevant permissions).

To see and tap the screen, use **scrcpy** from your own computer:
```bash
# on your computer (not the VPS):
adb connect YOUR_VPS_IP:5555    # open VPS port 5555 to your IP only, via firewall
scrcpy
```
Open RoK, log in, and leave it on the **map/city** screen.

### Step 3 — calibrate the tap coordinates
Take a screenshot and read pixel positions from it:
```bash
dc exec app python -m scripts.calibrate screenshot   # saves captures/calibrate.png
dc cp app:/app/captures/calibrate.png ./calibrate.png # copy it out to view
dc exec app python -m scripts.calibrate tap 640 360   # test-tap a point
```
Open `calibrate.png`, read the x,y of each button, and edit
`app/profiles/rok_720p.json`:
- **anchors** — the tap points (search button, title buttons, rank buttons, the
  rankings tabs, alliance/members buttons …).
- **rankings.rows** — the screen regions where each ranking row's name and value
  appear (for OCR).

The file has comments explaining each field. The defaults are for a **1280×720**
client — set redroid to that resolution (it is by default in the compose file)
to minimise changes.

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
