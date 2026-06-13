@echo off
echo Pulling latest Ascent Terminal code...
git pull
echo.
echo Rebuilding and restarting Docker containers...
docker compose -f platform/docker-compose.yml up -d --build
echo.
echo Done. Check logs with:
echo   docker compose -f platform/docker-compose.yml logs -f
pause
