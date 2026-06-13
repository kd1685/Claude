@echo off
REM  ASCENT TERMINAL - send a test post to a Discord webhook URL
REM  Use after creating the #signals webhook to prove it works
REM  BEFORE pasting it into the server's .env.
set /p URL="  Paste the Discord webhook URL: "
curl -s -H "Content-Type: application/json" -d "{\"content\":\"✅ Ascent Terminal webhook test — if you can read this in #signals, paste this URL into the server's .env as DISCORD_WEBHOOK_URL and run: docker compose up -d --force-recreate\"}" "%URL%"
echo.
echo  Check the Discord channel for the test message.
pause
