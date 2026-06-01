#!/usr/bin/env bash
# Update the Kingdom 1685 tracker to the latest code and restart.
#   bash deploy/update.sh
# Your data (DB) and deploy/.env are untouched — they live in Docker volumes /
# are gitignored.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Pulling latest code…"
git pull --ff-only

echo "Rebuilding and restarting containers…"
docker compose -f deploy/docker-compose.yml up -d --build

docker image prune -f >/dev/null 2>&1 || true
echo "Done. Logs:  docker compose -f deploy/docker-compose.yml logs -f app"
