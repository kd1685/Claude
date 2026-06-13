@echo off
REM ============================================================
REM  ASCENT TERMINAL - upload to the VPS and rebuild (SAFE)
REM  FIRST TIME: edit the SERVER line below with your VPS IP.
REM  Stages a copy that EXCLUDES your local .env, keys.json and
REM  data\ so the server's live settings/keys/database are never
REM  overwritten. Uses Windows 10/11 built-in ssh/scp + robocopy.
REM ============================================================
set SERVER=root@YOUR_SERVER_IP

if "%SERVER%"=="root@YOUR_SERVER_IP" (
  echo  Edit this file first: set SERVER to your real VPS IP.
  pause & exit /b 1
)
cd /d "%~dp0\.."
set STAGE=%TEMP%\AscentDeploy
if exist "%STAGE%" rmdir /s /q "%STAGE%"
echo  Staging a clean copy (excluding .env / keys.json / data / certs)...
robocopy . "%STAGE%" /E /NFL /NDL /NJH /NJS ^
  /XF .env keys.json *.pyc ^
  /XD data __pycache__ certs .pytest_cache edge_cache node_modules >nul
if errorlevel 8 ( echo  Staging failed. & pause & exit /b 1 )
echo  Uploading to %SERVER% ...
scp -r "%STAGE%\platform" "%STAGE%\brain" "%STAGE%\forward" "%STAGE%\discord" "%STAGE%\legal" "%STAGE%\whop_patreon" "%STAGE%\GO_LIVE_STEPS.md" %SERVER%:/root/AscentTerminal/
if errorlevel 1 ( echo  Upload failed - check IP / SSH access. & pause & exit /b 1 )
echo  Rebuilding containers (also picks up server-side .env changes)...
ssh %SERVER% "cd /root/AscentTerminal/platform && docker compose up -d --build && docker compose ps"
rmdir /s /q "%STAGE%"
echo.
echo  Done. Open https://ascentterminal.com and run the GO_LIVE_STEPS checks.
pause
