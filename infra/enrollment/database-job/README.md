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

## Provider-owned database policy and v2 receipt

The separate CosmaBot server contains exactly the enrollment database,
`postgres`, `template0`, `template1`, `azure_maintenance` and `azure_sys`.
Microsoft identifies the managed `azure_superuser` role and
[`azure_maintenance`](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-servers),
and documents PUBLIC views in the
[`azure_sys` Query Store](https://learn.microsoft.com/en-us/azure/postgresql/monitor/concepts-query-store).
PostgreSQL gives databases PUBLIC `CONNECT/TEMPORARY` by default and owners
`CREATE/CONNECT/TEMPORARY`, with implicit owner grant options
([privileges](https://www.postgresql.org/docs/16/ddl-priv.html)).

Our initial strict provider-owner allowlist is only `azure_superuser`. From the
existing enrollment connection, the check reads `pg_database`/`pg_roles` and
expands `COALESCE(datacl, acldefault('d', datdba))` with
[`aclexplode`](https://www.postgresql.org/docs/16/functions-info.html#FUNCTIONS-INFO-ACCESS-TABLE).
Each of the two provider databases must retain the three standard owner ACL
privileges. PUBLIC may have any subset of `CONNECT/TEMPORARY`, including no
access. All entries must be granted by that owner without explicit grant
options. Application owners/grantees, unknown owners,
grantees/grantors, PUBLIC `CREATE`, missing provider databases or additional
privileges fail closed. A mismatch emits only the fixed database names,
allowlisted role/privilege tags and booleans, with at most eight ACL rows per
database. Unknown names are redacted; this does not automatically extend the
allowlist.

The check never connects to a provider database or changes its permissions,
objects, Query Store or functions. Source custody is explicit: bootstrap's
database REVOKEs target only `cosmabot_enrollment`, `postgres` and `template1`;
its created/altered roles are only the two enrollment logins. Migration uses
the bound enrollment connection and changes its enrollment tables/schema
grants. The local role rehearsal measures provider ownership/ACLs before and
after actual bootstrap, migration and check, and verifies all preparation
connections stay in the enrollment database. That local evidence is not an
Azure pre-change fingerprint.

Success is `enrollment-database-check.v2`, preserving the schema/runtime-role/
immutable-receipt/table-count fields and adding
`managed_database_ownership_acl_checked: true`,
`provider_database_default_access_allowed: true`, `provider_database_count: 2`.
The second flag describes this accepted metadata policy, not a successful
provider-database connection. `azure_connectivity_qualified`,
`restore_qualified` and `journey_qualified` remain false. The runtime retains
its exact TLS database URL, no role memberships, NOINHERIT and non-DDL/non-TEMP
authority in the enrollment database, with exact table grants including
immutable BAA receipts.
