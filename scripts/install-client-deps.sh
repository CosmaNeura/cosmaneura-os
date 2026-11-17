#!/bin/sh
# Install pinned client dependencies for shared imports and the local extension proof.
set -eu
ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
for package in clients/capture web clients/extension; do
  (
    cd "$ROOT/$package"
    corepack pnpm install --frozen-lockfile --ignore-scripts
  )
done
