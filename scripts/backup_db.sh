#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

backup_dir="$repo_root/backups"
mkdir -p "$backup_dir"
backup_file="$backup_dir/airender-$(date +%Y%m%d-%H%M%S).sql"

docker compose exec -T db pg_dump -U airender airender > "$backup_file"
printf 'Database backup written: %s\n' "$backup_file"
