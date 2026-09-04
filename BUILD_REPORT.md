# BUILD_REPORT — local synthetic L0 through D3 synthetic-lab source preparation

Updated: 2026-09-03

Approvals:

- `APPROVE LOCAL SYNTH BUILD` → DL-20260902-05
- `Synthetic CI/release-artifact hardening` → DL-20260902-06
- `First commit and private remote` → DL-20260902-07
- `I authorize D2` → DL-20260902-08
- `deploy now` → DL-20260902-09
- Pasted D3-to-complete-build handoff hygiene gate → DL-20260903-01
- `AUTHORIZE D2 ACR PUSH AND APP WIRING` → DL-20260903-02
- `APPROVE D3 ISOLATED EARLY-ADOPTER BETA` → DL-20260903-03
- Approved non-PHI Cosmas Beta Lab first slice → DL-20260903-04
- Approved creation/configuration of the separate Cosmas OS Clerk development
  application and Beta Lab Organization → DL-20260903-05
- Approved native mobile closed-beta placement after browser D3 and before D4
  → DL-20260903-06

## Verdict

**Local synthetic Insurance ArtifactChase L0 is implemented and verified.**  
**Deployment D1 (synthetic CI / release artifact) is implemented and verified locally.**
**D2: the non-PHI Azure synth runtime is deployed and verified.**
**D3: the isolated synthetic Beta Lab source candidate is implemented and the
complete local D3 gate passed on 2026-09-03. Any deployable release must use a
committed SHA with green GitHub CI and bind that exact SHA in its external,
protected release record. All exact-plan and live deployment acceptance gates
remain open. No D3 Azure resource or production Clerk instance exists.**

API and Celery worker now run one immutable Cosmas OS ACR digest. Key Vault
references supply the synth PostgreSQL and Redis URLs through the OS managed
identity; the database is at Alembic head; the public health check is green.
Track A was not mutated. No secret values are included in this report.

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

- Python 3.13; sync worker for local tests/demo, async Celery in Azure
  (`SYNC_WORKER=false`)
- Host uses `docker-compose` (V5), not `docker compose` plugin
- GitHub Actions runs `synth-ci` on the private remote; local parity remains
  `./scripts/ci-local.sh`

## Dark capabilities

For the deployed D2 runtime, Athena/Acuity, real messaging, Clerk, Azure Blob,
LLM, payment/PAN, and `AUTO_TEMPLATE` remain dark. The D3 candidate now contains
offline-tested Clerk and Azure Blob boundaries, but neither is live. The D2
runtime remains synthetic-only; it is not a beta or PHI environment.

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
| ACR | `cosmasossynthacrrkpt0e.azurecr.io` — current OS image digest recorded below |
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

## D2 ACR push and application wiring (DL-20260903-02)

Owner authorization: exact phrase `AUTHORIZE D2 ACR PUSH AND APP WIRING`.
The sanitized Terraform plan was shown before apply.

| Item | Result |
|---|---|
| Runtime source | `81d75c3f353e2e2ae4eaf112bf4a69ef9f7242e0`; digest defaults in `471f56f5332fff5dc1af49322343677c33840b30` |
| ACR build | QuickRun `ca1`, succeeded; source archiving disabled |
| Immutable image | `cosmasossynthacrrkpt0e.azurecr.io/cosmas-os@sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be` |
| Reviewed plan | 2 add, 2 update in place, 0 destroy/replacement |
| Apply | **2 added, 2 changed, 0 destroyed** |
| Added | Key Vault secrets `database-url` and `redis-url` (values never logged) |
| App wiring | Both apps pull through UAMI `id-cosmasossynth`; connection settings use Key Vault secret refs; `COSMAS_ENV=synth_os`, `SYNC_WORKER=false` |
| API | Revision `ca-api-cosmasossynth--0000001`, Healthy/Provisioned, 1 replica, 100% traffic |
| Worker | Revision `ca-worker-cosmasossynth--0000001`, Healthy/Provisioned; Celery broker-connected and ready signals, 0 error/failure signals in the sanitized log query |
| Migration | `alembic upgrade head` succeeded against synth database `cosmas_os`; `alembic current --check-heads` returned `0001_initial (head)` |
| Health | HTTP 200 with `{"status":"ok","env":"synth_os"}` |
| Post-apply plan | Refresh-backed Terraform plan: **0 add, 0 change, 0 destroy** |
| Local verification | `./scripts/ci-local.sh` passed: Ruff, Pyright, Alembic, **25 tests**, OpenAPI, demo, and web test/build |
| GitHub verification | `81d75c3` [run 33741787268](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33741787268) and `471f56f` [run 33742668350](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33742668350) passed all five jobs |

