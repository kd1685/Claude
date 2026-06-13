@echo off
REM role_sync_setup.bat — installs dependencies and starts the Whop role sync server locally.
REM For testing only. On your VPS this runs automatically via docker compose.

cd /d "%~dp0"
echo ============================================================
echo  Installing dependencies...
echo ============================================================
pip install fastapi uvicorn discord.py requests

echo.
echo ============================================================
echo  BEFORE RUNNING:
echo  1. Set your Whop plan IDs in discord_role_sync.py
echo     (PLAN_TO_ROLE dictionary — replace placeholder values)
echo  2. Get your Whop webhook secret from:
echo     Whop dashboard > Settings > Webhooks
echo ============================================================
echo.

set DISCORD_BOT_TOKEN=your-bot-token-here
set DISCORD_GUILD_ID=715825137785634859
set WHOP_WEBHOOK_SECRET=your-whop-webhook-secret-here

echo Starting role sync server on http://localhost:8001
echo Health check: http://localhost:8001/health
echo Webhook endpoint: http://localhost:8001/whop-webhook
echo Press Ctrl+C to stop.
echo.

uvicorn discord_role_sync:app --host 0.0.0.0 --port 8001
pause
