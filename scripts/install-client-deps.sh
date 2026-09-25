#!/bin/sh
# Both lockfiles are required by the standalone workspace's shared imports.
set -eu
ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
for package in clients/capture web; do
  (
    cd "$ROOT/$package"
    corepack pnpm install --frozen-lockfile --ignore-scripts
  )
done
