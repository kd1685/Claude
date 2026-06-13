@echo off
REM ============================================================
REM  ASCENT TERMINAL - EDGE LAB LAUNCHER
REM  Double-click this file to run edge_lab.py
REM  Requires Python 3.11+ with pandas, numpy, requests installed
REM ============================================================

echo.
echo  Ascent Terminal — Edge Lab
echo  ===========================
echo.

REM Check Python is available
where python >nul 2>&1
if %errorlevel% NEQ 0 (
    echo  ERROR: Python not found.
    echo  Install from https://python.org and tick "Add to PATH".
    pause
    exit /b 1
)

REM Install deps if missing (silent)
python -m pip install --quiet pandas numpy requests tqdm 2>nul

REM Run the lab
echo  Starting edge_lab.py ...
echo.
python "%~dp0edge_lab.py"

echo.
echo  Edge Lab exited.
pause
