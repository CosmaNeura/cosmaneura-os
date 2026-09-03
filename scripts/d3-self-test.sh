#!/usr/bin/env bash
# Local-only D3 readiness checks. This script never authenticates to Azure or Clerk.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/cosmas-os-uv-cache}"

echo "== synthetic regression suite =="
./scripts/ci-local.sh

if command -v tofu >/dev/null 2>&1; then
  TF_BIN="tofu"
elif command -v terraform >/dev/null 2>&1; then
  TF_BIN="terraform"
else
  echo "Terraform/OpenTofu is required for D3 infrastructure validation" >&2
  exit 1
fi

echo "== deployment wrapper guards =="
bash infra/beta/tests/deployment-guards.sh

for TF_ROOT in infra/beta/bootstrap infra/beta/environment; do
  echo "== validate ${TF_ROOT} =="
  "$TF_BIN" -chdir="$TF_ROOT" init -backend=false -input=false >/dev/null
  "$TF_BIN" -chdir="$TF_ROOT" fmt -check -recursive
  "$TF_BIN" -chdir="$TF_ROOT" validate -no-color
  "$TF_BIN" -chdir="$TF_ROOT" test -no-color
done

echo "== immutable runtime image =="
if ! docker buildx version >/dev/null 2>&1; then
  echo "Docker Buildx is required so offline RUN --network=none stages are enforced" >&2
  exit 1
fi
docker buildx build --load --platform linux/amd64 --tag cosmas-os:d3-local-check .
RUNTIME_UID="$(docker run --rm --entrypoint id cosmas-os:d3-local-check -u)"
if [[ "$RUNTIME_UID" != "10001" ]]; then
  echo "runtime image must use uid 10001, got ${RUNTIME_UID}" >&2
  exit 1
fi

echo "== fail-closed static beta web image =="
docker buildx build --load \
  --platform linux/amd64 \
  --tag cosmas-os-web:d3-local-check \
  --file Dockerfile.web \
  --build-arg VITE_COSMAS_ENV=early_adopter_beta \
  --build-arg VITE_CLERK_PUBLISHABLE_KEY=pk_live_synthetic_public_test_value \
  --build-arg VITE_API_BASE=https://api.example.invalid \
  .
WEB_UID="$(docker run --rm --entrypoint id cosmas-os-web:d3-local-check -u)"
if [[ "$WEB_UID" == "0" ]]; then
  echo "static web image must not run as root" >&2
  exit 1
fi
docker run --rm --entrypoint nginx cosmas-os-web:d3-local-check -t

echo "== D3 local readiness checks passed; no cloud deployment or PHI use occurred =="
