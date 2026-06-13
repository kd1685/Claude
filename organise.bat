@echo off
REM Ascent Terminal — organise release folder
REM Run this from the root of the release folder to check everything is in place

echo Checking release structure...
echo.

IF EXIST platform\app.py (
    echo [OK] platform/app.py
) ELSE (
    echo [MISSING] platform/app.py
)

IF EXIST platform\.env.example (
    echo [OK] platform/.env.example
) ELSE (
    echo [MISSING] platform/.env.example
)

IF EXIST platform\static\index.html (
    echo [OK] platform/static/index.html
) ELSE (
    echo [MISSING] platform/static/index.html
)

IF EXIST platform\static\landing.html (
    echo [OK] platform/static/landing.html
) ELSE (
    echo [MISSING] platform/static/landing.html
)

IF EXIST platform\static\download.html (
    echo [OK] platform/static/download.html
) ELSE (
    echo [MISSING] platform/static/download.html
)

IF EXIST bots\scalper_bot.py (
    echo [OK] bots/scalper_bot.py
) ELSE (
    echo [MISSING] bots/scalper_bot.py
)

IF EXIST brain\edge_lab.py (
    echo [OK] brain/edge_lab.py
) ELSE (
    echo [MISSING] brain/edge_lab.py
)

IF EXIST brain\mexc_trend_bot.py (
    echo [OK] brain/mexc_trend_bot.py
) ELSE (
    echo [MISSING] brain/mexc_trend_bot.py
)

IF EXIST discord\discord_role_sync.py (
    echo [OK] discord/discord_role_sync.py
) ELSE (
    echo [MISSING] discord/discord_role_sync.py
)

IF EXIST tools\DEPLOY_TO_VPS.bat (
    echo [OK] tools/DEPLOY_TO_VPS.bat
) ELSE (
    echo [MISSING] tools/DEPLOY_TO_VPS.bat
)

IF EXIST installer\AscentTerminal.iss (
    echo [OK] installer/AscentTerminal.iss
) ELSE (
    echo [MISSING] installer/AscentTerminal.iss
)

echo.
echo Structure check complete.
pause
