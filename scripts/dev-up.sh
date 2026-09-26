#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cp -n .env.example .env 2>/dev/null || true
docker-compose up -d postgres redis
echo "Waiting for Postgres..."
for i in $(seq 1 40); do
  if docker-compose exec -T postgres pg_isready -U cosmas -d cosmas_os >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
uv sync --extra dev
uv run alembic upgrade head
uv run python -m cosmas_os.cli seed-synth
echo "Starting API on :8000 (Ctrl+C to stop). Web: ./scripts/install-client-deps.sh && cd web && corepack pnpm dev"
exec uv run uvicorn cosmas_os.api.app:app --reload --port 8000
