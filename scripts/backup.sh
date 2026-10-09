#!/bin/bash
set -e
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker compose exec -T db pg_dump -U airender airender > "$BACKUP_DIR/db.sql"
echo "DB backup: $BACKUP_DIR/db.sql"
# Keep last 7
ls -dt ./backups/*/ | tail -n +8 | xargs rm -rf 2>/dev/null || true
