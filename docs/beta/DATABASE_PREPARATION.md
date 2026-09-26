# D3 database preparation and evidence

Status: **source implemented and locally verified; no D3 job or database has
been deployed**.

The D3 database path is a manually triggered Azure Container Apps Job inside
the isolated Container Apps environment. It is not a scheduled job, Terraform
does not start it, and its image is the same reviewed `cosmas-os@sha256:...`
digest later used by the API and worker.

## Security contract

The job runs `python -m cosmas_os.cli prepare-beta-database
--confirm-forward-only` and:

1. validates that the administrator and runtime URLs target the same dedicated
   `cosmas_os` database, use different roles, and require
   `sslmode=verify-full&sslrootcert=system`;
2. takes a PostgreSQL advisory lock so two operator starts cannot race;
3. creates the runtime login when absent, or rotates its password when present,
   and enforces `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`,
   and `NOBYPASSRLS` with no inherited role memberships;
4. applies the image's forward-only Alembic graph and requires its sole head to
   equal the revision compiled into that image;
5. grants ordinary application DML but denies persistent schema/database
   creation, temporary-table creation, ownership of application objects,
   mutation of `alembic_version`, and `UPDATE`, `DELETE`, or `TRUNCATE` on
   `audit_events`;
6. connects as the runtime role and performs real, rollback-safe denial probes
   for `CREATE TABLE`, audit `UPDATE`, and audit `DELETE`; and
7. emits one deterministic, credential-free JSON evidence record. It never
   emits a URL, hostname, user name, password, SQL error, or database contents.

The runtime API/worker identity cannot read the administrator URL. The job has
a separate user-assigned identity whose only Azure data-plane permission is
`AcrPull`. Its two database URLs are isolated Container Apps Job secrets held
in protected Terraform state and the job resource. The administrator
credential is never mounted in the API or worker.

## Three-stage deployment

### 1. Foundation

Apply with both switches false:

```hcl
enable_database_preparation_job = false
deploy_workloads                = false
```

This stage creates networking, private services, ACR, and the Container Apps
environment. It creates no application revision, database-preparation job,
artifact Blob container, or Key Vault workload secret. Consequently the
foundation plan does not require Key Vault or workload Blob data-plane access.

### 2. Manual database preparation

After the exact reviewed application digest has been pushed, prepare a
protected `0600` variable file containing the non-admin runtime URL and plan:

```hcl
enable_database_preparation_job = true
deploy_workloads                = false
database_preparation_image_digest = "<64-lowercase-hex-digest>"
runtime_database_url            = "<protected verify-full non-admin URL>"
runner_live_network_evidence_reference = "<protected live connectivity evidence reference>"
```

The plan and state contain database credentials. Keep both encrypted and out of
source, tickets, chat, and ordinary logs. A named human reviews and applies the
saved plan, then starts and attests exactly one execution through the protected
runner:

```text
bash ./infra/beta/transport-to-protected-runner.sh database-prepare \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id REVIEWED_RELEASE_ID \
  --artifact-out /protected/ephemeral/database-preparation-attestation.json
```

This command verifies the job name, environment, UAMI, registry identity,
digest, command, secret references, and exact private database before starting
it. It waits for the bound execution, reads only one credential-free contract
record, validates its canonical self-hash, and returns a structured sanitized
attestation. Its current job log stream follows the pinned official Azure CLI
Container Apps extension's preview REST flow; failure of that live preflight is
a hard stop. Do not add a schedule, event trigger, mutable tag, retry loop,
`az containerapp exec`, or API/worker administrator secret.

The job has `parallelism = 1`, one required completion, no automatic retry, and
a 15-minute timeout. A nonzero execution result is a hard stop. A failed run is
safe to investigate and manually rerun after correction: role setup, forward
migration, grants, and verification are idempotent, while the advisory lock
serializes overlapping starts.

The success record has this public-safe shape:

```json
{"audit_delete_denied":true,"audit_update_denied":true,"contract":"cosmas-os-d3-database-preparation-v1","evidence_sha256":"<sha256>","runtime_ddl_denied":true,"runtime_role_non_admin":true,"schema_at_expected_head":true,"schema_revision":"<selected_schema_revision>","status":"ready"}
```

The emitted `schema_revision` must match `schema_revision` in the selected
[`release-schema.json`](../../infra/beta/environment/release-schema.json) for
the exact reviewed application source/image. Its source-graph validation is
defined by `infra/beta/validate_release_schema.py`; do not substitute a historical
revision or turn this example into an attestation.

Record the immutable image digest, Azure job execution identity and completion
time, the actual returned JSON, and its hash in the protected deployment record.
Do not copy the job definition, environment variables, Terraform plan/state,
or raw platform diagnostics into the evidence record. The live execution—not a
placeholder string—is the evidence for both the role and migration gates.

### 3. Workloads

Only after the live success record is reviewed may a human supply the
structured `database_preparation_attestation` and plan with
`deploy_workloads = true`. The attestation records the immutable image digest,
expected schema revision, evidence SHA-256, exact Box ID, exact database-server
resource ID, and full Azure job-execution resource ID.
Terraform rejects a missing attestation or one whose image digest does not
equal the API/worker digest. It also requires the preparation job to remain
declared. The workload stage creates the private artifact container and Key
Vault workload secrets only after the separate
`runner_live_network_evidence_reference` records live private DNS and endpoint
reachability from the protected runner.

Evidence fields are necessary gates, not self-attesting proof. Never invent a
reference, paste a credential into it, or enable workloads because the local
test passed. Local validation proves the implementation; only the completed
isolated Azure execution proves the deployment.

## Recovery and future migrations

- Do not downgrade the live database. Correct a failed or incompatible schema
  with a reviewed additive migration and a new image digest.
- Rerunning the job rotates the runtime password to the protected URL and
  reapplies the exact privilege contract.
- For an upgrade, keep `deploy_workloads = true` and the currently attested
  `image_digest` live while advancing only
  `database_preparation_image_digest`. Run and review that candidate job, then
  promote the API/worker digest in a second plan with the new matching
  attestation. Never disable workloads as a migration-staging shortcut.
- Restore fingerprinting uses the protected non-admin runtime `database-url`
  from Key Vault and passes it to the digest-pinned image through a short-lived
  mode-`0600` env file. The administrator URL is not used by PITR acceptance. A
  restored database must pass this job again before it can receive traffic.
