# ☀️ START HERE — morning runbook

Everything below either runs instantly or needs only your Discord bot token /
your domain. Do them in this order.

---

## 1. Test the web terminal locally (2 min, instant)
Folder: `platform/`
```cmd
cd platform
run_local.bat
```
Then open **http://localhost:8000** in your browser.
- The **proof panel** (top) loads in ~30s (it fetches history).
- Type **DEMO-KEY** in the access box (top right) → the **live signals unlock**.
- Click coins to see charts with the EMA30 trend line.
- To view it on your **phone**: run `ipconfig`, note your IPv4, open
  `http://<that-ip>:8000` on your phone (same Wi-Fi).

✅ This confirms the whole panel works before you deploy it.

---

## 2. Start the forward paper track record (1 min)
Folder: `forward/`
```cmd
cd forward
forward_paper.bat
```
Run it **once a day** (or `python forward_paper.py --loop` to leave it running).
It logs a live equity track record to `forward_log.csv`.

⚠️ **Honest note (read this):** a *daily* trend strategy needs **months**, not 2
weeks, to validate statistically — in 2 weeks you may see **zero** trend flips.
What 2 weeks DOES prove is that everything **works live** (signals compute, data
feeds, accounting). Treat this as an **operational check + the start of a real
track record** you'll show on the proof panel later — not as "edge confirmed."
The edge is already evidenced by the 40-coin out-of-sample backtest.

---

## 3. Populate your Discord (5 min — needs your bot token)
You already have the bot + server. Make sure **Developer Mode** is on, right-click
your server → **Copy Server ID**.

```cmd
pip install discord.py

REM channels + roles + permissions:
set DISCORD_BOT_TOKEN=your-NEW-bot-token
set DISCORD_GUILD_ID=715825137785634859
python discord_setup.py

REM standard text (welcome / rules / disclaimer / faq / getting-started), pinned:
python discord_content\discord_post_content.py

REM your Whop storefront pitch, pinned in #start-here:
python discord_post_pitch.py
```
(If a step says **Missing Permissions**, drag your bot's role to the top of
Server Settings → Roles and re-run — all scripts are safe to re-run.)

🔑 **Reset your bot token first** if it was ever shown in a screenshot.

---

## 4. (Optional) Test the Discord trend-flip alerts
The web app posts alerts itself when a coin's daily trend flips — just set the
webhook before running it (locally or on the VPS):
```cmd
set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/....
```
(Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL.)

---

## 5. Paste your legal text (5 min)
Folder: `legal/`
- `DISCLAIMER.md` → website footer + Whop listing + Discord #disclaimer.
- `TERMS.md` → website /terms + Whop.
- Fill the `[DATE]`, `[YOUR JURISDICTION]`, refund policy, and contact blanks.
- ⚠️ Get a lawyer to glance at them before taking money — you're selling trading
  software/signals.

---

## 6. Go live on your VPS (when ready — needs your domain)
Full step-by-step is in **`platform/DEPLOY.md`**. Short version:
1. Point a DNS **A record** (e.g. `app.yourdomain.com`) → your VPS IP.
2. On the VPS: install Docker, `ufw allow 80,443`, upload the `platform/` folder.
3. `cp .env.example .env` and edit it (your domain, your real ACCESS_KEYS,
   optional Discord webhook).
4. `docker compose up -d --build` → Caddy auto-issues HTTPS in ~30s.
5. Visit `https://app.yourdomain.com`.

Then point the **desktop app** at it: in `desktop/ascent_desktop.py` set
`ASCENT_URL` to your domain before building the `.exe` (`build_desktop.bat`).

---

## 📁 What's where
```
platform/        the web terminal (FastAPI + dashboard) + deploy kit + run_local.bat
  static/        the browser UI
  desktop/       downloadable .exe client (build_desktop.bat)
  DEPLOY.md      VPS deploy guide
forward/         forward_paper.py — live paper track record
discord_setup.py            create channels/roles/permissions
discord_content/            standard text (welcome/rules/disclaimer/faq/getting-started)
discord_post_pitch.py       your Whop pitch
legal/           DISCLAIMER.md + TERMS.md
brain/           the research tools that found & validated the trend edge
```

## ✅ Launch checklist
- [ ] Web terminal tested locally (step 1)
- [ ] Forward paper running (step 2)
- [ ] Discord populated: channels, rules, disclaimer, faq, pitch (step 3)
- [ ] Legal text filled in + placed (step 5)
- [ ] Deployed to VPS + HTTPS live (step 6)
- [ ] Whop tiers finalized + access-key delivery decided
- [ ] Patreon Discord integration connected (auto-roles)
- [ ] Real ACCESS_KEYS set (remove DEMO-KEY in production)

You did this the honest way — proved what doesn't work, found the trend edge that
does, and built a real product around it. Sleep well. ☕
