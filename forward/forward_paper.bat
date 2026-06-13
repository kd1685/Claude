@echo off
REM Record one day of the forward paper track record for the EMA30 trend strategy.
REM Run this ONCE a day (or run forward_paper.py --loop to leave it running).
cd /d "%~dp0"
pip install requests
python forward_paper.py
echo.
echo Done. Today's step is logged to forward_log.csv.
echo Tip: to leave it running and auto-update daily, run:  python forward_paper.py --loop
pause
