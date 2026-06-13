@echo off
REM ============================================================
REM  ASCENT TERMINAL - EDGE LAB (owner research tool)
REM  Double-click me. Runs from this folder automatically.
REM ============================================================
cd /d "%~dp0"
python -c "import ccxt" 2>nul || (
  echo  Installing ccxt...
  pip install ccxt || ( echo  pip failed - install Python from python.org & pause & exit /b 1 )
)

echo.
echo  EDGE LAB - what do you want to run?
echo    1 ^| single  - every indicator alone (fast first look)
echo    2 ^| pairs   - all indicator pairs x weight ratios
echo    3 ^| random  - random search (the workhorse)
echo    4 ^| greedy  - forward selection on TRAIN only
echo    5 ^| full    - all of the above in order (long)
echo    6 ^| top     - show the leaderboard from previous runs
echo.
set /p MODE="  Choice (1-6): "
if "%MODE%"=="6" ( python edge_lab.py top & pause & exit /b 0 )

set /p SYMS="  Symbols - list or topN e.g. top10 [BTC_USDT,ETH_USDT,SOL_USDT]: "
if "%SYMS%"=="" set SYMS=BTC_USDT,ETH_USDT,SOL_USDT
set /p TF="  Timeframe 1d/4h/1h/15m/5m/3d/1w [1d]: "
if "%TF%"=="" set TF=1d
set /p BARS="  Bars of history [900]: "
if "%BARS%"=="" set BARS=900
set /p EXCH="  Exchange [binance] (try mexc if fetch fails): "
if "%EXCH%"=="" set EXCH=binance

set EXTRA=
if "%MODE%"=="3" (
  set /p TRIALS="  Trials [20000]: "
  if "!TRIALS!"=="" set TRIALS=20000
)
setlocal enabledelayedexpansion
if "%MODE%"=="1" python edge_lab.py single --symbols %SYMS% --tf %TF% --bars %BARS% --exchange %EXCH%
if "%MODE%"=="2" python edge_lab.py pairs  --symbols %SYMS% --tf %TF% --bars %BARS% --exchange %EXCH%
if "%MODE%"=="3" python edge_lab.py random --trials %TRIALS% --symbols %SYMS% --tf %TF% --bars %BARS% --exchange %EXCH%
if "%MODE%"=="4" python edge_lab.py greedy --symbols %SYMS% --tf %TF% --bars %BARS% --exchange %EXCH%
if "%MODE%"=="5" python edge_lab.py full --trials 20000 --symbols %SYMS% --tf %TF% --bars %BARS% --exchange %EXCH%
echo.
echo  Results saved to edge_results.csv - run choice 6 anytime for the leaderboard.
pause
