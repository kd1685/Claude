@echo off
REM organise.bat — project-level utility. Wraps Python tasks that
REM are awkward as pure batch. Called by UPDATE.bat for env migration.
REM
REM Usage (direct):
REM   organise.bat --migrate-env <src_env> <dst_env>
REM   organise.bat --list-keys
REM   organise.bat --new-key --tier architect --note "owner"
REM   organise.bat --check-health

cd /d "%~dp0"

if "%1"=="--migrate-env" goto migrate_env
if "%1"=="--list-keys"   goto list_keys
if "%1"=="--new-key"     goto new_key
if "%1"=="--check-health" goto check_health

echo.
echo  organise.bat — available commands:
echo    --migrate-env ^<src^> ^<dst^>   copy/merge .env values into destination
echo    --list-keys                  list all keys in keys.json
echo    --new-key --tier ^<t^> --note ^<n^>  generate a new subscriber key
echo    --check-health               hit /api/health and print the response
echo.
goto end

:migrate_env
REM ── Merge old .env into new one, skipping keys already set ─────────────────
python -c "
import sys, os, re
src, dst = sys.argv[1], sys.argv[2]
if not os.path.exists(src):
    print(f'  src {src!r} not found — nothing to migrate.')
    sys.exit(0)

# Parse existing dst keys so we don't overwrite
existing = set()
if os.path.exists(dst):
    for line in open(dst):
        m = re.match(r'^([A-Z_][A-Z0-9_]*)=', line)
        if m: existing.add(m.group(1))

added = []
with open(dst, 'a') as out:
    for line in open(src):
        m = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)', line.rstrip())
        if m and m.group(1) not in existing:
            out.write(line if line.endswith('\n') else line + '\n')
            added.append(m.group(1))

if added:
    print(f'  Migrated: {chr(44).join(added)}')
else:
    print('  Nothing new to migrate (all keys already present in dst).')
" "%2" "%3"
goto end

:list_keys
python -c "
import json, os
path = os.path.join('platform', 'keys.json')
if not os.path.exists(path):
    print('  keys.json not found — no keys issued yet.')
else:
    data = json.load(open(path))
    keys = data if isinstance(data, list) else data.get('keys', [])
    if not keys:
        print('  No keys found.')
    for k in keys:
        note  = k.get('note', '')
        tier  = k.get('tier', '?')
        exp   = k.get('expires', 'never')
        revok = ' [REVOKED]' if k.get('revoked') else ''
        print(f'  {tier:<12} exp={exp:<12} {note}{revok}')
"
goto end

:new_key
REM parse --tier and --note from remaining args
set TIER=observer
set NOTE=
:parse_new_key_args
if "%2"=="" goto do_new_key
if /i "%2"=="--tier" ( set TIER=%3 & shift & shift & goto parse_new_key_args )
if /i "%2"=="--note" ( set NOTE=%3 & shift & shift & goto parse_new_key_args )
shift & goto parse_new_key_args
:do_new_key
python platform\key_gen.py new --tier %TIER% --note "%NOTE%"
goto end

:check_health
python -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)
    print('  Status:', r.status, json.loads(r.read()))
except Exception as e:
    print('  Health check failed:', e)
"
goto end

:end
