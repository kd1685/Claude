@echo off
REM Double-click to start the Kingdom 1685 PC agent.
cd /d "%~dp0\.."
echo Starting Kingdom 1685 agent...
python agent\agent.py
echo.
echo Agent stopped. Press any key to close.
pause >nul
