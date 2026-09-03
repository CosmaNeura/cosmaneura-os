# Release and rollback (synthetic D1 / Azure D2)

Status: D1 local release flow and D2 Azure runtime verified
Updated: 2026-09-03

The D1 workflow produces a **pinned local container image and release
manifest** without a registry push or deployment. The separately authorized D2
runtime section below records the deployed ACR digest and cloud rollback rules.

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

## D1 local image rollback

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
- The D2 residual was applied under `DL-20260903-02`. API revision
  `ca-api-cosmasossynth--0000001` and worker revision
  `ca-worker-cosmasossynth--0000001` are healthy on:
  `cosmasossynthacrrkpt0e.azurecr.io/cosmas-os@sha256:af48b5b22b15d64f5592405a7ac041237224fb7a1ed05b8041e0b60f5a5ca6be`.
- Both apps resolve `database-url` and `redis-url` from Key Vault through the OS
  managed identity. `alembic current --check-heads` returned
  `0001_initial (head)` and `/health` returned HTTP 200 for `synth_os`.
- A refresh-backed post-apply `terraform plan` returned no changes. Init,
  validate, and plan remain the default review path; any later apply requires
  its applicable exact owner gate.
- State must stay OS-local (or a future OS-named backend) — never Track A `cosmaneura-tfstate`.
- Only `DESTROY COSMANEURA-OS-SYNTH` authorizes retiring the synth resource
  group.

### D2 image rollback

This is the first functional Cosmas OS digest in ACR. Its predecessor was
mutable `helloworld:latest`, not a functional product rollback target, and the
Single-mode apps expose no prior live OS revision. Therefore an immediate
rollback must be a fix-forward deployment of another tested immutable OS
digest; do not reactivate or record the placeholder as a valid rollback.

For the next release, retain the current digest above as the prior known-good
baseline. Restore it only when it is compatible with the current forward-only
database schema. After the applicable owner authorization:

```bash
cd infra
source ./.apply-env
TF_VAR_api_image='<prior-acr-ref>@sha256:<digest>' \
TF_VAR_worker_image='<prior-acr-ref>@sha256:<digest>' \
  ../.tools/terraform plan -out=tfplan-rollback
# Review: only API/worker image revisions; no delete or replacement.
../.tools/terraform apply tfplan-rollback
```

Then verify the exact active digest, revision health, `/health`, worker-ready
signal, and `alembic current --check-heads`. Database migrations are
forward-only in Azure D2: do not use the destructive local downgrade examples
against the cloud database. If a new release needs a schema correction, add a
new migration and roll forward.

Current D2 limits remain part of rollback acceptance: the externally reachable
API uses fake caller-controlled identity headers and wildcard CORS, PostgreSQL
retains public `AllowAzureServices`, and `BLOB_ROOT` is ephemeral per replica.
No PHI is allowed.

## Secrets policy

CI and release scripts use only synthetic Compose credentials from
`.env.example` placeholders. No Clerk, Stripe, Athena, Acuity, or production
GitHub deploy identities. Azure connection values are active behind Key Vault
references; apply-time secrets use `TF_VAR_*` only. Terraform state, backups,
and saved plans contain sensitive derived URLs even when console output is
redacted: keep them local, ignored, mode `0600`, and never commit or log them.

## Explicit non-goals (until separately authorized)

- Further Azure mutation without its exact owner gate
- Auto-promote to early-adopter beta
- Track A integration  
- Clerk, real-vendor, or PHI activation
