@echo off
REM Reliable updater for the Kingdom 1685 PC agent.
REM Double-click this, or run:  agent\update.bat
REM Downloads the latest code and overwrites it in place. Your agent.env is kept.
cd /d "%~dp0\.."
echo.
echo === Kingdom 1685 agent updater ===
echo Downloading latest code...
curl --ssl-no-revoke -L -o _latest.zip https://github.com/kd1685/claude/archive/refs/heads/main.zip
if errorlevel 1 ( echo Download failed. & pause & exit /b 1 )
echo Extracting...
if exist claude-main rmdir /S /Q claude-main
tar -xf _latest.zip
if errorlevel 1 ( echo Extract failed. & pause & exit /b 1 )
echo Updating files (your agent.env is preserved)...
robocopy claude-main . /E /XF agent.env /NFL /NDL /NJH /NJS /NP >nul
rmdir /S /Q claude-main
del _latest.zip
echo.
echo Done.  Now restart the agent:   python agent\agent.py
echo (It should print version 2026.06.04-verify-close or newer.)
pause
