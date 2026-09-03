# Cosmas OS (Track B)

Local synthetic practice computer. This repository is **synth-only**: invented
people, appointments, and insurance images. No PHI, production credentials, or
live Athena/Acuity/Clerk/messaging. Its Azure footprint is a non-PHI D2 synth
environment only.

## One-command local start

```bash
./scripts/dev-up.sh
```

Requires: Docker (`docker-compose`), `uv`, Python 3.13. Starts Postgres + Redis,
runs migrations, seeds a clinic, and serves the API on `:8000`.

In another terminal:

```bash
cd web && pnpm install && pnpm dev
```

Open http://localhost:5173 for the owner work queue.

## Demo (full ArtifactChase L0)

```bash
docker-compose up -d postgres redis
uv sync --extra dev
uv run alembic upgrade head
uv run python -m cosmas_os.cli demo-artifact-chase
```

## Tests

```bash
./scripts/ci-local.sh
```

Or piecemeal:

```bash
uv run pytest
uv run ruff check src tests
uv run pyright src
cd web && pnpm test && pnpm build
```

## Synthetic CI / release artifact (D1)

```bash
./scripts/ci-local.sh
./scripts/release-artifact.sh
```

- GitHub Actions: [`.github/workflows/synth-ci.yml`](.github/workflows/synth-ci.yml)
- Rollback / migration recovery: [`docs/RELEASE_AND_ROLLBACK.md`](docs/RELEASE_AND_ROLLBACK.md)
- Manifests land in `artifacts/releases/` (not pushed, not deployed)

## D2 Azure synth infrastructure (deployed)

```bash
# See infra/README.md — plan is the default; every later mutation is gated
```

- Plan: [`.azure/deployment-plan.md`](.azure/deployment-plan.md)
- Code: [`infra/`](infra/)
- Resource group `cosmaneura-os-synth` is deployed; most resources are in
  `eastus`, while PostgreSQL is in `centralus` after the subscription rejected
  Flexible Server provisioning in `eastus`.
- API and worker still use placeholder `helloworld` images. ACR push, digest
  pinning, and app wiring require `AUTHORIZE D2 ACR PUSH AND APP WIRING`.

## What this slice proves

1. Seed one Org Box with owner + Scribe/Chief/Chaser  
2. Import synthetic appointments  
3. Attest PatientLink  
4. Detect missing insurance artifact → F-8 ticket + neutral message  
5. Approve / edit / reject / escalate in one queue  
6. Payload-bound approval → one local operation via fake NotifyPort  
7. Double-click / retry does not duplicate the effect  
8. Synthetic front/back upload + human verification → `IMAGE_ON_FILE`  
9. Close ticket + audit timeline  
10. Injectable clock purge with non-PHI receipt  

## Layout

```text
src/cosmas_os/   domain, application, ports, adapters, api, worker
web/             minimal React owner queue
migrations/      Alembic
fixtures/synthetic/
docs/validation/ Phase 0 evidence (complete)
```

## Authority

See `AGENTS.md`, `CANONICAL_PRODUCT_DECISIONS.md`, and `docs/DECISION_LOG.md`.
GPT-5.6 SOL is a development agent only — not a product runtime dependency.

## Remote

Private GitHub: `git@github.com:CosmaNeura/cosmaneura-os.git` (Track B only).

## Not authorized here

Further Azure mutation, registry push/app wiring, D3+, Track A edits, real
vendors, PHI, and an application LLM.
