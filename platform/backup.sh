#!/bin/bash
# Ascent Terminal — nightly backup of everything irreplaceable:
#   data/ (incl. keys.json — subscriber access, alerts, exec log, bot state,
#   billing maps, mailing list) + .env (your configuration).
# Install on the VPS:
#   chmod +x /root/AscentTerminal/platform/backup.sh
#   crontab -e   →   0 4 * * * /root/AscentTerminal/platform/backup.sh
# Keeps 14 days locally. STRONGLY recommended: also copy off-box, e.g.
#   rclone copy /root/backups remote:ascent-backups   (or scp to your PC weekly)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/root/backups
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M)
tar -czf "$DEST/ascent-$STAMP.tar.gz" -C "$SRC" data .env 2>/dev/null || \
tar -czf "$DEST/ascent-$STAMP.tar.gz" -C "$SRC" data
ls -t "$DEST"/ascent-*.tar.gz | tail -n +15 | xargs -r rm --
echo "backup written: $DEST/ascent-$STAMP.tar.gz"
