@echo off
REM  ASCENT TERMINAL - issue a subscriber key (shown ONCE - copy it!)
cd /d "%~dp0\..\platform"
set /p TIER="  Tier (observer / operator / architect): "
set /p DAYS="  Days valid (e.g. 31): "
set /p NOTE="  Note (e.g. 'whop sub 123' - NO real names/emails): "
python key_gen.py new --tier %TIER% --days %DAYS% --note "%NOTE%"
echo.
echo  Key takes effect IMMEDIATELY (hot reload - no restart).
pause
