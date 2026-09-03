# D2 Terraform — Cosmas OS synth (non-PHI)

**Gate:** Live apply authorized and completed under `DL-20260902-09` (`deploy now`).
Further destructive changes still need owner instruction. Track A state never used.

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
# terraform apply  # only after the exact applicable owner gate
```

Or via Docker (no host Terraform install):

```bash
docker run --rm -v "$PWD/infra:/work" -w /work hashicorp/terraform:1.9 init -backend=false
docker run --rm -v "$PWD/infra:/work" -w /work hashicorp/terraform:1.9 validate
```

## Secrets

- Copy `terraform.tfvars.example` → `terraform.tfvars` only if needed; keep secrets out of git.
- Prefer `TF_VAR_postgres_admin_password` or local `infra/.apply-env` (gitignored) — never commit.

## Gated residual work

1. Build/push the synth image to the OS ACR only after
   `AUTHORIZE D2 ACR PUSH AND APP WIRING`.
2. Set `api_image` / `worker_image` to ACR digests.
3. Run migrations with synth fixtures only.
4. Destroy only after `DESTROY COSMANEURA-OS-SYNTH`.
