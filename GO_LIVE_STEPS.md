════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — GO-LIVE STEPS (final pass · do in order)
════════════════════════════════════════════════════════════════════
This zip is CODE ONLY — your live .env, keys.json and data/ are never
overwritten. Times are realistic. §3 (Stripe) is the one you said
you're doing tomorrow; everything else can be done today.

──────────────────────────────────────────────────────────────────
 §1  UPLOAD THE UPDATE TO THE VPS (10 min)
──────────────────────────────────────────────────────────────────

  From Windows, open UPDATE.bat and follow the one prompt it gives
  you (it asks for your VPS IP once, then does the rest).

  What it does:
    • rsync everything EXCEPT .env / keys.json / data/  to the VPS
    • restarts the ascent-terminal systemd service automatically

  If you don't have rsync on Windows yet:
    winget install --id GnuWin32.Rsync   (or use WSL / Git-Bash)

──────────────────────────────────────────────────────────────────
 §2  SMOKE-TEST THE LIVE SERVER (5 min)
──────────────────────────────────────────────────────────────────

  2a. SSH into the VPS and check the service:

        ssh user@<your-vps-ip>
        sudo systemctl status ascent-terminal
        sudo journalctl -u ascent-terminal -n 40

      You want: Active: active (running)
      No tracebacks in the log.

  2b. Hit the health endpoint from your browser or curl:

        curl https://ascentterminal.com/health
        # → {"status": "ok", ...}

  2c. Log in as a test user and load the dashboard.
      Confirm the chart loads and the sidebar shows your real
      subscription status (or "free tier" if no sub yet).

──────────────────────────────────────────────────────────────────
 §3  STRIPE LIVE-KEY SWAP (15 min — do this tomorrow)
──────────────────────────────────────────────────────────────────

  You said you're doing this step tomorrow, so just a reminder:

  3a. In Stripe Dashboard → Developers → API keys
        Copy the live Publishable key  (pk_live_…)
        Copy the live Secret key        (sk_live_…)

  3b. In Stripe Dashboard → Webhooks
        Add endpoint:  https://ascentterminal.com/stripe/webhook
        Events to send:
          checkout.session.completed
          customer.subscription.updated
          customer.subscription.deleted
          invoice.payment_failed
        Copy the Signing secret  (whsec_…)

  3c. SSH into VPS, edit .env:

        nano /home/<user>/ascent-terminal/.env

        Change:
          STRIPE_SECRET_KEY=sk_live_…
          STRIPE_PUBLISHABLE_KEY=pk_live_…
          STRIPE_WEBHOOK_SECRET=whsec_…
          STRIPE_PRICE_ID=price_…   ← your live price ID

  3d. sudo systemctl restart ascent-terminal
      Do one real £1 test purchase to confirm webhooks fire.

──────────────────────────────────────────────────────────────────
 §4  DISCORD ROLE-SYNC (10 min)
──────────────────────────────────────────────────────────────────

  The bot already exists; you just need to point it at production.

  4a. Make sure DISCORD_BOT_TOKEN and DISCORD_GUILD_ID are in .env.

  4b. Run role_sync_setup.bat from your Windows machine once to
      register the slash commands with Discord.

  4c. In Discord → Server Settings → Integrations → Bots
      confirm the bot has the "Manage Roles" permission and that
      your subscriber role sits BELOW the bot's role in the list.

  4d. Test: use /sync in your Discord server. The bot should DM
      you a confirmation and assign the correct role.

──────────────────────────────────────────────────────────────────
 §5  PATREON WEBHOOK (5 min, only if you're using Patreon)
──────────────────────────────────────────────────────────────────

  5a. Patreon → Creator Tools → Webhooks
      Add:  https://ascentterminal.com/patreon/webhook
      Tick:  members:pledge:create  /  members:pledge:delete

  5b. Copy the Patreon webhook secret into .env:
        PATREON_WEBHOOK_SECRET=…

  5c. sudo systemctl restart ascent-terminal

──────────────────────────────────────────────────────────────────
 §6  SSL / DOMAIN CHECK (2 min)
──────────────────────────────────────────────────────────────────

  curl -I https://ascentterminal.com
  # HTTP/2 200  ← good
  # Check cert expiry: sudo certbot renew --dry-run

──────────────────────────────────────────────────────────────────
 §7  OPTIONAL — WINDOWS INSTALLER BUILD
──────────────────────────────────────────────────────────────────

  Only needed if you want to ship a .exe to subscribers.

  7a. Install Inno Setup 6  (https://jrsoftware.org/isdl.php)
  7b. Open installer/AscentTerminal.iss in Inno Setup
  7c. Press Ctrl+F9 to compile
  7d. Upload the resulting Output/AscentTerminalSetup.exe wherever
      you host downloads (VPS /static, S3, etc.)

════════════════════════════════════════════════════════════════════
 THAT'S IT.  Estimated total time (excl. Stripe tomorrow): ~30 min
════════════════════════════════════════════════════════════════════
