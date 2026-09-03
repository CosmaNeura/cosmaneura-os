# D2 Terraform Scaffold Implementation Plan

> **For agentic workers:** Execute task-by-task. No `terraform apply` in this plan.

**Goal:** Add OS-owned Terraform under `infra/` for `cosmaneura-os-synth` in `eastus` and prove `terraform validate` without creating Azure resources.

**Architecture:** Single-root Terraform module declaring RG, ACR, Log Analytics, Container Apps Environment, API + worker apps, Postgres Flexible Server, Redis Basic, Storage, Key Vault, and a user-assigned identity. Local backend only. Secrets via `TF_VAR_*` at future apply time — never committed.

**Tech Stack:** Terraform >= 1.5, AzureRM provider ~> 4.x, existing repo Dockerfile.

## Global Constraints

- Subscription: `bab2a709-1fcb-4c87-a9fc-802f7477ec13`
- Location: `eastus`
- RG name: `cosmaneura-os-synth`
- Tags: `track=B`, `product=cosmas-os`, `env=synth_os`, `phi=false`
- No Track A state (`cosmaneura-tfstate`), no PHI, no apply
- Existing Dockerfile retained

---

### Task 1: Core Terraform skeleton

**Files:**
- Create: `infra/versions.tf`, `infra/providers.tf`, `infra/variables.tf`, `infra/locals.tf`, `infra/main.tf`, `infra/outputs.tf`, `infra/terraform.tfvars.example`, `infra/README.md`

- [x] **Step 1:** Write versions/providers (azurerm ~> 4, local backend)
- [x] **Step 2:** Variables for subscription, location, name_prefix, postgres password (sensitive, no default), image placeholders
- [x] **Step 3:** Locals for tags and naming; RG resource

### Task 2: Supporting + data plane resources

**Files:**
- Create: `infra/acr.tf`, `infra/monitoring.tf`, `infra/storage.tf`, `infra/keyvault.tf`, `infra/postgres.tf`, `infra/redis.tf`, `infra/identity.tf`

- [x] **Step 1:** ACR Basic, Log Analytics, Storage + container, Key Vault, UAMI
- [x] **Step 2:** Postgres Flexible B1ms + db; Redis Basic C0
- [x] **Step 3:** Role assignments placeholders only where valid without circular apply issues

### Task 3: Container Apps

**Files:**
- Create: `infra/container_apps.tf`

- [x] **Step 1:** ACA environment wired to Log Analytics
- [x] **Step 2:** API + worker container apps with placeholder images and synth env vars

### Task 4: Docs + validate

**Files:**
- Modify: `.azure/deployment-plan.md`, `docs/RELEASE_AND_ROLLBACK.md`, `BUILD_REPORT.md`

- [x] **Step 1:** Document init/plan; apply gated
- [x] **Step 2:** `terraform init -backend=false` && `terraform validate` (install Terraform if missing)
- [x] **Step 3:** Record proof in deployment-plan; **no apply**
