# Manual private enrollment database preparation

This root consumes only the actual independent staging `foundation` JSON from
`../foundation/`. It creates one scoped manual job; it never starts it, schedules
it or changes readiness. Use distinct new Blob state keys for each operation
(`database-bootstrap-v1.tfstate`, `database-migrate-v1.tfstate`,
`database-check-v1.tfstate`), never the foundation or API state key.

Build from the exact CI-qualified application image in the **new owned ACR**:

```sh
docker build --file infra/enrollment/database-job/Dockerfile --build-arg APP_IMAGE=<owned-acr>/enrollment@sha256:<digest> --tag <owned-acr>/enrollment-database:<source-id> .
```

Publish and resolve its actual ACR SHA-256 digest; pass that digest to Terraform's
`image`, never a tag. The application image supplies its existing pinned Python,
psycopg, SQLAlchemy, migration and independent enrollment models. The small job
image adds only `database.py`. Verify those imports and the job image's exact
digest/build context before running; this source preparation did not build or
qualify a hosted image.

Inputs: subscription/tenant, `foundation_file`, exact `image`, `operation`,
`secret_references` (versioned URLs only), and `create_job` (defaults false).
For `bootstrap`, references have keys `admin`, `migration`, `runtime`; for
`migrate`, only `migration`, `runtime`; for `check`, only `runtime`. Their names
are fixed to `enrollment-bootstrap-database-url`,
`enrollment-migration-database-url`, `enrollment-database-url`. Cross-vault,
unversioned, privileged migration/check mounts and cross-ACR images are rejected.

Each operation has its own managed identity with AcrPull and Key Vault Secrets
User on exactly those secret names. It receives no Blob, deployment, clinical,
workspace or external provider role. `manual_trigger_config` is single-replica,
600-second timeout, zero automatic retries; a lost response is recovered by
reading the actual job execution and rerunning the same frozen credentials if
needed. No server password enters Terraform, arguments or logs.

After the reviewed job apply, start it explicitly (root owns this action):

```sh
az containerapp job start --resource-group <new-enrollment-rg> --name job-enrollment-db-bootstrap
```

Inspect that exact execution's completion and its fixed JSON receipt; follow with
the separately applied `migrate` and `check` jobs. Bootstrap is idempotent for the
same frozen credentials and refuses unexpected authority or unrelated database
objects. Migration keeps immutable receipts and explicit grants. The check
reports actual SQL schema/role/table/receipt protections, while restore/vendor/
journey flags stay false. Remove the bootstrap job/identity/read scopes after
qualification; never expose an API/bootstrap shortcut or grant runtime that URL.

Failures print only a fixed code and exception class, never SQL, URL, provider
error or environment. Actual private Azure connectivity, restart/restore,
runtime readiness and vendor/browser qualification are root deployment work.
