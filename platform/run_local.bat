@echo off
cd /d "%~dp0"

echo ============================================================
echo  Installing dependencies (first run only takes a minute)...
echo ============================================================
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  ERROR: pip install failed. Make sure Python is installed and on PATH.
    echo  Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Freeing port 8000 if something is already using it...
echo ============================================================
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    echo  Killing PID %%a on port 8000...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

set ACCESS_KEYS=DEMO-KEY
echo.
echo ============================================================
echo  Ascent Terminal starting...
echo  Open in your browser:   http://localhost:8000
echo  Unlock live signals with the access key:   DEMO-KEY
echo  (First load fetches history for the proof panel - give it ~30s)
echo  Press Ctrl+C here to stop.
echo ============================================================
echo.
python -m uvicorn app:app --port 8000
pause
