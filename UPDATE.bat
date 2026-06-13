@echo off
REM ============================================================
REM  ASCENT TERMINAL — UPDATE SCRIPT
REM  Run this whenever you want to pull the latest version.
REM ============================================================

title Ascent Terminal — Updater
color 0A

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   ASCENT TERMINAL — UPDATE SCRIPT   ║
echo  ╚══════════════════════════════════════╝
echo.

REM ── 1. Pull latest code ─────────────────────────────────────
echo [1/4] Pulling latest code from GitHub...
git pull origin main
if errorlevel 1 (
    echo  ERROR: git pull failed. Check your internet connection.
    pause
    exit /b 1
)
echo  Done.
echo.

REM ── 2. Upgrade pip ──────────────────────────────────────────
echo [2/4] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo  Done.
echo.

REM ── 3. Install / upgrade dependencies ───────────────────────
echo [3/4] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  ERROR: pip install failed. See output above.
    pause
    exit /b 1
)
echo  Done.
echo.

REM ── 4. Check .env exists ────────────────────────────────────
echo [4/4] Checking environment...
if not exist .env (
    echo  WARNING: .env file not found.
    echo  Copy .env.example to .env and fill in your credentials.
) else (
    echo  .env found.
)
echo.

echo  ══════════════════════════════════════
echo   Update complete! You are up to date.
echo  ══════════════════════════════════════
echo.
pause
