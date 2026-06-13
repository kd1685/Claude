@echo off
REM  ASCENT TERMINAL - pre-deploy test suite (expect: 17 passed)
cd /d "%~dp0\..\platform"
python -m pytest tests -q
if errorlevel 1 (
  echo.
  echo  *** TESTS FAILED - DO NOT DEPLOY. Screenshot this to Claude. ***
) else (
  echo.
  echo  All green - safe to deploy.
)
pause
