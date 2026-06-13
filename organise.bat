@echo off
echo Starting organiser...
echo Log: %USERPROFILE%\Downloads\organise_log.txt
echo. > "%USERPROFILE%\Downloads\organise_log.txt"
echo Started at %date% %time% >> "%USERPROFILE%\Downloads\organise_log.txt"

set DL=%USERPROFILE%\Downloads
set ROOT=%USERPROFILE%\Downloads\AscentTerminal

echo Source folder: %DL% >> "%USERPROFILE%\Downloads\organise_log.txt"
echo Dest folder:   %ROOT% >> "%USERPROFILE%\Downloads\organise_log.txt"
echo. >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Creating folders...
mkdir "%ROOT%"                       2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\platform"              2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\platform\static"       2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\platform\desktop"      2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\forward"               2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\discord"               2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\legal"                 2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\whop_patreon"          2>>"%USERPROFILE%\Downloads\organise_log.txt"
mkdir "%ROOT%\brain"                 2>>"%USERPROFILE%\Downloads\organise_log.txt"

echo Copying platform files...
echo [platform] >> "%USERPROFILE%\Downloads\organise_log.txt"

if exist "%DL%\app (3).py"       copy /Y "%DL%\app (3).py"       "%ROOT%\platform\app.py"            >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\app.py"           copy /Y "%DL%\app.py"           "%ROOT%\platform\app.py"            >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\exchanges.py"     copy /Y "%DL%\exchanges.py"     "%ROOT%\platform\exchanges.py"      >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\requirements (1).txt" copy /Y "%DL%\requirements (1).txt" "%ROOT%\platform\requirements.txt" >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\requirements.txt" copy /Y "%DL%\requirements.txt" "%ROOT%\platform\requirements.txt"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\run_local (1).bat" copy /Y "%DL%\run_local (1).bat" "%ROOT%\platform\run_local.bat"   >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\run_local.bat"    copy /Y "%DL%\run_local.bat"    "%ROOT%\platform\run_local.bat"     >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\Dockerfile"       copy /Y "%DL%\Dockerfile"       "%ROOT%\platform\Dockerfile"        >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\Caddyfile"        copy /Y "%DL%\Caddyfile"        "%ROOT%\platform\Caddyfile"         >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\env.example"      copy /Y "%DL%\env.example"      "%ROOT%\platform\env.example"       >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\dockerignore"     copy /Y "%DL%\dockerignore"     "%ROOT%\platform\.dockerignore"     >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\dockercompose.yml" copy /Y "%DL%\dockercompose.yml" "%ROOT%\platform\docker-compose.yml" >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\DEPLOY.md"        copy /Y "%DL%\DEPLOY.md"        "%ROOT%\platform\DEPLOY.md"         >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\START_HERE.md"    copy /Y "%DL%\START_HERE.md"    "%ROOT%\platform\START_HERE.md"     >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\static\index.html" copy /Y "%DL%\static\index.html" "%ROOT%\platform\static\index.html" >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\index.html"       copy /Y "%DL%\index.html"       "%ROOT%\platform\static\index.html" >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\ascent_desktop.py"  copy /Y "%DL%\ascent_desktop.py"  "%ROOT%\platform\desktop\ascent_desktop.py"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\build_desktop.bat" copy /Y "%DL%\build_desktop.bat" "%ROOT%\platform\desktop\build_desktop.bat" >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Copying forward files...
echo [forward] >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\forward_paper.py"    copy /Y "%DL%\forward_paper.py"    "%ROOT%\forward\forward_paper.py"    >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\forward_paper.bat"   copy /Y "%DL%\forward_paper.bat"   "%ROOT%\forward\forward_paper.bat"   >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\forward_state.json"  copy /Y "%DL%\forward_state.json"  "%ROOT%\forward\forward_state.json"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\forward_log.csv"     copy /Y "%DL%\forward_log.csv"     "%ROOT%\forward\forward_log.csv"     >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Copying discord files...
echo [discord] >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\discord_post_content.py"  copy /Y "%DL%\discord_post_content.py"  "%ROOT%\discord\discord_post_content.py"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\add_alerts_channel.py"    copy /Y "%DL%\add_alerts_channel.py"    "%ROOT%\discord\add_alerts_channel.py"    >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\discord_role_sync.py"     copy /Y "%DL%\discord_role_sync.py"     "%ROOT%\discord\discord_role_sync.py"     >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\role_sync_setup.bat"      copy /Y "%DL%\role_sync_setup.bat"      "%ROOT%\discord\role_sync_setup.bat"      >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\PATREON_DISCORD_SETUP.md" copy /Y "%DL%\PATREON_DISCORD_SETUP.md" "%ROOT%\discord\PATREON_DISCORD_SETUP.md" >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Copying legal files...
echo [legal] >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\DISCLAIMER (1).md"  copy /Y "%DL%\DISCLAIMER (1).md"  "%ROOT%\legal\DISCLAIMER.md"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\DISCLAIMER.md"      copy /Y "%DL%\DISCLAIMER.md"      "%ROOT%\legal\DISCLAIMER.md"  >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\TERMS (1).md"       copy /Y "%DL%\TERMS (1).md"       "%ROOT%\legal\TERMS.md"       >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\TERMS.md"           copy /Y "%DL%\TERMS.md"           "%ROOT%\legal\TERMS.md"       >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\PRIVACY.md"         copy /Y "%DL%\PRIVACY.md"         "%ROOT%\legal\PRIVACY.md"     >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Copying whop/patreon files...
echo [whop_patreon] >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\whop_ai_prompts.md"       copy /Y "%DL%\whop_ai_prompts.md"       "%ROOT%\whop_patreon\whop_ai_prompts.md"       >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\patreon_setup_prompts.md" copy /Y "%DL%\patreon_setup_prompts.md" "%ROOT%\whop_patreon\patreon_setup_prompts.md" >> "%USERPROFILE%\Downloads\organise_log.txt"

echo Copying brain files...
echo [brain] >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\swing_oos_wide.py"      copy /Y "%DL%\swing_oos_wide.py"      "%ROOT%\brain\swing_oos_wide.py"      >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\swing_oos_wide-edit.py" copy /Y "%DL%\swing_oos_wide-edit.py" "%ROOT%\brain\swing_oos_wide-edit.py" >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\swing_voltarget.py"     copy /Y "%DL%\swing_voltarget.py"     "%ROOT%\brain\swing_voltarget.py"     >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\swing_oos.py"           copy /Y "%DL%\swing_oos.py"           "%ROOT%\brain\swing_oos.py"           >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\swing_backtest.py"      copy /Y "%DL%\swing_backtest.py"      "%ROOT%\brain\swing_backtest.py"      >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\mexc_trend_bot (3).py"  copy /Y "%DL%\mexc_trend_bot (3).py"  "%ROOT%\brain\mexc_trend_bot.py"      >> "%USERPROFILE%\Downloads\organise_log.txt"
if exist "%DL%\mexc_trend_bot.py"      copy /Y "%DL%\mexc_trend_bot.py"      "%ROOT%\brain\mexc_trend_bot.py"      >> "%USERPROFILE%\Downloads\organise_log.txt"

echo. >> "%USERPROFILE%\Downloads\organise_log.txt"
echo Finished at %date% %time% >> "%USERPROFILE%\Downloads\organise_log.txt"

echo.
echo ============================================================
echo  Done! Check organise_log.txt in your Downloads for details.
echo  Your project is at: %ROOT%
echo.
echo  To test: open AscentTerminal\platform\ and run run_local.bat
echo ============================================================
echo.
pause
