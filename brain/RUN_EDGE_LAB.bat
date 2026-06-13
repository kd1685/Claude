@echo off
REM ============================================================
REM  ASCENT TERMINAL - RUN EDGE LAB
REM  Double-click this file to run the full walk-forward backtest.
REM  Results land in brain/edge_results.csv
REM  An HTML report is also generated: brain/edge_report.html
REM ============================================================

cd /d "%~dp0"

REM Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ and add to PATH.
    pause
    exit /b 1
)

REM Install / upgrade dependencies silently
python -m pip install --quiet --upgrade ccxt pandas numpy scipy ta

echo.
echo  Running edge lab backtest...
echo  This may take 10-30 minutes depending on your machine.
echo.

python edge_lab.py

if errorlevel 1 (
    echo.
    echo  ERROR: edge_lab.py exited with an error. Check output above.
    pause
    exit /b 1
)

echo.
echo  Backtest complete!
echo  Results: brain\edge_results.csv
echo  Report:  brain\edge_report.html
echo.

REM Open HTML report if it exists
if exist edge_report.html (
    start edge_report.html
)

pause
