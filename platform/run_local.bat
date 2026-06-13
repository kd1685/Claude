@echo off
REM run_local.bat — Start Ascent Terminal locally on Windows (no Docker)
REM
REM Requirements: Python 3.11+ in PATH, pip installed
REM
REM Usage: double-click this file or run from a terminal.

echo [Ascent Terminal] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

echo [Ascent Terminal] Installing dependencies...
pip install -r requirements.txt --quiet

echo [Ascent Terminal] Starting server on http://localhost:8000
uvicorn auth:app --host 0.0.0.0 --port 8000 --reload

pause
