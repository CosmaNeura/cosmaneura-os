# D2 Terraform — Cosmas OS synth (non-PHI)

**Gate:** Infrastructure apply completed under `DL-20260902-09`; ACR push and
application wiring completed under `DL-20260903-02`. Further mutations need
their applicable owner gate. Track A state was never used.

## Locked targets

| Item | Value |
|---|---|
| Subscription | `bab2a709-1fcb-4c87-a9fc-802f7477ec13` |
| Location | `eastus` (RG + most resources) |
| Postgres location | `centralus` (`postgres_location`) — Flexible Server restricted in eastus on this sub |
| Resource group | `cosmaneura-os-synth` |
| State | Local backend only — never Track A `cosmaneura-tfstate` |

## Commands

```bash
cd infra
terraform init -backend=false
terraform fmt -check
terraform validate
# Plan needs Azure login + TF_VAR_postgres_admin_password (or gitignored infra/.apply-env):
# export TF_VAR_postgres_admin_password='…'   # never commit
# terraform plan
# terraform apply  # only after review and the exact applicable owner gate
```

Or via Docker (no host Terraform install):

```bash
docker run --rm -v "$PWD/infra:/work" -w /work hashicorp/terraform:1.9 init -backend=false
docker run --rm -v "$PWD/infra:/work" -w /work hashicorp/terraform:1.9 validate
```

## Secrets

- Copy `terraform.tfvars.example` → `terraform.tfvars` only if needed; keep secrets out of git.
- Prefer `TF_VAR_postgres_admin_password` or local `infra/.apply-env` (gitignored) — never commit.
- API and worker resolve `database-url` and `redis-url` through Key Vault using
  `id-cosmasossynth`; do not query or print their values.
- Local state, backups, and binary plans contain sensitive derived connection
  data. Keep them ignored, untracked, mode `0600`, and never emit
  `terraform show -json` for them into logs.

## Current D2 runtime

- Both apps use
  `cosmasossynthacrrkpt0e.azurecr.io/cosmas-os@sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be`.
- API `ca-api-cosmasossynth--0000001` and worker
  `ca-worker-cosmasossynth--0000001` are healthy. The worker runs Celery with
  `SYNC_WORKER=false`; sanitized logs prove broker-connected and ready signals.
- `alembic current --check-heads` returns `0001_initial (head)` against the
  synth `cosmas_os` database. `/health` returns HTTP 200 and `synth_os`.
- The refresh-backed post-apply plan is `0 add / 0 change / 0 destroy`.

## D2-only limitations and remaining gates

- External API ingress has no real authentication: header identities are
  caller-controlled and CORS is wildcard. No PHI or real users.
- PostgreSQL public networking plus `AllowAzureServices` is retained only for
  D2 synth and must be tightened before any D3 PHI posture.
- `BLOB_ROOT=/tmp/cosmas-os-blobs` is ephemeral and per replica; API max
  replicas is 1. The provisioned Azure Blob container is not wired to the app.
- This is the first functional OS digest. The prior `helloworld:latest`
  placeholder is not a rollback artifact; this digest is the next release's
  baseline.
- D3 requires `APPROVE D3 ISOLATED EARLY-ADOPTER BETA`.
- Destroy requires `DESTROY COSMANEURA-OS-SYNTH`.
