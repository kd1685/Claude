@echo off
REM  ASCENT TERMINAL - revoke a key (paste the key or its hash prefix)
cd /d "%~dp0\..\platform"
set /p K="  Key (or hash prefix from key_gen.py list): "
python key_gen.py revoke --key %K%
python key_gen.py list
pause
