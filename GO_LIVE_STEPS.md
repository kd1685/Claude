════════════════════════════════════════════════════════════════════
  GO-LIVE STEPS  —  AscentTerminal  (owner checklist)
  Generated: 2026-06-12   Build: launch
════════════════════════════════════════════════════════════════════

This file is the single source of truth for deploying a fresh
AscentTerminal instance from the repo to a live URL.  Follow the
steps in order; each section has a ✅ checkbox you can tick off.

────────────────────────────────────────────────────────────────────
PRE-FLIGHT  (do these before you touch the server)
────────────────────────────────────────────────────────────────────

□ 1.  Clone / pull latest from your repo
        git clone <your-repo-url>   OR   git pull origin main

□ 2.  Copy the example env and fill in real values
        cp .env.example .env
        nano .env          # see ENV VARIABLES section below

□ 3.  Confirm Python ≥ 3.10 is installed
        python3 --version

□ 4.  Install Python deps
        pip install -r requirements.txt
        # core: fastapi uvicorn httpx python-dotenv websockets

□ 5.  (Optional) install Node if you want the JS bundler
        node --version     # ≥ 18 recommended

────────────────────────────────────────────────────────────────────
ENV VARIABLES  (.env)
────────────────────────────────────────────────────────────────────

Required
  ACCESS_KEY          = a strong random string  (gates the UI)
  ANTHROPIC_API_KEY   = sk-ant-…                (Claude AI tab)

Optional — trade execution bridge
  EXECUTE_KEY         = separate strong string  (gates /api/execute)
  AUTO_EXECUTE        = false                   (set true to auto-fire BUY/SELL)
  DEFAULT_EXCHANGE    = mexc                    (ccxt exchange id)
  USER_CAP_USD        = 0                       (per-order $ cap, 0 = unlimited)

Optional — MEXC market-data override
  MEXC_API_KEY        = …
  MEXC_API_SECRET     = …

────────────────────────────────────────────────────────────────────
STARTING THE SERVER
────────────────────────────────────────────────────────────────────

□ 6.  Start the FastAPI server

    Development (auto-reload):
        uvicorn platform.main:app --reload --port 8000

    Production (recommended):
        uvicorn platform.main:app --host 0.0.0.0 --port 8000 --workers 1

    Background (Linux/Mac):
        nohup uvicorn platform.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &

    Windows:
        start /B uvicorn platform.main:app --host 0.0.0.0 --port 8000

□ 7.  Open http://localhost:8000 in your browser
      Enter your ACCESS_KEY — you should see the full terminal UI.

────────────────────────────────────────────────────────────────────
REVERSE PROXY  (Nginx — put behind this for HTTPS + a real domain)
────────────────────────────────────────────────────────────────────

□ 8.  Install Nginx + Certbot
        sudo apt install nginx certbot python3-certbot-nginx

□ 9.  Create /etc/nginx/sites-available/ascent with:

    server {
        listen 80;
        server_name yourdomain.com;

        location / {
            proxy_pass         http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_set_header   Host $host;
            proxy_cache_bypass $http_upgrade;
        }

        # WebSocket passthrough for /ws/*
        location /ws/ {
            proxy_pass         http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "Upgrade";
            proxy_read_timeout 3600;
        }
    }

□ 10. Enable & get a cert
        sudo ln -s /etc/nginx/sites-available/ascent /etc/nginx/sites-enabled/
        sudo nginx -t && sudo systemctl reload nginx
        sudo certbot --nginx -d yourdomain.com

────────────────────────────────────────────────────────────────────
SYSTEMD SERVICE  (keep the server running after reboot)
────────────────────────────────────────────────────────────────────

□ 11. Create /etc/systemd/system/ascent.service:

    [Unit]
    Description=AscentTerminal
    After=network.target

    [Service]
    User=ubuntu
    WorkingDirectory=/home/ubuntu/AscentTerminal
    EnvironmentFile=/home/ubuntu/AscentTerminal/.env
    ExecStart=/usr/bin/uvicorn platform.main:app --host 0.0.0.0 --port 8000 --workers 1
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target

□ 12. Enable and start
        sudo systemctl daemon-reload
        sudo systemctl enable ascent
        sudo systemctl start ascent
        sudo systemctl status ascent

────────────────────────────────────────────────────────────────────
WEBHOOK URL  (TradingView alerts)
────────────────────────────────────────────────────────────────────

□ 13. Your TradingView webhook URL is:
        https://yourdomain.com/api/tv-webhook

      Alert message JSON format:
        {
          "action": "BUY",
          "symbol": "BTCUSDT",
          "price":  {{close}},
          "tp":     {{close}} * 1.02,
          "sl":     {{close}} * 0.98
        }

      Supported actions: BUY  SELL  TP  SL  ALERT

────────────────────────────────────────────────────────────────────
QUICK SMOKE-TEST
────────────────────────────────────────────────────────────────────

□ 14. UI loads at your domain with the lock screen
□ 15. ACCESS_KEY unlocks the terminal
□ 16. Asset picker shows tickers and live prices
□ 17. CHART tab renders candles
□ 18. SIGNALS tab loads indicator panel
□ 19. AI tab → "Analyse this setup" returns a Claude response
□ 20. POST a test webhook (curl example):

    curl -X POST https://yourdomain.com/api/tv-webhook \
      -H 'Content-Type: application/json' \
      -d '{"action":"ALERT","symbol":"BTCUSDT","price":67000}'

    → Alert should appear in the ALERTS tab within seconds.

□ 21. BOTS tab → Add Trend Bot → configure → Start → confirm it
      logs "waiting for signal" in the events panel

────────────────────────────────────────────────────────────────────
UPDATES
────────────────────────────────────────────────────────────────────

Windows:  double-click  UPDATE.bat
Linux:    git pull && pip install -r requirements.txt -q &&
          sudo systemctl restart ascent

────────────────────────────────────────────────────────────────────
TROUBLESHOOTING
────────────────────────────────────────────────────────────────────

Server won't start
  • Check Python version (≥ 3.10)
  • pip install -r requirements.txt
  • Check .env exists and ACCESS_KEY is set

UI shows 403 / locked
  • ACCESS_KEY in .env must match what you type in the UI

AI tab errors
  • ANTHROPIC_API_KEY must be valid and have credits
  • Check server logs: sudo journalctl -u ascent -n 50

Webhook not received
  • Test with curl (step 20)
  • Confirm firewall allows inbound 443
  • Check Nginx error log: sudo tail -f /var/log/nginx/error.log

Bot won't execute live
  • EXECUTE_KEY must be set in .env
  • Exchange API keys must have futures-trade permission
  • USER_CAP_USD must be ≥ your order size (or 0)

════════════════════════════════════════════════════════════════════
END OF CHECKLIST
════════════════════════════════════════════════════════════════════
