# Release artifact and rollback (synthetic CI / D1)

Status: authorized by owner request for synthetic CI/release-artifact hardening  
Date: 2026-09-02

This stage produces a **pinned local container image and release manifest**. It
does **not** push to a registry, create cloud resources, or deploy.

## Artifacts

| Artifact | How produced |
|---|---|
| CI green on synth jobs | `.github/workflows/synth-ci.yml` |
| Local CI parity | `./scripts/ci-local.sh` |
| Image tag `cosmas-os:synth-<sha>` | `./scripts/release-artifact.sh` |
| Manifest JSON | `artifacts/releases/manifest-*.json` (+ `manifest-latest.json`) |

Manifest fields include `git_sha`, `image_tag`, `image_id`, `built_at`, and
explicit `deployed: false` / `pushed: false` / `cloud: false`.

## Required CI gates (must not be skipped)

1. Ruff + Pyright  
2. Alembic upgrade on empty/ephemeral Postgres  
3. Full Pytest suite (includes fixture scan)  
4. Demo ArtifactChase CLI  
5. Web test + production build  
6. Container image build + manifest (no push)  
7. Aggregate `synth-ci-gate` job  

## Migration apply / recovery

### Apply forward

```bash
uv run alembic upgrade head
# or from the release image:
docker run --rm --network host \
  -e DATABASE_URL=postgresql+psycopg://cosmas:cosmas@127.0.0.1:54329/cosmas_os \
  cosmas-os:synth-<sha> alembic upgrade head
```

### Inspect current revision

```bash
uv run alembic current
uv run alembic history
```

### Rollback one revision (local synth only)

```bash
uv run alembic downgrade -1
```

Full downgrade to empty (destroys synth schema — local only):

```bash
uv run alembic downgrade base
```

### Recovery after failed upgrade

1. Read the Alembic error; do not invent a partial schema fix by hand.  
2. If the transaction aborted cleanly, re-run `upgrade head`.  
3. If the database is inconsistent, prefer `downgrade` to last known good, fix
   the migration in a **new** revision, then upgrade again.  
4. Re-run `./scripts/ci-local.sh` before considering the artifact valid.  
5. Never point these recovery steps at Track A or production databases.

## Image rollback (pre-deploy)

Because images are not pushed in D1, “rollback” means rebuilding/retagging a
prior local tag from a known `git_sha` in a prior manifest:

```bash
git checkout <git_sha>   # when history exists
./scripts/release-artifact.sh
```

Compare `image_id` in `artifacts/releases/manifest-*.json`.

## D2 Azure synth infrastructure

See [`infra/README.md`](../infra/README.md) and [`.azure/deployment-plan.md`](../.azure/deployment-plan.md).

- The non-PHI Terraform stack was applied under `DL-20260902-09`; PostgreSQL
  recovered in `centralus` while the remainder stayed in `eastus`.
- API and worker still run placeholder `helloworld` images. No OS image has
  been pushed to ACR and no application migration has run against Azure.
- `terraform init -backend=false`, `terraform validate`, and `terraform plan`
  are the default review path. Any later apply requires its applicable exact
  owner gate.
- State must stay OS-local (or a future OS-named backend) — never Track A `cosmaneura-tfstate`.
- The D2 residual must use digest-pinned ACR images and document the prior
  digest for rollback.
- Only `DESTROY COSMANEURA-OS-SYNTH` authorizes retiring the synth resource
  group.

## Secrets policy

CI and release scripts use only synthetic Compose credentials from
`.env.example` placeholders. No Clerk, Stripe, Athena, Acuity, or
production GitHub deploy identities. Azure apply-time secrets use `TF_VAR_*`
only and must not be committed.

## Explicit non-goals (until separately authorized)

- ACR push or Container Apps application wiring
- Further Azure mutation
- Auto-promote to early-adopter beta  
- Track A integration  
