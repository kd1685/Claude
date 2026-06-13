#!/usr/bin/env bash
# backup.sh — Dump the Ascent Terminal database and key store.
#
# Usage: bash backup.sh
# Cron:  0 3 * * * cd /opt/ascent && bash backup.sh

set -euo pipefail

BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "${BACKUP_DIR}"

# ---------------------------------------------------------------------------
# 1. PostgreSQL dump (via Docker Compose service)
# ---------------------------------------------------------------------------
echo "[backup] Dumping PostgreSQL..."
docker compose exec -T db pg_dump -U ascent ascent_db \
    > "${BACKUP_DIR}/db_${TIMESTAMP}.sql"
echo "[backup] DB dump written to ${BACKUP_DIR}/db_${TIMESTAMP}.sql"

# ---------------------------------------------------------------------------
# 2. Key store
# ---------------------------------------------------------------------------
if [ -f "keys.json" ]; then
    cp keys.json "${BACKUP_DIR}/keys_${TIMESTAMP}.json"
    echo "[backup] keys.json copied to ${BACKUP_DIR}/keys_${TIMESTAMP}.json"
else
    echo "[backup] keys.json not found — skipping."
fi

# ---------------------------------------------------------------------------
# 3. Prune backups older than 30 days
# ---------------------------------------------------------------------------
find "${BACKUP_DIR}" -name "db_*.sql" -mtime +30 -delete
find "${BACKUP_DIR}" -name "keys_*.json" -mtime +30 -delete
echo "[backup] Old backups pruned."

echo "[backup] Done."
