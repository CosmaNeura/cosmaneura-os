# BUILD_REPORT — local synthetic L0 through D2 Azure synth

Updated: 2026-09-03

Approvals:

- `APPROVE LOCAL SYNTH BUILD` → DL-20260902-05
- `Synthetic CI/release-artifact hardening` → DL-20260902-06
- `First commit and private remote` → DL-20260902-07
- `I authorize D2` → DL-20260902-08
- `deploy now` → DL-20260902-09
- Pasted D3-to-complete-build handoff hygiene gate → DL-20260903-01

## Verdict

**Local synthetic Insurance ArtifactChase L0 is implemented and verified.**  
**Deployment D1 (synthetic CI / release artifact) is implemented and verified locally.**
**D2: Terraform scaffold validated, then live apply succeeded (deployed).**

Azure infrastructure is deployed, but Azure application wiring is not: API and
worker remain on placeholder `helloworld` images. Track A was not mutated. No
secrets are included in this report.

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

The original pre-commit D1 manifests used `git_sha=uncommitted`. Later generated
manifests use a commit SHA and remain local-only.

## Assumptions

- Python 3.13; sync worker for tests/demo
- Host uses `docker-compose` (V5), not `docker compose` plugin
- GitHub Actions runs `synth-ci` on the private remote; local parity remains
  `./scripts/ci-local.sh`

## Dark capabilities

Unchanged: Athena/Acuity, real messaging, Clerk, Azure application wiring, LLM,
payment/PAN, and `AUTO_TEMPLATE`.

## First commit / private remote (DL-20260902-07)

| Item | Value |
|---|---|
| Commit | `44e97ed` on `main` (docs later) |
| Remote | `git@github.com:CosmaNeura/cosmaneura-os.git` (private; company org) |
| Excluded | `.env`, generated `artifacts/releases/manifest-*.json` |

## D2 Terraform scaffold — historical pre-apply stage (DL-20260902-08)

| Item | Value |
|---|---|
| Depth | IaC only — **no apply** |
| Targets | RG `cosmaneura-os-synth`, `eastus`, sub `bab2a709-…` |
| Path | `infra/` (Terraform azurerm ~> 4) |
| Proof | `terraform fmt` + `init -backend=false` + `validate` via `hashicorp/terraform:1.9` ✅ |
| Plan | `.azure/deployment-plan.md`; later advanced to **Deployed** under DL-20260902-09 |

## D2 live apply (DL-20260902-09)

Owner authorization: `deploy now`. Apply succeeded after Postgres recovery. No
secrets are included in this report.

| Item | Value |
|---|---|
| Subscription | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` |
| Resource group | `cosmaneura-os-synth` |
| Result | **Succeeded** (partial apply + Postgres recovery; no `terraform destroy`) |
| Primary location | `eastus` (RG, ACA, ACR, Redis, KV, Storage, LAW) |
| Postgres location | `centralus` (`postgres_location`) — eastus Flexible Server returned `ParameterOutOfRange` (empty Version set / provisioning restricted) |
| API HTTPS | `https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io` |
| ACR | `cosmasossynthacrrkpt0e.azurecr.io` — image push still gated; apps on placeholder helloworld images |
| Postgres FQDN | `pg-cosmasossynth-rkpt0e.postgres.database.azure.com` (v16) |
| Redis host | `redis-cosmasossynth-rkpt0e.redis.cache.windows.net` |
| Key Vault | `https://kvcosmasossynthrkpt0e.vault.azure.net/` |
| Storage | `cosmasossynthstrkpt0e` |

**Resources (all Succeeded):** `cosmaneura-os-synth`, `cosmasossynthacrrkpt0e`, `cae-cosmasossynth-rkpt0e`, `ca-api-cosmasossynth`, `ca-worker-cosmasossynth`, `pg-cosmasossynth-rkpt0e`, `redis-cosmasossynth-rkpt0e`, `kvcosmasossynthrkpt0e`, `cosmasossynthstrkpt0e`, `law-cosmasossynth-rkpt0e`, `id-cosmasossynth`.

Recovery added Flexible Server, database `cosmas_os`, and AllowAzureServices firewall in `centralus` after the eastus Postgres failure. Remainder of the stack stayed in `eastus`.

## Immediate D2 repository hygiene (DL-20260903-01)

| Check | Result |
|---|---|
| Remote preflight | `git fetch origin`; local `HEAD` and `origin/main` both `f077a1f` before the hygiene commit |
| Ignore coverage | `.env`, `.tools/`, `.apply-env`, Terraform state/provider cache/plans/real tfvars, and generated release manifests excluded |
| Prospective commit scan | No credential, private-key, token, connection-string, or PHI value found |
| Local sensitive-file permissions | Existing `.env`, `.apply-env`, Terraform state, and saved plans restricted to mode `0600` |
| Terraform source | Terraform 1.9.8 `fmt -check -recursive infra` and `validate -no-color` passed |
| Terraform example | `postgres_location = "centralus"`; no `postgres_admin_password` assignment |
| Local synth CI | `./scripts/ci-local.sh` passed: Ruff, Pyright, Alembic, 23 Pytest tests, OpenAPI, demo, web test/build |
| GitHub `synth-ci` | **Passed** for `b54f4c4f90d460beb2bdd14dc7164ade8887d81a`; run [33739304958](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33739304958), including the aggregate `synth-ci-gate` |

## Limitations / next gate

- `AUTHORIZE D2 ACR PUSH AND APP WIRING` is required before ACR push, digest
  pinning, Key Vault/environment wiring, synth migration, or cloud health smoke
- `APPROVE D3 ISOLATED EARLY-ADOPTER BETA` is required before D3
- `infra/.apply-env`, local Terraform state, tools, and plan files remain
  uncommitted; their contents are not reproduced here

## Legacy repositories

Read-only; not modified.
