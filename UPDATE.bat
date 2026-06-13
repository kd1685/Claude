@echo off
REM ════════════════════════════════════════════════
REM  UPDATE.bat  —  AscentTerminal  (Windows)
REM  Pull latest code + restart the server
REM ════════════════════════════════════════════════

echo.
echo ════════════════════════════════
echo  AscentTerminal Updater
echo ════════════════════════════════
echo.

REM ── 1. Pull latest from GitHub ──────────────────
echo [1/4] Pulling latest from GitHub...
git pull origin main
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: git pull failed.  Check your internet connection.
    pause
    exit /b 1
)
echo Done.
echo.

REM ── 2. Install / upgrade Python deps ────────────
echo [2/4] Installing Python dependencies...
pip install -r requirements.txt -q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed.  Is Python on your PATH?
    pause
    exit /b 1
)
echo Done.
echo.

REM ── 3. Kill any existing uvicorn ────────────────
echo [3/4] Stopping old server (if running)...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM uvicorn.exe /T >nul 2>&1
echo Done.
echo.

REM ── 4. Start the server ─────────────────────────
echo [4/4] Starting AscentTerminal server...
echo       URL: http://localhost:8000
echo.
uvicorn platform.main:app --host 0.0.0.0 --port 8000

REM (window stays open so you can see errors)
pause
