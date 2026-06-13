@echo off
echo Starting organiser...
echo Log: %USERPROFILE%\Desktop\organise_log.txt

REM ============================================================
REM  organise.bat — Ascent Terminal Windows setup
REM  Run this once on a new PC (or after a git pull).
REM  It creates the platform/ folder layout and copies scripts.
REM ============================================================

setlocal enabledelayedexpansion

REM ── Resolve repo root (folder containing this .bat) ─────────
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

REM ── Target platform folder ──────────────────────────────────
set "PLAT=%REPO%\platform"

echo.
echo ============================================================
echo  Ascent Terminal — Organiser
echo  Repo : %REPO%
echo  Platform : %PLAT%
echo ============================================================
echo.

REM ── Create folder layout ────────────────────────────────────
echo [1/6] Creating folder layout...
for %%D in (
    "%PLAT%"
    "%PLAT%\bots"
    "%PLAT%\brain"
    "%PLAT%\data"
    "%PLAT%\logs"
) do (
    if not exist "%%~D" (
        mkdir "%%~D"
        echo   Created: %%~D
    ) else (
        echo   Exists : %%~D
    )
)
echo.

REM ── Copy bot scripts ────────────────────────────────────────
echo [2/6] Copying bot scripts...
if exist "%REPO%\bots\scalper_bot.py" (
    copy /Y "%REPO%\bots\scalper_bot.py" "%PLAT%\bots\scalper_bot.py" >nul
    echo   Copied: bots/scalper_bot.py
) else (
    echo   MISSING: bots/scalper_bot.py — skipped
)
echo.

REM ── Copy brain scripts ──────────────────────────────────────
echo [3/6] Copying brain scripts...
for %%F in (
    "mexc_trend_bot.py"
    "edge_lab.py"
    "swing_backtest.py"
    "RUN_EDGE_LAB.bat"
) do (
    if exist "%REPO%\brain\%%~F" (
        copy /Y "%REPO%\brain\%%~F" "%PLAT%\brain\%%~F" >nul
        echo   Copied: brain/%%~F
    ) else (
        echo   MISSING: brain/%%~F — skipped
    )
)
echo.

REM ── Write .env (only if it doesn't exist) ───────────────────
echo [4/6] Writing starter .env...
if not exist "%PLAT%\.env" (
    (
        echo # Ascent Terminal — environment variables
        echo # Fill in your real values before running any bot.
        echo.
        echo MEXC_API_KEY=YOUR_KEY_HERE
        echo MEXC_API_SECRET=YOUR_SECRET_HERE
        echo.
        echo TELEGRAM_BOT_TOKEN=YOUR_TOKEN_HERE
        echo TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
        echo.
        echo # Trading settings
        echo SYMBOL=BTC/USDT:USDT
        echo POSITION_SIZE_USDT=20
        echo LEVERAGE=5
        echo TP_PCT=0.8
        echo SL_PCT=0.4
        echo RSI_OVERSOLD=35
        echo RSI_OVERBOUGHT=65
        echo.
        echo # Safety
        echo PAPER_TRADE=true
    ) > "%PLAT%\.env"
    echo   Written: platform/.env  ^(fill in your credentials^)
) else (
    echo   Exists : platform/.env  ^(not overwritten^)
)
echo.

REM ── Write requirements.txt ──────────────────────────────────
echo [5/6] Writing requirements.txt...
(
    echo ccxt
    echo python-dotenv
    echo requests
    echo pandas
    echo numpy
    echo ta
) > "%PLAT%\requirements.txt"
echo   Written: platform/requirements.txt
echo.

REM ── Write run_bot.bat ───────────────────────────────────────
echo [6/6] Writing run_bot.bat...
(
    echo @echo off
    echo REM Ascent Terminal — start the scalper bot
    echo cd /d "%%~dp0"
    echo python bots/scalper_bot.py
    echo pause
) > "%PLAT%\run_bot.bat"
echo   Written: platform/run_bot.bat
echo.

echo ============================================================
echo  Setup complete.
echo.
echo  Next steps:
echo   1. Open platform\.env and fill in your credentials
echo   2. Run:  pip install -r platform\requirements.txt
echo   3. Double-click platform\run_bot.bat to start the bot
echo.
echo  See GO_LIVE_STEPS.md for the full checklist.
echo ============================================================
echo.
pause
