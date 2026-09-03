# Azure Deployment Plan

> **Status:** Deployed

Generated: 2026-09-02T23:30:00Z
Updated: 2026-09-03T00:20:00Z (D2 apply close-out)

**Gate:** D2 live apply completed under `DL-20260902-09` (`deploy now`). Track A untouched. No PHI.

Design spec: `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md`
Decision: `DL-20260902-08` (+ owner choices depth 3, region B, tooling 1); apply auth `DL-20260902-09`

---

## 1. Project Overview

**Original goal:** Scaffold Terraform for optional non-PHI Cosmas OS Azure
development without joining Track A. The scaffold was later applied under
`DL-20260902-09`; most resources are in `eastus` and PostgreSQL is in
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
| Blobs | Storage Account + container | Standard LRS |
| Secrets | Key Vault | Standard |
| Identity | User-assigned managed identity | for ACA → ACR/KV/Storage |

### Supporting Services

| Service | Purpose |
|---------|---------|
| Log Analytics | Centralized logging for ACA |
| Key Vault | Reserved for residual app secrets; no values committed and app wiring remains incomplete |
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
- [ ] ACR image push + digest pin — requires
  `AUTHORIZE D2 ACR PUSH AND APP WIRING`
- [ ] App wiring to Postgres/Redis secrets beyond scaffold placeholders — same
  exact residual gate

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

**API URL:** https://ca-api-cosmasossynth.delightfulsmoke-58dcae81.eastus.azurecontainerapps.io

**Deployed names (sanitized):** ACR `cosmasossynthacrrkpt0e`, CAE `cae-cosmasossynth-rkpt0e`, API `ca-api-cosmasossynth`, worker `ca-worker-cosmasossynth`, PG `pg-cosmasossynth-rkpt0e` (centralus), Redis `redis-cosmasossynth-rkpt0e`, KV `kvcosmasossynthrkpt0e`, storage `cosmasossynthstrkpt0e`, LAW `law-cosmasossynth-rkpt0e`, identity `id-cosmasossynth`.

**Validated by:** D2 scaffold workflow + live apply under `DL-20260902-09`
**Validation timestamp:** 2026-09-03T00:20Z

---

## 9. Files Generated

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | This plan | ✅ |
| `docs/superpowers/specs/2026-09-02-d2-terraform-scaffold-design.md` | Design | ✅ |
| `infra/*.tf` | Terraform scaffold | ✅ |
| `infra/.terraform.lock.hcl` | Provider lock | ✅ |
| `infra/terraform.tfvars.example` | Non-secret examples | ✅ |
| `infra/README.md` | init/plan and exact residual/destroy gates | ✅ |
| `Dockerfile` | Existing API/worker image | ✅ (keep) |
| `azure.yaml` | Not using AZD | ❌ skip |

---

## 10. Next Steps

> Current: **Deployed** — infra up; runtime image still placeholder

1. Commit/push the D2 source and evidence under the hygiene authorization in
   `DL-20260903-01`; record the resulting CI evidence.
2. Wait for `AUTHORIZE D2 ACR PUSH AND APP WIRING` before ACR image push,
   digest pinning, app connection settings, migrations, or cloud smoke tests.
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
