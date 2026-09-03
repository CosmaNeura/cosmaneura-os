# D2 non-PHI Azure — Terraform scaffold design

Date: 2026-09-02
Status: approved by owner; scaffold validated, then applied under
`DL-20260902-09`; runtime image push and app wiring remain gated
Authority: DL-20260902-08; owner choices depth **3**, region **B**, tooling **1**

## Goal

Add an **OS-owned Terraform scaffold** for optional non-PHI Azure development.
Declare infrastructure for a synthetic Cosmas OS runtime. **Do not**
`terraform apply`, push images to Azure, or connect Track A / MCD until a later
explicit owner “deploy now” message.

## Locked decisions

| Decision | Choice |
|---|---|
| Depth | IaC scaffold only (no apply) |
| Subscription | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` (default Sponsorship) |
| Region | `eastus` |
| Resource group | `cosmaneura-os-synth` |
| Tooling | Terraform under `infra/` |
| State | Local by default; optional OS-named remote state later — **never** `cosmaneura-tfstate` / Track A |
| Data | Synthetic only (`COSMAS_ENV=synth_os`, `phi=false` tags) |

## In scope (declared resources)

- Resource group `cosmaneura-os-synth`
- Azure Container Registry (Basic)
- Log Analytics workspace
- Container Apps Environment
- Container Apps: `api` and `worker` (image placeholders; no push required to plan)
- PostgreSQL Flexible Server (burstable / small) + database
- Azure Cache for Redis (Basic) **or** documented ACA Redis sidecar alternative via variable
- Storage account + container for synth BlobPort
- Key Vault (access via deployer identity placeholders; no secrets in git)
- User-assigned managed identity for ACA → ACR/KV/Storage

## Out of scope

- `terraform apply` / `azd up` / live resource create
- Clerk, Athena, Acuity, Stripe, real messaging, application LLM
- Track A VNet peering, shared service principals, shared Terraform state
- PHI, production credentials, production-like fixtures
- CI auto-deploy to Azure
- D3 beta isolation / BAA path

## Repo layout

```text
infra/
  versions.tf
  providers.tf
  variables.tf
  locals.tf
  main.tf          # RG, tags
  acr.tf
  monitoring.tf
  container_apps.tf
  postgres.tf
  redis.tf
  storage.tf
  keyvault.tf
  outputs.tf
  terraform.tfvars.example
  README.md        # init/plan only; apply gated
.azure/deployment-plan.md
docs/RELEASE_AND_ROLLBACK.md  # append Azure plan/apply/destroy notes (no apply)
```

## Safety rules

1. Default `terraform` workflow documented as `init` + `plan` only.
2. README and variables comment: apply requires exact owner phrase (or clear “deploy now”).
3. No passwords in `.tf` / committed `.tfvars`. Postgres admin via Key Vault reference or ephemeral `TF_VAR_` at apply time only.
4. Tags on all resources: `track=B`, `product=cosmas-os`, `env=synth_os`, `phi=false`.
5. Naming must not collide with `cosmaneura-prod` / Track A RGs.

## Success criteria

- `terraform fmt` / `terraform validate` succeed with local backend (no Azure create).
- Plan is human-reviewable; apply remains blocked by documentation + owner gate.
- Decision log records scaffold completion separately from any future apply.

## Non-goals for this slice

Proving a live HTTPS URL, running migrations in Azure, or registry push.