Pre/post state evidence is local-only and mode `0600` under
`/private/tmp/cosmaneura-os-d2-residual-20260903/`. SHA-256:
`f91a4e38f9cfe3a540b5924c8fb17177e76a30566faf0cb76efdb53cea20a0e5`
(pre) and
`8920843aa3e5fa5a30a6e840fba7bfd94194575f84d350c156e91d3ab11f466a`
(post). Terraform state and saved binary plans contain sensitive derived
connection data even when CLI output is redacted; they remain ignored,
untracked, and mode `0600`.

The Azure CLI 2.89 local-context packer did not interpret trailing-slash
directory patterns as Docker does, so the initial QuickRun source upload was
larger than expected and may have included local infrastructure paths. The run
reports source archiving disabled, and Docker's effective 396.3 kB build
context excluded those paths from the image. The policy is now a strict
runtime-input allowlist; an exact packer replay produced an approximately 78 kB
archive with zero paths outside that allowlist and zero nested bytecode,
environment, or log files. A local image rebuild succeeded with a 293.9 kB
Docker context. Future ACR builds must use this guarded context (preferably a
clean committed staging tree).

## D3 isolated synthetic Beta Lab source (DL-20260903-03 / -04)

The approved first D3 slice is a separate, invitation-only, strictly non-PHI
Cosmas Beta Lab for the owner and outside testers. It does not reuse the
MyCatholicDoctor Clerk application, D2 resources, or Track A state.

| Item | Result |
|---|---|
| Deployment modes | `synthetic_lab` is the fail-closed default; `authorized_beta` separately requires named-clinic, clinic-approval, BAA, and PHI authorization evidence |
| Authentication | Exact Clerk issuer/audience/authorized-party checks, bounded JWKS caches, no unknown-key request-time fetch, exact Org and server-side Principal/Box authority |
| Browser | Supported Clerk React provider, signed-in session plus active Org required, fresh bearer token per API call, zero API calls when configuration or identity is incomplete |
| Identity administration | Protected first-owner bootstrap plus an authenticated owner-only roster and web screen for bind, deactivate, reactivate, and ownership transfer; stale-owner race regression covered |
| Storage | Managed-identity Azure Blob adapter with Box-prefixed keys |
| Infrastructure | Independent bootstrap/environment roots, separated web/runtime/database-job identities, staged private data-plane writes, private Azure Managed Redis `Balanced_B0` with two-node HA/TLS/one-second AOF, a manual digest-pinned in-network role/migration verifier, immutable API/worker and web image digests |
| Complete local gate | `./scripts/d3-self-test.sh` passed on 2026-09-04: Ruff, Pyright, Alembic/OpenAPI/demo, **447 Python tests**, **32 web tests**, and the production web build passed |
| Infrastructure and shell gates | Bootstrap OpenTofu **6/6** and environment OpenTofu **35/35** passed; deployment guards, formatting, Bash syntax, ShellCheck, and diff integrity were clean |
| Recovery/offboarding suites | Focused PITR, release recovery, and offboarding tests passed **31/31** |
| Protected runner | The guarded compressed custom-data payload remains within Azure's **65,536-byte** limit |
| Container evidence | Final local Linux/amd64 API and web images built; both current-database Trivy scans reported **0 fixable HIGH/CRITICAL findings**; final release digests do not exist until protected-runner build/push |
| Security review | Independent adversarial review found **no open P0-P2 source defect**; live control and deployment evidence remain required |
| Clerk state | Separate Cosmas OS development app and zero-member Cosmas Beta Lab Org created under `DL-20260903-05`; email-code, invite-only, required Org membership, disabled user-created Orgs, and exact API audience configured; existing Cosmas app untouched |
| Release eligibility | **LOCAL SOURCE GATES COMPLETE**; each deployable release still requires a committed SHA, green GitHub CI, and exact-SHA binding in its external protected release record |
| Live state | The isolated D3 bootstrap/state boundary and protected runner exist. The application foundation, database job, workloads, custom-domain binding, production Clerk instance, tester invitations, MCD transfer, and PHI remain absent |

