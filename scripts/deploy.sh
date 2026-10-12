#!/usr/bin/env bash
set -euo pipefail
COMPOSE=(docker compose -f docker-compose.yml)

python3 scripts/check_vps_handoff.py

if [ ! -f .env ]; then
    echo "ERROR: .env is missing. Configure it from .env.example." >&2
    exit 1
fi
for file in certs/fullchain.pem certs/privkey.pem; do
    if [ ! -s "$file" ]; then
        echo "ERROR: $file is missing or empty; install TLS files before starting nginx." >&2
        echo "Development only: run ./scripts/generate-certs.sh <hostname>." >&2
        echo "Production: place the matching Let's Encrypt fullchain.pem and privkey.pem in certs/." >&2
        exit 1
    fi
done

# Check presence only; never print secret values or source .env as shell code.
python3 - <<'PY'
from pathlib import Path
values = {}
for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"\'')
for key in ('POSTGRES_PASSWORD', 'JWT_SECRET', 'ALLOWED_HOSTS', 'HERMES_TOKEN_KEY'):
    value = values.get(key, '')
    if not value or value.startswith('replace-') or value == 'example.com':
        raise SystemExit(f'ERROR: configure {key} in .env before deployment')
if len(values['JWT_SECRET']) < 32 or len(values['HERMES_TOKEN_KEY']) < 32:
    raise SystemExit('ERROR: JWT_SECRET and HERMES_TOKEN_KEY must each be at least 32 characters')
if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in values['POSTGRES_PASSWORD']):
    raise SystemExit('ERROR: POSTGRES_PASSWORD must be URL-safe (letters, digits, underscore, hyphen)')
PY

"${COMPOSE[@]}" config --quiet

echo "[1/5] Building images..."
"${COMPOSE[@]}" build

echo "[2/5] Starting database and Redis..."
"${COMPOSE[@]}" up -d db redis
ready=0
for attempt in {1..60}; do
    if "${COMPOSE[@]}" exec -T db pg_isready -U airender > /dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" -ne 1 ]; then
    echo "ERROR: database did not become ready within 120 seconds" >&2
    exit 1
fi

echo "[3/5] Running and checking database migrations..."
"${COMPOSE[@]}" run --rm app python scripts/check_migration_baseline.py
"${COMPOSE[@]}" run --rm app alembic upgrade head
"${COMPOSE[@]}" run --rm app alembic check
"${COMPOSE[@]}" run --rm app alembic current

echo "[4/5] Starting services..."
"${COMPOSE[@]}" up -d --wait --wait-timeout 180

echo "[5/5] Checking HTTPS API health..."
# The certificate must match localhost's replacement host and resolve publicly or in /etc/hosts.
deploy_host=$(awk -F= '/^ALLOWED_HOSTS=/{print $2; exit}' .env | cut -d, -f1 | tr -d '\047"')
curl --fail --silent --show-error --resolve "$deploy_host:443:127.0.0.1" "https://$deploy_host/api/" > /dev/null
"${COMPOSE[@]}" ps
echo "Deployment health checks passed for https://$deploy_host"
