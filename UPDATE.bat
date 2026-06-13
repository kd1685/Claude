@echo off
REM ============================================================
REM  ASCENT TERMINAL - UPDATE EVERYTHING
REM  Run this from inside the new AscentTerminal folder.
REM  It will:
REM    1. Find your old install (ApexTerminal_v4 / AscentTerminal)
REM    2. Carry over your settings (.env), subscriber keys
REM       (keys.json) and database (data\) so nothing is lost
REM    3. Install / update all Python dependencies (incl. ccxt,
REM       yfinance for live data and the bots)
REM    4. Offer to launch the terminal
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ===========================================================
echo   ASCENT TERMINAL - UPDATER
echo  ===========================================================
echo.

REM ---- 1. Locate the old install ------------------------------
set "OLD="
for %%P in (
  "%USERPROFILE%\Downloads\ApexTerminal_v4"
  "%USERPROFILE%\Desktop\ApexTerminal_v4"
  "%USERPROFILE%\Documents\ApexTerminal_v4"
  "..\ApexTerminal_v4"
  "%USERPROFILE%\Downloads\AscentTerminal_old"
) do (
  if exist "%%~P\platform" if not defined OLD set "OLD=%%~P"
)

if not defined OLD (
  echo  Could not auto-find your previous install.
  echo  If you HAVE one, type its full path now ^(the folder that
  echo  contains "platform"^). If this is a fresh install, just
  echo  press ENTER to skip.
  echo.
  set /p OLD="  Old install path (or ENTER to skip): "
)

REM ---- 2. Carry over state ------------------------------------
if defined OLD if exist "%OLD%\platform" (
  echo.
  echo  Migrating your data from: %OLD%
  if exist "%OLD%\platform\.env" (
    copy /Y "%OLD%\platform\.env" "platform\.env" >nul
    echo    + .env            ^(your settings / secrets^)
  )
  if exist "%OLD%\platform\keys.json" (
    copy /Y "%OLD%\platform\keys.json" "platform\keys.json" >nul
    echo    + keys.json       ^(subscriber keys - all still valid^)
  )
  if exist "%OLD%\platform\data" (
    xcopy /E /I /Y "%OLD%\platform\data" "platform\data" >nul
    echo    + data\           ^(alerts, execution log, bot state^)
  )
  echo  Migration done. Your old folder was NOT modified - delete
  echo  it yourself once you're happy the new version works.
) else (
  echo  No previous install migrated ^(fresh setup^).
)

REM ---- 3. Dependencies ----------------------------------------
echo.
echo  Installing / updating dependencies...
pip install -r platform\requirements.txt
if errorlevel 1 (
  echo.
  echo  ERROR: pip failed. Install Python from python.org ^(tick
  echo  "Add python.exe to PATH"^) and run this again.
  pause & exit /b 1
)
pip install ccxt yfinance
echo  Dependencies OK.

REM ---- 4. Launch? ---------------------------------------------
echo.
choice /M "  Launch Ascent Terminal now"
if errorlevel 2 goto done
cd platform
call run_local.bat
exit /b 0

:done
echo.
echo  All updated. Start any time with:  platform\run_local.bat
echo  Next: open LAUNCH_PLAN.txt for the full go-live steps.
pause
