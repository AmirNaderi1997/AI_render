#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <backup-file> <target-database>" >&2
  exit 2
fi

backup_file="$1"
target_database="$2"

if [[ ! -f "$backup_file" ]]; then
  printf 'ERROR: backup file not found: %s\n' "$backup_file" >&2
  exit 1
fi
if [[ ! "$target_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "ERROR: target database must be a simple PostgreSQL identifier" >&2
  exit 1
fi

printf 'This will restore %s into database "%s". Type the database name to continue: ' "$backup_file" "$target_database"
read -r confirmation
if [[ "$confirmation" != "$target_database" ]]; then
  echo "Restore cancelled." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U airender -d "$target_database" < "$backup_file"
printf 'Database restore completed: %s\n' "$target_database"
