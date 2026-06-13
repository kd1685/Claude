@echo off
REM ============================================================
REM  ASCENT TERMINAL - UPDATE SCRIPT (Windows → VPS)
REM  Edit the three variables below, then double-click this file.
REM ============================================================

set VPS_HOST=YOUR_VPS_IP_OR_HOSTNAME
set VPS_USER=root
set REMOTE_PATH=/root/ascent_terminal

REM ---- nothing to edit below this line ----------------------

echo.
echo  Ascent Terminal — deploying update to %VPS_HOST% ...
echo.

REM Try WSL rsync first (fast, incremental)
where wsl >nul 2>&1
if %errorlevel%==0 (
    echo  Using WSL rsync ...
    wsl rsync -avz --exclude='.env' --exclude='keys.json' --exclude='platform/data/' --exclude='__pycache__' --exclude='*.pyc' ./ %VPS_USER%@%VPS_HOST%:%REMOTE_PATH%/
    goto restart
)

REM Fall back to plain scp (copies everything; .env is excluded via .gitignore logic — but scp has no exclude so we skip the secrets manually)
echo  WSL not found — using scp (slower) ...
echo  WARNING: make sure .env and keys.json are NOT in this folder before continuing.
pause
scp -r . %VPS_USER%@%VPS_HOST%:%REMOTE_PATH%/

:restart
echo.
echo  Restarting services on VPS ...
ssh %VPS_USER%@%VPS_HOST% "cd %REMOTE_PATH% && docker compose down && docker compose up -d --build"
echo.
echo  Done.  Visit https://%VPS_HOST%/health to verify.
pause
