@echo off
REM Ascent Terminal — Windows installer
REM Run this once before launching ascent_desktop.py

echo.
echo ========================================
echo   Ascent Terminal — Setup
echo ========================================
echo.

REM ---- Check Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Download Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ---- Install Python dependencies ----
echo Installing Python dependencies...
pip install --upgrade pywebview pythonnet
if errorlevel 1 (
    echo.
    echo WARNING: pip install had errors. Trying user install...
    pip install --user --upgrade pywebview pythonnet
)

REM ---- Check .NET Runtime ----
echo.
echo Checking .NET Runtime...
dotnet --list-runtimes >nul 2>&1
if errorlevel 1 (
    echo.
    echo .NET Runtime not found.
    echo Opening download page — install .NET 8 Runtime then re-run this script.
    echo.
    start https://dotnet.microsoft.com/download/dotnet/8.0
    echo After installing .NET 8 Runtime, press any key to continue...
    pause >nul
    REM Re-check
    dotnet --list-runtimes >nul 2>&1
    if errorlevel 1 (
        echo .NET still not detected. Please install it and re-run install.bat.
        pause
        exit /b 1
    )
)

echo .NET Runtime OK.
echo.
echo ========================================
echo   Setup complete!
echo   Launch with:  python ascent_desktop.py
echo ========================================
echo.
pause