The current private, low-traffic D3 planning envelope is approximately
**$170–260/month** across its bootstrap/state and workload resource groups,
without credits and excluding founder support, Clerk paid-plan charges, taxes,
and unusual egress/log volume. The accepted **$350/month combined alert** is a
notification threshold across both D3 groups, not a spending cap; the exact
plan and human-owned recipient still require review before apply.

The concrete source-controlled capability record is
`docs/beta/SYNTHETIC_LAB_CAPABILITY_MANIFEST.md`. A deployable release must bind
the manifest's exact committed SHA and SHA-256 in the external protected record;
all live values remain pending, and this document is not an apply approval.

## Limitations / next gate

- This is still a public, synthetic-only D2 service: the API trusts caller-set
  identity headers and permits wildcard CORS. There is no Clerk authentication.
- PostgreSQL public networking and the `AllowAzureServices` firewall rule are
  D2-only. D3 must use stronger isolation before PHI is possible.
- `BLOB_ROOT=/tmp/cosmas-os-blobs` is local to an app replica and is lost on
  restart. The provisioned Azure Blob container is not yet used; API max
  replicas is intentionally 1 for this residual synth.
- This is the first functional OS image in ACR. The placeholder predecessor was
  mutable `helloworld:latest`, not a valid product rollback target. The current
  digest is the rollback baseline for the next release.
- The synthetic Beta Lab still needs its production Clerk instance and
  production Organization, dedicated synthetic Box UUID, approved HTTPS
  origin, human deploy identity/evidence, final region/cost choice, and
  reviewed D3 bootstrap, foundation, database-preparation, and workload plans
  before deployment. Each apply is bound to an exact saved plan hash and
  current state lineage/serial; the existing D3 phase approval is not a blank
  approval for later plans.
- The source now includes a separate digest-pinned, HTTPS-only static beta web
  Container App and fail-closed release contract. Its foundation-derived
  origin, production Clerk configuration, reviewed image digest, and human
  deployment evidence are still required before the host exists.
- The recommended beta registry posture is Premium/private ACR, and the source
  requires an explicit selection. A lower-cost Basic/public exception is
  possible only for `synthetic_lab` with a reviewed risk reference; a human
  must select and evidence the final posture before planning.
- The D3 broker design is closed in source on private Azure Managed Redis
  `Balanced_B0` with HA. A human must still refresh and record Central US
  availability, quota, contract price, and a live broker-mediated worker probe
  before admitting testers.
- The least-privilege database and private migration path is now implemented as
  a manual, unscheduled Container Apps Job with sanitized evidence. Its live
  Azure execution must produce the structured
  `database_preparation_attestation`; protected-runner probes must separately
  produce `runner_live_network_evidence_reference`. Worker readiness,
  controlled outbound egress, and physical purge/restore evidence remain
  deployment controls to close before testers are admitted.
- Any clinic or PHI-capable beta additionally requires the named clinic,
  clinic approval, applicable BAA/service eligibility, and a separate PHI
  authorization.
- `infra/.apply-env`, local Terraform state, tools, and plan files remain
  uncommitted; their contents are not reproduced here.

## Legacy repositories

Read-only; not modified.
