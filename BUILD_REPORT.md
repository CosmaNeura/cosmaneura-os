# BUILD_REPORT — local synthetic L0 + D1 synth CI

Date: 2026-09-02  
Approvals:
- `APPROVE LOCAL SYNTH BUILD` → DL-20260902-05
- `Synthetic CI/release-artifact hardening` → DL-20260902-06

## Verdict

**Local synthetic Insurance ArtifactChase L0 is implemented and verified.**  
**Deployment D1 (synthetic CI / release artifact) is implemented and verified locally.**

Cloud deployment, registry push, and Track A mutation were not performed.

## What changed (L0)

- Local `git init` on `main` (no remote)
- Modular monolith under `src/cosmas_os/`
- Alembic `0001_initial`, Compose Postgres/Redis, React queue, synth fixtures
- Docs: capability matrix, threat/recovery, retention, demo walkthrough

## What changed (D1)

- `.github/workflows/synth-ci.yml` — required jobs, no secrets, no deploy
- `./scripts/ci-local.sh` — local parity for all synth gates
- `./scripts/release-artifact.sh` — pinned image + manifest (`deployed/pushed/cloud: false`)
- `docs/RELEASE_AND_ROLLBACK.md` — migration apply/downgrade recovery
- `.dockerignore` — lean image context
- `artifacts/releases/` — manifest output location

## Commands run and results

### L0

| Command | Result |
|---|---|
| `git init -b main` | OK — no remote |
| `uv run pytest` | **23 passed** |
| `uv run ruff check src tests` | passed |
| `uv run pyright src` | 0 errors |
| demo + openapi + web test/build | OK |

### D1

| Command | Result |
|---|---|
| `./scripts/ci-local.sh` | **passed** (ruff, pyright, migrate, pytest 23, demo, web test+build) |
| `./scripts/release-artifact.sh` | **passed** — image `cosmas-os:synth-uncommitted`, smoke `alembic upgrade`, manifest written under `artifacts/releases/` |

Note: `git_sha` is `uncommitted` until an owner-requested initial commit exists.

## Assumptions

- Python 3.13; sync worker for tests/demo
- Host uses `docker-compose` (V5), not `docker compose` plugin
- CI workflow will run when a remote exists; local scripts are the authoritative D1 proof today

## Dark capabilities

Unchanged: Athena/Acuity, real messaging, Clerk/Azure, LLM, payment/PAN, AUTO_TEMPLATE.

## Limitations / next gate

- No GitHub remote yet — Actions file is ready but not executed on GitHub
- No image push / no Azure
- Recommended next: owner-requested git commit (+ optional private remote), then optional non-PHI Azure **only** with a separate explicit decision

## Legacy repositories

Read-only; not modified.
