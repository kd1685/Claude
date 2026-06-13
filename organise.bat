@echo off
echo Starting organiser...
echo Log: %USERPROFILE%\Downloads\organise_log.txt
echo. > "%USERPROFILE%\Downloads\organise_log.txt"
echo Started at %date% %time% >> "%USERPROFILE%\Downloads\organise_log.txt"

REM ── Folder definitions ──────────────────────────────────────────────────────
set IMAGES=%USERPROFILE%\Downloads\Images
set DOCS=%USERPROFILE%\Downloads\Documents
set VIDS=%USERPROFILE%\Downloads\Videos
set AUDIO=%USERPROFILE%\Downloads\Audio
set ARCHIVES=%USERPROFILE%\Downloads\Archives
set INSTALLERS=%USERPROFILE%\Downloads\Installers
set CODE=%USERPROFILE%\Downloads\Code
set MISC=%USERPROFILE%\Downloads\Misc

REM ── Create folders if missing ─────────────────────────────────────────────
for %%D in ("%IMAGES%" "%DOCS%" "%VIDS%" "%AUDIO%" "%ARCHIVES%" "%INSTALLERS%" "%CODE%" "%MISC%") do (
    if not exist "%%~D" mkdir "%%~D"
)

REM ── Move files by extension ─────────────────────────────────────────────────

REM Images
for %%F in (
    "%USERPROFILE%\Downloads\*.jpg"
    "%USERPROFILE%\Downloads\*.jpeg"
    "%USERPROFILE%\Downloads\*.png"
    "%USERPROFILE%\Downloads\*.gif"
    "%USERPROFILE%\Downloads\*.bmp"
    "%USERPROFILE%\Downloads\*.webp"
    "%USERPROFILE%\Downloads\*.svg"
    "%USERPROFILE%\Downloads\*.ico"
    "%USERPROFILE%\Downloads\*.tiff"
    "%USERPROFILE%\Downloads\*.heic"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Images >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%IMAGES%\" >nul
    )
)

REM Documents
for %%F in (
    "%USERPROFILE%\Downloads\*.pdf"
    "%USERPROFILE%\Downloads\*.doc"
    "%USERPROFILE%\Downloads\*.docx"
    "%USERPROFILE%\Downloads\*.xls"
    "%USERPROFILE%\Downloads\*.xlsx"
    "%USERPROFILE%\Downloads\*.ppt"
    "%USERPROFILE%\Downloads\*.pptx"
    "%USERPROFILE%\Downloads\*.txt"
    "%USERPROFILE%\Downloads\*.csv"
    "%USERPROFILE%\Downloads\*.md"
    "%USERPROFILE%\Downloads\*.odt"
    "%USERPROFILE%\Downloads\*.ods"
    "%USERPROFILE%\Downloads\*.rtf"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Documents >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%DOCS%\" >nul
    )
)

REM Videos
for %%F in (
    "%USERPROFILE%\Downloads\*.mp4"
    "%USERPROFILE%\Downloads\*.mkv"
    "%USERPROFILE%\Downloads\*.avi"
    "%USERPROFILE%\Downloads\*.mov"
    "%USERPROFILE%\Downloads\*.wmv"
    "%USERPROFILE%\Downloads\*.flv"
    "%USERPROFILE%\Downloads\*.webm"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Videos >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%VIDS%\" >nul
    )
)

REM Audio
for %%F in (
    "%USERPROFILE%\Downloads\*.mp3"
    "%USERPROFILE%\Downloads\*.wav"
    "%USERPROFILE%\Downloads\*.flac"
    "%USERPROFILE%\Downloads\*.aac"
    "%USERPROFILE%\Downloads\*.ogg"
    "%USERPROFILE%\Downloads\*.m4a"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Audio >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%AUDIO%\" >nul
    )
)

REM Archives
for %%F in (
    "%USERPROFILE%\Downloads\*.zip"
    "%USERPROFILE%\Downloads\*.rar"
    "%USERPROFILE%\Downloads\*.7z"
    "%USERPROFILE%\Downloads\*.tar"
    "%USERPROFILE%\Downloads\*.gz"
    "%USERPROFILE%\Downloads\*.bz2"
    "%USERPROFILE%\Downloads\*.xz"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Archives >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%ARCHIVES%\" >nul
    )
)

REM Installers
for %%F in (
    "%USERPROFILE%\Downloads\*.exe"
    "%USERPROFILE%\Downloads\*.msi"
    "%USERPROFILE%\Downloads\*.dmg"
    "%USERPROFILE%\Downloads\*.pkg"
    "%USERPROFILE%\Downloads\*.deb"
    "%USERPROFILE%\Downloads\*.rpm"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Installers >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%INSTALLERS%\" >nul
    )
)

REM Code
for %%F in (
    "%USERPROFILE%\Downloads\*.py"
    "%USERPROFILE%\Downloads\*.js"
    "%USERPROFILE%\Downloads\*.ts"
    "%USERPROFILE%\Downloads\*.html"
    "%USERPROFILE%\Downloads\*.css"
    "%USERPROFILE%\Downloads\*.json"
    "%USERPROFILE%\Downloads\*.xml"
    "%USERPROFILE%\Downloads\*.yaml"
    "%USERPROFILE%\Downloads\*.yml"
    "%USERPROFILE%\Downloads\*.sh"
    "%USERPROFILE%\Downloads\*.bat"
    "%USERPROFILE%\Downloads\*.ps1"
    "%USERPROFILE%\Downloads\*.java"
    "%USERPROFILE%\Downloads\*.cpp"
    "%USERPROFILE%\Downloads\*.c"
    "%USERPROFILE%\Downloads\*.h"
    "%USERPROFILE%\Downloads\*.go"
    "%USERPROFILE%\Downloads\*.rs"
    "%USERPROFILE%\Downloads\*.rb"
    "%USERPROFILE%\Downloads\*.php"
    "%USERPROFILE%\Downloads\*.sql"
    "%USERPROFILE%\Downloads\*.ipynb"
) do (
    if exist "%%F" (
        echo Moving %%~nxF to Code >> "%USERPROFILE%\Downloads\organise_log.txt"
        move /Y "%%F" "%CODE%\" >nul
    )
)

echo.
echo Organise complete. Check the log for details:
echo %USERPROFILE%\Downloads\organise_log.txt
pause
