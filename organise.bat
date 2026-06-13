@echo off
setlocal enabledelayedexpansion

set LOG=%USERPROFILE%\Downloads\organise_log.txt
echo Starting organiser... > "%LOG%"
echo Log: %LOG%
echo.
echo Starting organiser...

REM ── CONFIG ──────────────────────────────────────────────────────────────────
set SRC=%USERPROFILE%\Downloads
set ARCHIVE=%USERPROFILE%\Downloads\Archive

REM File-type → subfolder mapping  (add more lines to extend)
set EXT[pdf]=Documents
set EXT[docx]=Documents
set EXT[doc]=Documents
set EXT[xlsx]=Documents
set EXT[xls]=Documents
set EXT[pptx]=Documents
set EXT[ppt]=Documents
set EXT[txt]=Documents
set EXT[csv]=Documents

set EXT[jpg]=Images
set EXT[jpeg]=Images
set EXT[png]=Images
set EXT[gif]=Images
set EXT[bmp]=Images
set EXT[svg]=Images
set EXT[webp]=Images
set EXT[heic]=Images

set EXT[mp4]=Videos
set EXT[mov]=Videos
set EXT[avi]=Videos
set EXT[mkv]=Videos
set EXT[wmv]=Videos
set EXT[flv]=Videos
set EXT[webm]=Videos

set EXT[mp3]=Audio
set EXT[wav]=Audio
set EXT[flac]=Audio
set EXT[aac]=Audio
set EXT[ogg]=Audio
set EXT[m4a]=Audio

set EXT[zip]=Archives
set EXT[rar]=Archives
set EXT[7z]=Archives
set EXT[tar]=Archives
set EXT[gz]=Archives
set EXT[iso]=Archives

set EXT[exe]=Installers
set EXT[msi]=Installers
set EXT[dmg]=Installers
set EXT[pkg]=Installers

set EXT[py]=Code
set EXT[js]=Code
set EXT[ts]=Code
set EXT[html]=Code
set EXT[css]=Code
set EXT[json]=Code
set EXT[xml]=Code
set EXT[sh]=Code
set EXT[bat]=Code
set EXT[ps1]=Code

set EXT[torrent]=Torrents

REM ── HELPERS ─────────────────────────────────────────────────────────────────

REM Pad a number to 2 digits
:pad2
set _n=%~1
if %_n% LSS 10 set _n=0%_n%
set PAD2_RESULT=%_n%
goto :eof

REM ── MAIN ────────────────────────────────────────────────────────────────────

REM Get today's date parts
for /f "tokens=1-3 delims=/ " %%a in ("%DATE%") do (
    set _dd=%%a
    set _mm=%%b
    set _yyyy=%%c
)
REM Handle locales that put yyyy first
if "%_yyyy%"=="" (
    for /f "tokens=1-3 delims=/-" %%a in ("%DATE%") do (
        set _yyyy=%%a
        set _mm=%%b
        set _dd=%%c
    )
)
set TODAY=%_yyyy%-%_mm%-%_dd%

echo Date detected: %TODAY% >> "%LOG%"
echo.

REM Move files by extension
for %%F in ("%SRC%\*.*") do (
    REM skip directories
    if not exist "%%F\" (
        set FN=%%~nxF
        set EX=%%~xF
        set EX=!EX:~1!
        REM lower-case extension via temp var trick
        for %%L in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do (
            set EX=!EX:%%L=%%L!
        )

        if defined EXT[!EX!] (
            set DEST=%SRC%\!EXT[!EX!]!
        ) else (
            set DEST=%SRC%\Other
        )

        REM skip if file is the log itself or is in a subfolder
        if /I "%%F" NEQ "%LOG%" (
            if not exist "!DEST!" mkdir "!DEST!"
            echo Moving %%~nxF  →  !DEST! >> "%LOG%"
            move /Y "%%F" "!DEST!\" >nul 2>&1
        )
    )
)

REM Archive files older than 30 days (all type-sorted subfolders)
for /D %%D in ("%SRC%\Documents" "%SRC%\Images" "%SRC%\Videos" "%SRC%\Audio" "%SRC%\Archives" "%SRC%\Installers" "%SRC%\Code" "%SRC%\Other") do (
    if exist "%%D\" (
        for %%F in ("%%D\*.*") do (
            REM forfiles to check age
            forfiles /P "%%D" /M "%%~nxF" /D -30 /C "cmd /c echo @path" >nul 2>&1
            if !errorlevel!==0 (
                set ADEST=%ARCHIVE%\%TODAY%
                if not exist "!ADEST!" mkdir "!ADEST!"
                echo Archiving %%~nxF  →  !ADEST! >> "%LOG%"
                move /Y "%%F" "!ADEST!\" >nul 2>&1
            )
        )
    )
)

echo. >> "%LOG%"
echo Done. >> "%LOG%"
echo.
echo Done!  Check the log at:
echo   %LOG%
pause
