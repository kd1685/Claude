@echo off
REM ============================================================
REM  UPDATE.bat — pull latest code and upgrade pip packages
REM ============================================================

echo.
echo ============================================================
echo  Ascent Terminal — Updater
echo ============================================================
echo.

REM ── 1. Pull latest from GitHub ──────────────────────────────
echo [1/3] Pulling latest code from GitHub...
git pull
if errorlevel 1 (
    echo.
    echo  ERROR: git pull failed.
    echo  Make sure git is installed and you have internet access.
    pause
    exit /b 1
)
echo  Done.
echo.

REM ── 2. Upgrade pip packages ─────────────────────────────────
echo [2/3] Upgrading pip packages...
if exist platform\requirements.txt (
    pip install --upgrade -r platform\requirements.txt
) else (
    pip install --upgrade ccxt python-dotenv requests pandas numpy ta
)
if errorlevel 1 (
    echo.
    echo  WARNING: pip upgrade had errors — check output above.
)
echo  Done.
echo.

REM ── 3. Re-run organiser to sync any new scripts ─────────────
echo [3/3] Syncing scripts via organise.bat...
call organise.bat
echo  Done.
echo.

echo ============================================================
echo  Update complete.  You can now start the bot.
echo ============================================================
echo.
pause
