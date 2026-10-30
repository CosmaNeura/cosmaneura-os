#!/usr/bin/env bash
# Build a pinned local release image + manifest. Does NOT push or deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p artifacts/releases

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git rev-parse HEAD >/dev/null 2>&1; then
    GIT_SHA="$(git rev-parse HEAD | tr -d '\n')"
    GIT_DESC="$(git describe --always --dirty --tags 2>/dev/null | tr -d '\n' || printf '%s' "$GIT_SHA")"
  else
    GIT_SHA="uncommitted"
    GIT_DESC="uncommitted"
  fi
  GIT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null | tr -d '\n' || true)"
  if [[ -z "${GIT_BRANCH}" ]]; then
    GIT_BRANCH="main"
  fi
else
  GIT_SHA="no-git"
  GIT_DESC="no-git"
  GIT_BRANCH="none"
fi

SHORT="${GIT_SHA:0:12}"
IMAGE_TAG="cosmas-os:synth-${SHORT}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MANIFEST="artifacts/releases/manifest-${STAMP}.json"
LATEST="artifacts/releases/manifest-latest.json"

echo "== docker build ${IMAGE_TAG} =="
docker build -t "$IMAGE_TAG" .

IMAGE_ID="$(docker image inspect --format='{{.Id}}' "$IMAGE_TAG")"
CREATED="$(docker image inspect --format='{{.Created}}' "$IMAGE_TAG")"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os}"
bash scripts/ensure-local-services.sh postgres

echo "== image smoke: alembic upgrade =="
docker run --rm --network host \
  -e DATABASE_URL="postgresql+psycopg://cosmas:cosmas@127.0.0.1:54329/cosmas_os" \
  -e COSMAS_ENV=synth_os \
  "$IMAGE_TAG" \
  alembic upgrade head

export GIT_SHA GIT_DESC GIT_BRANCH IMAGE_TAG IMAGE_ID CREATED STAMP MANIFEST LATEST
python3 <<'PY'
import json
import os
from pathlib import Path

manifest = {
    "product": "cosmas-os",
    "track": "B",
    "env": "synth_os",
    "git_sha": os.environ["GIT_SHA"],
    "git_describe": os.environ["GIT_DESC"],
    "git_branch": os.environ["GIT_BRANCH"],
    "image_tag": os.environ["IMAGE_TAG"],
    "image_id": os.environ["IMAGE_ID"],
    "image_created": os.environ["CREATED"],
    "built_at": os.environ["STAMP"],
    "deployed": False,
    "pushed": False,
    "cloud": False,
    "notes": "Synthetic release artifact only. Not pushed. Not cloud-deployed.",
}
path = Path(os.environ["MANIFEST"])
text = json.dumps(manifest, indent=2) + "\n"
path.write_text(text, encoding="utf-8")
Path(os.environ["LATEST"]).write_text(text, encoding="utf-8")
print(text)
PY

echo "== wrote ${MANIFEST} and ${LATEST} =="
echo "Next: do NOT docker push / do NOT deploy without a separate owner decision."
