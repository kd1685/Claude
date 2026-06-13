@echo off
echo Starting organiser...
echo Log: %USERPROFILE%\Desktop\organise_log.txt
echo.

REM ════════════════════════════════════════════════
REM  organise.bat  —  AscentTerminal  (Windows)
REM  Move stray files to the right folders
REM  Safe to re-run; only moves known files.
REM ════════════════════════════════════════════════

setlocal enabledelayedexpansion
set LOG=%~dp0organise_log.txt
set MOVED=0
set SKIPPED=0

echo [%DATE% %TIME%] organise.bat started >> "%LOG%"

REM ── Create target dirs if missing ───────────────
if not exist "%~dp0bots" mkdir "%~dp0bots" && echo Created bots/ >> "%LOG%"
if not exist "%~dp0brain" mkdir "%~dp0brain" && echo Created brain/ >> "%LOG%"

REM ════════════════════════════════════════════════
REM  Files that belong in  bots/
REM ════════════════════════════════════════════════

for %%F in (
    "scalper_bot.py"
    "rok_bot.py"
    "grid_bot.py"
    "dca_bot.py"
    "arb_bot.py"
) do (
    if exist "%~dp0%%~F" (
        move /Y "%~dp0%%~F" "%~dp0bots\%%~F" >nul
        echo Moved %%~F  ->  bots/ >> "%LOG%"
        echo   ✓  %%~F  ->  bots/
        set /A MOVED+=1
    ) else (
        set /A SKIPPED+=1
    )
)

REM ════════════════════════════════════════════════
REM  Files that belong in  brain/
REM ════════════════════════════════════════════════

for %%F in (
    "edge_lab.py"
    "mexc_trend_bot.py"
    "swing_backtest.py"
    "RUN_EDGE_LAB.bat"
    "edge_lab.bat"
    "research.py"
    "backtest.py"
    "walk_forward.py"
    "signal_audit.py"
) do (
    if exist "%~dp0%%~F" (
        move /Y "%~dp0%%~F" "%~dp0brain\%%~F" >nul
        echo Moved %%~F  ->  brain/ >> "%LOG%"
        echo   ✓  %%~F  ->  brain/
        set /A MOVED+=1
    ) else (
        set /A SKIPPED+=1
    )
)

REM ════════════════════════════════════════════════
REM  Docs: move stray .md / .txt to docs/ (optional)
REM  Commented out — uncomment if you want this.
REM ════════════════════════════════════════════════

REM if not exist "%~dp0docs" mkdir "%~dp0docs"
REM for %%F in ("HANDOFF.md" "UPDATE_NOTES.md" "LAUNCH_PLAN.txt") do (
REM     if exist "%~dp0%%~F" (
REM         move /Y "%~dp0%%~F" "%~dp0docs\%%~F" >nul
REM         echo Moved %%~F  ->  docs/ >> "%LOG%"
REM         echo   moved %%~F  ->  docs/
REM     )
REM )

REM ════════════════════════════════════════════════
REM  Summary
REM ════════════════════════════════════════════════

echo.
echo ──────────────────────────────────
echo  Done.  Moved: !MOVED!   Skipped: !SKIPPED!
echo  Log: %~dp0organise_log.txt
echo ──────────────────────────────────
echo [%DATE% %TIME%] Done. Moved: !MOVED! Skipped: !SKIPPED! >> "%LOG%"

pause
