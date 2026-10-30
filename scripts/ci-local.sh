#!/usr/bin/env bash
# Local equivalent of .github/workflows/synth-ci.yml (no cloud, no secrets).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export COSMAS_ENV=synth_os
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os}"
export REDIS_URL="${REDIS_URL:-redis://localhost:63799/0}"
export BLOB_ROOT="${BLOB_ROOT:-./data/blobs}"

echo "== ensure postgres/redis =="
bash scripts/ensure-local-services.sh postgres redis

echo "== uv sync =="
uv sync --extra dev --extra efax-inbound --extra mcp --extra calendar-import

echo "== ruff =="
uv run ruff check src tests

echo "== pyright =="
uv run pyright src

echo "== alembic upgrade =="
uv run alembic upgrade head

echo "== pytest =="
./scripts/install-client-deps.sh
uv run python scripts/check-backend-local.py --postgres-bin "${COSMAS_POSTGRES_BIN:-$(pg_config --bindir)}"

echo "== openapi =="
uv run python -m cosmas_os.cli dump-openapi

echo "== demo =="
uv run python -m cosmas_os.cli demo-artifact-chase

echo "== web =="
./scripts/install-client-deps.sh
(
  cd web
  corepack pnpm test
  corepack pnpm build
)

echo "== local synth CI gates passed =="
