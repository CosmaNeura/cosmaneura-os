# Azure Deployment Plan

> **Status:** D2 runtime deployed and verified

Generated: 2026-09-02T23:30:00Z
Updated: 2026-09-03T10:19:36Z (D2 ACR push, app wiring, and verification)

**Gate:** D2 infrastructure apply completed under `DL-20260902-09`; ACR push
and application wiring completed under `DL-20260903-02`. Track A untouched. No
PHI.

Design spec: `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md`
Decision: `DL-20260902-08` (+ owner choices depth 3, region B, tooling 1);
infrastructure apply `DL-20260902-09`; runtime residual `DL-20260903-02`

---

## 1. Project Overview

**Original goal:** Scaffold Terraform for optional non-PHI Cosmas OS Azure
development without joining Track A. The scaffold was applied under
`DL-20260902-09`, then the digest-pinned runtime was wired under
`DL-20260903-02`; most resources are in `eastus` and PostgreSQL is in
`centralus`.

**Path:** Add Components (existing modular-monolith repo)

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Development (synthetic / non-PHI) |
| Scale | Small |
| Budget | Cost-Optimized |
| **Subscription** | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` (Microsoft Azure Sponsorship, default) — owner confirmed **B** |
| **Primary location** | `eastus` — owner confirmed **B** |
| Resource group | `cosmaneura-os-synth` (deployed) |
| PHI | false — invented synth data only |
| Deploy now | **Yes** — `DL-20260902-09` |
| Postgres region note | Flexible Server **blocked in eastus** for this subscription; server lives in **`centralus`** (`postgres_location`), same RG |

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| API | API | Python 3.13 FastAPI | `src/cosmas_os/api/` |
| Worker | Worker | Celery | `src/cosmas_os/worker/` |
| Web queue | Frontend | React + Vite | `web/` (local/dev; not required on ACA for D2 scaffold) |
| Image | Container | Existing Dockerfile | `Dockerfile` |
| Migrations | Data | Alembic | `migrations/` |

---

## 4. Recipe Selection

**Selected:** Terraform

**Rationale:** Owner chose tooling **1**; Track A master uses Terraform; OS keeps **separate** state (never `cosmaneura-tfstate`). AZD/Bicep deferred.

---

## 5. Architecture

**Stack:** Containers (Azure Container Apps)

### Service Mapping

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| Resource group | `Microsoft.Resources/resourceGroups` | n/a — `cosmaneura-os-synth` |
| Registry | Azure Container Registry | Basic |
| Logs | Log Analytics workspace | PerGB2018 (payg, low volume) |
| Compute env | Container Apps Environment | Consumption |
| API | Container App | 0.25–0.5 vCPU / 0.5–1 Gi (scale-to-zero allowed) |
| Worker | Container App | minimal always-on or scale-from-1 (Celery) |
| Database | PostgreSQL Flexible Server | Burstable `B_Standard_B1ms` (or smallest available) |
| Broker/cache | Azure Cache for Redis | Basic C0 (variable to swap sidecar later) |
| Blobs | Storage Account + container | Provisioned but unused by app; D2 runtime uses ephemeral local FS |
| Secrets | Key Vault | Standard |
| Identity | User-assigned managed identity | for ACA → ACR/KV/Storage |

### Supporting Services

| Service | Purpose |
|---------|---------|
| Log Analytics | Centralized logging for ACA |
| Key Vault | Active versionless refs for `database-url` and `redis-url`; no values committed or logged |
| Managed Identity | Avoid admin passwords in app config where possible |
| Tags | `track=B`, `product=cosmas-os`, `env=synth_os`, `phi=false` |

### Explicit exclusions

Clerk, Athena, Acuity, Stripe, Track A VNet/SP/state, PHI monitoring packages, CI auto-deploy, Application Insights (optional later).

---

## 6. Provisioning Limit Checklist (historical pre-apply snapshot)

Captured 2026-09-02 before deployment. `Microsoft.Quota` was **not registered**
on this subscription (`MissingRegistrationForResourceProvider`), so the check
used Azure Resource Graph usage in `eastus` plus
[subscription service limits](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/azure-subscription-service-limits).

### Phase 1 + 2 (combined)

| Resource Type | Number to Deploy | Current usage (eastus ARG) | Total After Deployment | Limit/Quota (docs) | Notes |
|---------------|------------------|----------------------------|------------------------|--------------------|-------|
| Microsoft.Resources/resourceGroups | 1 | 27 (subscription-wide `az group list`) | 28 | 980 / subscription | RG `cosmaneura-os-synth` absent at snapshot time |
| Microsoft.App/managedEnvironments | 1 | 2 | 3 | 20 environments / region (typical default; confirm at apply) | ARG + ACA limits docs |
| Microsoft.App/containerApps | 2 | 2 | 4 | 300 apps / environment (env-scoped; sub headroom OK) | api + worker |
| Microsoft.ContainerRegistry/registries | 1 | 2 | 3 | 100 Basic registries / subscription (typical) | Basic SKU |
| Microsoft.DBforPostgreSQL/flexibleServers | 1 | 0 | 1 | Region capacity varies; B1ms commonly available | ARG shows 0 in eastus now |
| Microsoft.Cache/Redis | 1 | 0 | 1 | Soft limits high for Basic; C0 | ARG shows 0 in eastus now |
| Microsoft.Storage/storageAccounts | 1 | 3 | 4 | 250 / region | Well under limit |
| Microsoft.KeyVault/vaults | 1 | 4 | 5 | 1000 / subscription | Well under limit |
| Microsoft.OperationalInsights/workspaces | 1 | 3 | 4 | Soft; typically fine at low count | Log Analytics |
| Microsoft.ManagedIdentity/userAssignedIdentities | 1 | 7 | 8 | 2000 / region typical | ACA identity |

**Historical result:** ✅ All inventoried resources were within documented
limits for a single small synth stack. The later apply outcome is recorded
below.

---

## 7. Execution Checklist

### Phase 1: Planning
- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location with user
- [x] Prepare resource inventory
- [x] Fetch quotas / fallback capacity validation
- [x] Scan codebase
- [x] Select recipe
- [x] Plan architecture
- [x] **User approved this plan**
- [x] User approved design spec `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md`

### Phase 2: Execution (scaffold only — after approval)
- [x] Generate `infra/*.tf` + `terraform.tfvars.example` + `infra/README.md`
- [x] Keep existing root `Dockerfile` (already present)
- [x] Update `docs/RELEASE_AND_ROLLBACK.md` with plan-only Azure notes
- [x] `terraform fmt` + `terraform validate` (via Docker image; **no apply**)
- [x] Update plan status to Validated (scaffold)
- [x] **Did not** invoke azure-deploy / `terraform apply`

### Phase 3: Validation
- [x] `terraform validate` proof recorded
- [x] Status → Validated (scaffold)

### Phase 4: Deployment
- [x] Owner `deploy now` (`DL-20260902-09`)
- [x] `terraform apply` initial plan (Redis + stack in eastus)
- [x] Recovery: Postgres `postgres_location=centralus` after eastus Flexible Server restriction
- [x] `terraform apply` recovery plan (3 adds) — `APPLY_EXIT:0`
- [x] Azure RG resource list — all `Succeeded`
- [x] Owner authorized residual with
  `AUTHORIZE D2 ACR PUSH AND APP WIRING` (`DL-20260903-02`)
- [x] ACR image built/pushed and API/worker pinned to the same digest
- [x] Key Vault/UAMI Postgres and Redis refs wired; Celery command active
- [x] Synth migration applied; API health and worker readiness verified

---

## 8. Validation / deploy proof

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| terraform fmt -check | `hashicorp/terraform:1.9` via docker cp into container | ✅ Pass | 2026-09-02T23:42Z |
| terraform init -backend=false | same; azurerm 4.81.0 + random 3.9.0 | ✅ Pass | 2026-09-02T23:42Z |
| terraform validate | same | ✅ Pass | 2026-09-02T23:42Z |
| terraform apply (initial) | `.tools/terraform apply tfplan` → `/tmp/cosmas-os-tf-apply.log` | ⚠️ Failed on PG Version in eastus after Redis complete (~23m) | 2026-09-03T00:08Z |
| terraform apply (recovery) | `tfplan-recovery` → `/tmp/cosmas-os-tf-apply-recovery.log` | ✅ `APPLY_EXIT:0` — 3 added | 2026-09-03T00:20Z |
| az resource list RG | `cosmaneura-os-synth` | ✅ All Succeeded | 2026-09-03T00:20Z |
| ACR QuickRun | `ca1` from source `81d75c3`; Linux/amd64 push | ✅ digest `sha256:af48b5b…a6be` | 2026-09-03T10:05Z |
| residual terraform plan | saved, sanitized review before apply | ✅ 2 add / 2 update / 0 destroy or replace | 2026-09-03 |
| residual terraform apply | reviewed saved plan | ✅ 2 added / 2 changed / 0 destroyed | 2026-09-03 |
| migration | Container Apps exec: upgrade, then `alembic current --check-heads` | ✅ `0001_initial (head)` | 2026-09-03T10:14Z |
| API smoke | public `GET /health` | ✅ HTTP 200 `synth_os` | 2026-09-03T10:13Z |
| worker smoke | aggregate-only Log Analytics query | ✅ connected + ready; 0 error/failure signals | 2026-09-03T10:14Z |
| post-apply plan | refresh-backed detailed-exitcode plan | ✅ 0 add / 0 change / 0 destroy | 2026-09-03T10:17Z |
| GitHub `synth-ci` | runs [33741787268](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33741787268) and [33742668350](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33742668350) | ✅ all five jobs on both commits | 2026-09-03 |

**API URL:** https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io

**Deployed names (sanitized):** ACR `cosmasossynthacrrkpt0e`, CAE `cae-cosmasossynth-rkpt0e`, API `ca-api-cosmasossynth`, worker `ca-worker-cosmasossynth`, PG `pg-cosmasossynth-rkpt0e` (centralus), Redis `redis-cosmasossynth-rkpt0e`, KV `kvcosmasossynthrkpt0e`, storage `cosmasossynthstrkpt0e`, LAW `law-cosmasossynth-rkpt0e`, identity `id-cosmasossynth`.

**Runtime image:** `cosmasossynthacrrkpt0e.azurecr.io/cosmas-os@sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be`

**Active revisions:** API `ca-api-cosmasossynth--0000001`; worker
`ca-worker-cosmasossynth--0000001` (both Healthy/Provisioned).

**Validated by:** infrastructure apply `DL-20260902-09` + runtime residual
`DL-20260903-02`
**Validation timestamp:** 2026-09-03T10:19Z

---

## 9. Files Generated

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | This plan | ✅ |
| `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md` | Design | ✅ |
| `infra/*.tf` | Terraform scaffold | ✅ |
| `infra/.terraform.lock.hcl` | Provider lock | ✅ |
| `infra/terraform.tfvars.example` | Non-secret examples | ✅ |
| `infra/README.md` | init/plan, deployed runtime, and remaining gates | ✅ |
| `Dockerfile` | Pinned-uv API/worker image | ✅ |
| `azure.yaml` | Not using AZD | ❌ skip |

---

## 10. Next Steps

> Current: **D2 complete** — non-PHI synth infrastructure and runtime are up

1. ✅ D2 source and evidence committed/pushed as
   `b54f4c4f90d460beb2bdd14dc7164ade8887d81a`; GitHub `synth-ci` run
   [33739304958](https://github.com/CosmaNeura/cosmaneura-os/actions/runs/33739304958)
   passed, including the aggregate gate.
2. ✅ D2 runtime source and digest commits `81d75c3` / `471f56f`; both
   GitHub workflows passed. Apps are healthy and Terraform is converged.
3. Keep D3 separately gated by
   `APPROVE D3 ISOLATED EARLY-ADOPTER BETA`.

---

## 11. Hard stops

- No Track A resource mutation
- No secrets in git (`infra/.apply-env` local-only)
- No PHI
- No further Azure mutation without the exact applicable owner phrase


---

## 12. Apply outcome (DL-20260902-09)

**Status:** Deployed (partial first apply recovered)

| Item | Value |
|------|-------|
| Subscription | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` |
| Resource group | `cosmaneura-os-synth` (eastus) |
| First apply | Failed: `azurerm_postgresql_flexible_server.synth` — `ParameterOutOfRange` Version should be in `[]` (eastus Flexible Server provisioning restricted) |
| Recovery | `postgres_location=centralus`; re-plan/apply added Postgres server + DB + Azure-services firewall rule (3 resources). No destroy. |
| API URL | https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io |
| Postgres FQDN | `pg-cosmasossynth-rkpt0e.postgres.database.azure.com` (Central US, v16) |
| ACR | `cosmasossynthacrrkpt0e.azurecr.io` |
| Key Vault URI | `https://kvcosmasossynthrkpt0e.vault.azure.net/` |

RG resources (all Succeeded): ACR, UAMI, Storage, Redis, Key Vault, LAW, CAE, API/Worker Container Apps, Postgres Flexible Server.

---

## 13. Runtime residual outcome (DL-20260903-02)

| Item | Value |
|---|---|
| ACR digest | `sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be` |
| API revision | `ca-api-cosmasossynth--0000001` — 1 replica, 100% traffic |
| Worker revision | `ca-worker-cosmasossynth--0000001` — 1 replica, Celery ready |
| Secrets | Key Vault names `database-url`, `redis-url`; values not queried or logged |
| Managed identity | `id-cosmasossynth` for ACR pull and Key Vault resolution |
| Migration | `0001_initial (head)` |
| Terraform convergence | 0 add / 0 change / 0 destroy |

Pre/post state backups are local-only, mode `0600`, and SHA-256 identified in
`BUILD_REPORT.md`. State and binary plans contain sensitive values despite CLI
redaction and must never be committed or rendered to logs.

### D2-only exposure and rollback limits

- API ingress is external, header identities are caller-controlled, and CORS
  is wildcard. This is not real authentication and no PHI is allowed.
- PostgreSQL remains public with `AllowAzureServices`. D3 must tighten it.
- `BLOB_ROOT=/tmp/cosmas-os-blobs` is ephemeral and per replica. API max
  replicas is 1; the provisioned Azure Blob container is not used by the app.
- This is the first functional OS digest. The prior mutable
  `helloworld:latest` placeholder is not a rollback target; the current digest
  becomes the known-good baseline for the next release.
