@echo off
REM ============================================================
REM  ASCENT TERMINAL - UPDATE EVERYTHING
REM  Run this from inside the new AscentTerminal folder.
REM  It will:
REM    1. Find your VPS details from .env (or prompt you)
REM    2. Rsync the code (never touches .env/keys.json/data/)
REM    3. Print a checklist of manual steps
REM ============================================================

setlocal EnableDelayedExpansion

REM ── 1. Load VPS_USER and VPS_HOST from .env if present ──────
set VPS_USER=
set VPS_HOST=
if exist .env (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if /I "%%A"=="VPS_USER" set VPS_USER=%%B
        if /I "%%A"=="VPS_HOST" set VPS_HOST=%%B
    )
)

if "!VPS_USER!"=="" (
    set /p VPS_USER="Enter VPS username (e.g. ubuntu): "
)
if "!VPS_HOST!"=="" (
    set /p VPS_HOST="Enter VPS IP or hostname: "
)

set REMOTE=!VPS_USER!@!VPS_HOST!:/opt/ascent/

echo.
echo  Uploading to !REMOTE!
echo  (skipping .env  keys.json  data/  __pycache__  *.pyc)
echo.

REM ── 2. Rsync ──────────────────────────────────────────────
rsync -avz --progress ^--exclude='.env' ^--exclude='keys.json' ^--exclude='data/' ^--exclude='__pycache__/' ^--exclude='*.pyc' ^--exclude='.git/' . !REMOTE!

if errorlevel 1 (
    echo.
    echo  ERROR: rsync failed. Check SSH access and try again.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Upload complete. Now do these steps on the VPS:
echo  ============================================================
echo.
echo  1. ssh !VPS_USER!@!VPS_HOST!
echo  2. cd /opt/ascent ^&^& source venv/bin/activate
echo  3. pip install -r requirements.txt
echo  4. sudo systemctl restart ascent
echo  5. sudo systemctl status  ascent
echo.
echo  (If you run the scalper separately:)
echo  6. sudo systemctl restart ascent-scalper
echo.
pause
