#!/usr/bin/env bash
# Start the Kingdom 1685 tracker + controller.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "No .env found — copying .env.example"; cp .env.example .env; }

# shellcheck disable=SC1091
set -a; [ -f .env ] && . ./.env; set +a

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ "${1:-}" = "--seed" ]; then
  echo "Seeding demo data…"; python3 -m scripts.seed; shift
fi

echo "Starting on http://${HOST}:${PORT}  (control backend: ${CONTROL_BACKEND:-mock})"
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
