#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.production.yml)

python3 scripts/check_vps_handoff.py

if [[ ! -f .env ]]; then
  echo "ERROR: .env is missing. Copy .env.example and configure production values." >&2
  exit 1
fi

echo "[1/5] Pulling latest code..."
git pull --ff-only

echo "[2/5] Validating production Compose configuration..."
"${COMPOSE[@]}" config --quiet

echo "[3/5] Building images..."
"${COMPOSE[@]}" build

echo "[4/5] Applying database migrations..."
"${COMPOSE[@]}" run --rm app alembic upgrade head

echo "[5/5] Starting services and waiting for health checks..."
"${COMPOSE[@]}" up -d --wait --wait-timeout 180

"${COMPOSE[@]}" ps
echo "Production deployment is healthy."
