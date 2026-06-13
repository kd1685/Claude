@echo off
REM ============================================================
REM  ASCENT TERMINAL — REPO ORGANISER
REM  Cleans up temp files and verifies the repo structure.
REM ============================================================

title Ascent Terminal — Organiser
color 0B

echo.
echo  ╔════════════════════════════════════════╗
echo  ║   ASCENT TERMINAL — REPO ORGANISER   ║
echo  ╚════════════════════════════════════════╝
echo.

REM ── 1. Remove Python cache ──────────────────────────────────
echo [1/6] Removing __pycache__ directories...
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" (
        rd /s /q "%%d"
        echo   Removed: %%d
    )
)
echo  Done.
echo.

REM ── 2. Remove .pyc files ────────────────────────────────────
echo [2/6] Removing .pyc files...
for /r . %%f in (*.pyc) do (
    del /q "%%f"
    echo   Removed: %%f
)
echo  Done.
echo.

REM ── 3. Remove old log files ─────────────────────────────────
echo [3/6] Removing .log files...
for /r . %%f in (*.log) do (
    del /q "%%f"
    echo   Removed: %%f
)
echo  Done.
echo.

REM ── 4. Remove temp / swap files ────────────────────────────
echo [4/6] Removing temp files...
for /r . %%f in (*.tmp *.bak ~$*) do (
    del /q "%%f"
    echo   Removed: %%f
)
echo  Done.
echo.

REM ── 5. Verify required directories exist ───────────────────
echo [5/6] Verifying directory structure...
set MISSING=0
for %%d in (bots brain discord forward installer legal server_launcher tools whop_patreon) do (
    if not exist %%d\ (
        echo   MISSING: %%d\
        set MISSING=1
    ) else (
        echo   OK: %%d\
    )
)
if %MISSING%==1 (
    echo.
    echo  WARNING: Some directories are missing. Check the repo.
) else (
    echo  All directories present.
)
echo.

REM ── 6. Show git status ──────────────────────────────────────
echo [6/6] Git status...
git status --short
echo.

echo  ══════════════════════════════════════════
echo   Organise complete.
echo  ══════════════════════════════════════════
echo.
pause
