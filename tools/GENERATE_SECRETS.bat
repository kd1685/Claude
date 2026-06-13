@echo off
REM ============================================================
REM  ASCENT TERMINAL - generate all three secrets for .env
REM  Copy each value into platform\.env on the SERVER (nano .env)
REM  then: docker compose up -d --force-recreate
REM ============================================================
echo.
echo  TV_WEBHOOK_SECRET (protects the TradingView receiver - also
echo  paste the SAME value inside each TradingView alert's JSON):
python -c "import secrets; print('    ' + secrets.token_hex(32))"
echo.
echo  EXECUTE_KEY (arms the execution bridge + bots + exits;
echo  you'll type this once into the terminal UI when executing):
python -c "import secrets; print('    ' + secrets.token_hex(32))"
echo.
echo  DATA_KEY (encrypts stored customer emails - KEEP SAFE,
echo  losing it makes stored addresses unreadable):
python -c "from cryptography.fernet import Fernet; print('    ' + Fernet.generate_key().decode())" 2>nul || echo     (run: pip install cryptography  then re-run this)
echo.
pause
