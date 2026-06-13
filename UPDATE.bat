@echo off
REM UPDATE.bat — migrate from old ROK bot to AscentTerminal, or update between AT versions.
REM Run this from the AscentTerminal folder.

cd /d "%~dp0"

echo ============================================================
echo  AscentTerminal — update / first-run setup
echo ============================================================
echo.

REM ── 1. Install / upgrade Python dependencies ─────────────────────────────
echo [1/5] Installing Python dependencies...
pip install -r platform\requirements.txt
if errorlevel 1 (
    echo.
    echo  ERROR: pip install failed. Make sure Python 3.10+ is on PATH.
    pause & exit /b 1
)
echo  Done.
echo.

REM ── 2. Migrate old ROK bot .env if present ───────────────────────────────
echo [2/5] Checking for old ROK bot config...
if exist "..\rok_bot\.env" (
    echo  Found ..\rok_bot\.env — migrating values to platform\.env ...
    python organise.bat --migrate-env ..\rok_bot\.env platform\.env
    echo  Migration done. Review platform\.env before launching.
) else if exist "platform\.env" (
    echo  platform\.env already exists — skipping migration.
) else (
    echo  No old .env found — copying .env.example to platform\.env
    copy platform\.env.example platform\.env
    echo  IMPORTANT: edit platform\.env before going live.
)
echo.

REM ── 3. Migrate old keys.json if present ──────────────────────────────────
echo [3/5] Checking for existing keys.json...
if exist "..\rok_bot\keys.json" (
    echo  Copying ..\rok_bot\keys.json → platform\keys.json
    copy /Y "..\rok_bot\keys.json" "platform\keys.json"
) else (
    echo  No old keys.json found — a fresh one will be created on first run.
)
echo.

REM ── 4. Migrate old data/ if present ──────────────────────────────────────
echo [4/5] Checking for existing data directory...
if exist "..\rok_bot\data" (
    echo  Copying ..\rok_bot\data\ → platform\data\
    xcopy /E /I /Y "..\rok_bot\data" "platform\data"
) else (
    echo  No old data\ found — starting fresh.
)
echo.

REM ── 5. Launch ─────────────────────────────────────────────────────────────
echo [5/5] Ready to launch.
echo.
set /p LAUNCH="Launch AscentTerminal now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    python server_launcher\ascent_server.py
) else (
    echo  Run  python server_launcher\ascent_server.py  when ready.
)

pause
