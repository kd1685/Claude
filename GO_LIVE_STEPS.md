════════════════════════════════════════════════════════════════════
 ASCENT TERMINAL — GO-LIVE STEPS (final pass · do in order)
════════════════════════════════════════════════════════════════════
This zip is CODE ONLY — your live .env, keys.json and data/ are never
overwritten. Times are realistic. §3 (Stripe) is the one you said
you're doing tomorrow; everything else can be done today.

──────────────────────────────────────────────────────────────────
 §1  UPLOAD THE UPDATE TO THE VPS (10 min)
──────────────────────────────────────────────────────────────────

[ ] 1a. On your Windows PC, open a terminal in this folder and run:

        UPDATE.bat

     It will rsync everything (except .env / keys.json / data/).
     Watch for any rsync errors; there should be none.

[ ] 1b. SSH into the VPS:

        ssh user@<your-vps-ip>
        cd /opt/ascent          # or wherever you deployed
        source venv/bin/activate
        pip install -r requirements.txt   # picks up new deps

──────────────────────────────────────────────────────────────────
 §2  RESTART SERVICES (5 min)
──────────────────────────────────────────────────────────────────

[ ] 2a. Restart the main platform:

        sudo systemctl restart ascent
        sudo systemctl status  ascent   # should say "active (running)"

[ ] 2b. If you run the scalper bot as a separate service:

        sudo systemctl restart ascent-scalper
        sudo systemctl status  ascent-scalper

[ ] 2c. Tail the logs for 60 seconds and confirm no tracebacks:

        journalctl -u ascent -f

──────────────────────────────────────────────────────────────────
 §3  STRIPE LIVE KEY (do tomorrow — 15 min)
──────────────────────────────────────────────────────────────────

You told me you're switching Stripe from test→live tomorrow.
When you're ready:

[ ] 3a. In the Stripe dashboard → Developers → API keys, copy the
        live Secret key  (sk_live_…).

[ ] 3b. On the VPS, edit .env:

        nano /opt/ascent/.env

        Change:
          STRIPE_SECRET_KEY=sk_test_…
        To:
          STRIPE_SECRET_KEY=sk_live_…

        Also update STRIPE_WEBHOOK_SECRET with the live webhook
        signing secret (Stripe dashboard → Webhooks → your endpoint
        → Signing secret).

[ ] 3c. sudo systemctl restart ascent

[ ] 3d. Do one real £1 test purchase to confirm end-to-end.

──────────────────────────────────────────────────────────────────
 §4  VERIFY THE WEBSITE (5 min)
──────────────────────────────────────────────────────────────────

[ ] 4a. Open https://ascentterminal.com in a browser.
        - Home page loads without JS errors (open DevTools → Console)
        - /download page shows the Windows download button
        - /pricing page shows the correct tier cards

[ ] 4b. Click the download button — confirm the .exe (or .zip)
        actually downloads.

[ ] 4c. Log in as a test user and confirm the dashboard loads.

──────────────────────────────────────────────────────────────────
 §5  SMOKE-TEST THE BOTS (10 min)
──────────────────────────────────────────────────────────────────

[ ] 5a. On the VPS, run the edge lab in dry-run mode:

        cd /opt/ascent/brain
        python edge_lab.py --dry-run

        Expected: prints signal summary, exits 0, no exceptions.

[ ] 5b. Check the scalper bot heartbeat endpoint (if you wired one):

        curl http://localhost:8001/health

        Expected: {"status": "ok"}

──────────────────────────────────────────────────────────────────
 §6  OPTIONAL: RUN THE FULL EDGE-LAB BACKTEST (30–60 min)
──────────────────────────────────────────────────────────────────

Only needed if you changed any strategy parameters.

[ ] 6a. On Windows, open brain/ and double-click RUN_EDGE_LAB.bat
        (or run it from a terminal).

[ ] 6b. Results land in brain/edge_results.csv.
        Open with Excel / the edge_lab viewer and confirm Sharpe > 1.

──────────────────────────────────────────────────────────────────
 DONE — everything above ticked = you are live
──────────────────────────────────────────────────────────────────
