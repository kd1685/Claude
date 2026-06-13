# Ascent Terminal — START HERE

Welcome. This file is your map.

---

## What is Ascent Terminal?

Ascent Terminal is a **self-hosted, multi-user trading intelligence platform**.
It provides:

- Real-time market data (order-flow, liquidations, macro, forex)
- AI-powered market analysis
- Backtesting engine
- TradingView webhook receiver → execution bridge
- Tier-based API key access control
- Stripe subscription billing (optional)
- Desktop client (Electron-style, built with PyWebView)

---

## Repository layout

```
platform/
├── auth.py               # FastAPI app — all HTTP routes + WebSocket
├── market_intel.py       # Unified market-intelligence WebSocket hub
├── orderflow.py          # Order-flow analysis
├── liquidations.py       # Liquidation data
├── macro_data.py         # Macro economic indicators
├── forex_data.py         # Forex rates
├── mexc_macro.py         # MEXC-specific macro data
├── exchanges.py          # Exchange connectors
├── execution.py          # Order execution bridge
├── exits.py              # Exit strategy engine
├── backtest.py           # Back-testing engine
├── ai_analyst.py         # AI market analyst
├── store_db.py           # PostgreSQL helpers
├── webhook_store.py      # TradingView webhook receiver
├── privacy.py            # GDPR / data-privacy helpers
├── key_gen.py            # CLI tool — generate / revoke API keys
├── backup.sh             # Database + key backup script
├── requirements.txt      # Python dependencies
├── Dockerfile            # Container image
├── docker-compose.yml    # Full stack (app + Caddy + Postgres)
├── Caddyfile             # Reverse proxy / TLS config
├── Caddyfile.cloudflare  # Variant for CF-proxied domains
├── .env.example          # Environment variable template
├── .dockerignore
├── DEPLOY.md             # Step-by-step deployment guide
├── run_local.bat         # Windows quick-start (no Docker)
├── static/
│   └── download.html       # Desktop-client download page
├── certs/
│   └── README.txt          # Notes on TLS certificate management
└── desktop/
    ├── ascent_desktop.py   # Desktop client source
    └── build_desktop.py    # PyInstaller build script
```

---

## Quickstart (Docker)

```bash
cd platform
cp .env.example .env
# edit .env — set DOMAIN and DB_PASSWORD at minimum
docker compose up -d --build
```

See `DEPLOY.md` for the full guide.

---

## Quickstart (Windows, no Docker)

Double-click `run_local.bat`.

---

## First steps after deploy

1. Visit `https://<your-domain>` — you should see the Ascent Terminal UI.
2. Generate your first API key:
   ```bash
   docker compose exec app python key_gen.py --tier operator --label "me"
   ```
3. Open the desktop client or connect via the API.

---

## Getting help

Open an issue or check `DEPLOY.md` for troubleshooting.
