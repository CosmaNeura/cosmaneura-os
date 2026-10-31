# Independent enrollment staging foundation

This definition prepares the missing Azure foundation for the browser enrollment
flow. It is fixed to `staging`, with `centralus` as the default region and only
`centralus` or `eastus2` accepted; it cannot create production resources.
It neither deploys an application nor marks registration, billing, workspaces or
a customer journey qualified. No existing VM, Core, clinical database, vault,
state backend or VNet is consumed or changed.

Authenticated staging capability checks rejected PostgreSQL provisioning in
East US 2 and East US. Central US supports the selected PostgreSQL 16 /
`B_Standard_B1ms` / 32 GiB footprint and Container Apps, so fresh protected
preparation now selects Central US by default. East US 2 remains an explicit
Terraform option for a separately measured capacity recovery. The definition
does not accept East US or other regions. The selected location flows into the
new resource group, regional services, network and private endpoints; DNS zones
retain their global scope. Capability discovery does not qualify an actual
deployment or customer journey.

The default footprint is one new `rg-cosmabot-enrollment-staging-<suffix>` with:

- A fresh private `/20` VNet, delegated `/23` Container Apps subnet, delegated
  `/26` PostgreSQL subnet and `/26` private-endpoint subnet. No peering, VM,
  SSH ingress, NAT gateway or customer data storage is added.
- A workload-profiles Container Apps environment containing only Consumption;
  external HTTPS app ingress is supplied later by `../runtime/`. Azure-managed
  outbound connectivity must be measured on the actual deployment.
- Private PostgreSQL 16 (`B_Standard_B1ms`, 32 GiB, seven-day local backups,
  auto-grow, required TLS), one `cosmabot_enrollment` database and its private
  DNS link. This is a staging sizing assumption; HA/geo-backup is not enabled.
- A private RBAC Key Vault, private endpoint/DNS, purge protection and 90-day
  soft deletion. Bootstrap/migration and application secrets share this owned
  vault, but their managed identities receive disjoint per-secret read scopes.
- A dedicated Basic ACR with TLS and Entra/managed-identity authentication,
  administrator and anonymous access disabled. Its public endpoint contains
  code images only; credentials, data, tokens and `.env` files must never be
  built into an image. Private Premium ACR is deliberately not required here.
- A dedicated TLS Blob state account/container: public containers/shared keys
  disabled, Entra auth, default-deny network ACL, no bypass, one reviewed public
  operator IPv4 address (one `/32`), versioning and seven-day soft deletion.
  Database and vault endpoints remain private. The allowed IP is for the actual
  off-Azure operator; same-region Azure requests need a separately reviewed
  private route rather than a wider IP rule.
- Log Analytics with 30-day retention and a 0.1 GiB/day cap. This limits cost,
  and does not promise logs beyond that cap.

Use a fresh 6–8 character suffix (Key Vault's 24-character name limit), a verified
operator object ID/public IPv4 and a non-overlapping private `/20`. Names, tenant,
subscription, address space and Azure capacity are actual operator inputs; the
mock test fixture names are not deployment choices. The operator must already
hold the necessary new-RG deployment/provider/role-assignment authority. The
foundation grants only scoped ACR publication and its own state-container access
to that principal; it grants no new vault data-plane reader or global role.

## Protected foundation plan

OpenTofu **1.12.5** and AzureRM **4.81.0** are pinned. Start with enforced encrypted
local state/plan in a fresh owner-only directory outside the repository. Never
copy another application's state or backend. Preserve the encryption passphrase
through rollback/backup; losing it makes this state unreadable.

Create one owner-only `0600` JSON input file containing exactly these public keys:
`subscription_id`, `tenant_id`, `resource_name_suffix`, `vnet_address_prefix`,
`release_operator_object_id`, `state_operator_ipv4`. Then:

```sh
python infra/enrollment/foundation/prepare.py prepare --inputs /protected/foundation-inputs.json --directory /protected/new-enrollment-foundation
python infra/enrollment/foundation/prepare.py plan --directory /protected/new-enrollment-foundation
```

Preparation performs no Azure operation. It snapshots/hashes the Terraform
source/lock/helper and public inputs, pins the installed OpenTofu executable,
generates protected encryption/bootstrap password files, and isolates its local
backend/provider directory. Planning checks the exact Azure tenant/subscription
and refuses to adopt an existing initial RG. It rejects ambient `TF_*`, `ARM_*`
and encryption overrides. Its PostgreSQL password is ephemeral and flows only
to AzureRM's `administrator_password_wo`; neither state nor saved plan contains
that value. Keep debug logging disabled. The password file remains in protected
operator custody for server bootstrap and any reviewed rotation.

No apply was run during source preparation. For the eventual reviewed staging
plan, the protected wrapper supports `apply --directory ... --plan-sha256 <exact
encrypted-plan-hash>`. It rechecks source, inputs, executable and account; it
supplies the ephemeral password again without putting it in command arguments.
Export the actual local state's public coordinates using the same private
backend/key/provider configuration:

```sh
python infra/enrollment/foundation/prepare.py export --directory /protected/new-enrollment-foundation --output /protected/foundation.json
```

The export verifies the stored environment, namespace and tenant/subscription,
and writes only resource coordinates to a fresh protected file. Keep the
local encrypted foundation state and its recovery passphrase under independent
operator custody. The exported `state_backend.key` names the central API state
only. Initialize `../runtime/` against that new Blob container; database-job
uses distinct `database-bootstrap-v1.tfstate`, `database-migrate-v1.tfstate` and
`database-check-v1.tfstate` keys. Never reuse the API key for a job operation or
move the foundation state into it. The Blob account enforces infrastructure
encryption at rest and Entra-only access. Runtime/database-job do not currently
define OpenTofu client-side state/plan encryption, so do not represent them as
using the foundation's encryption passphrase. Their actual backend access,
locking and recovery custody still require verification.

## Secret seed and SQL roles

Microsoft documents `Microsoft.KeyVault/vaults/secrets@2024-11-01` ARM creation
with `properties.value`, which is never returned. `secret.template.json` uses a
`secureString` deployment parameter, and `seed_secret.py` accepts only a private
`0600` file. It sends a protected temporary parameter file to ARM, captures both
CLI streams without forwarding provider errors, and records only the exact
versioned secret URI returned by ARM metadata. It never opens the vault data
endpoint, retrieves a value or writes one into Terraform. Actual ARM seeding
permission/behavior on this new private vault must be measured after creation;
a documented API and a fake transport test are not that evidence.

The deployer needs `Microsoft.Resources/deployments/*` on this RG and
`Microsoft.KeyVault/vaults/secrets/write/read` on this vault for that ARM route.
This is control-plane deployment authority, distinct from runtime secret read.
The selected operator already needs scoped deployment authority; no VM or new
global administrator role is introduced to seed credentials.

After actual foundation creation/export:

```sh
python infra/enrollment/foundation/prepare_database_credentials.py --foundation /protected/foundation.json --admin-password-file /protected/new-enrollment-foundation/postgres-admin.password --directory /protected/new-database-urls
python infra/enrollment/foundation/seed_secret.py --foundation /protected/foundation.json --secret-name enrollment-bootstrap-database-url --value-file /protected/new-database-urls/bootstrap.url --receipt /protected/new-bootstrap-reference.json
```

Seed `migrator.url` as `enrollment-migration-database-url` and `runtime.url` as
`enrollment-database-url` in the same way. These URLs bind the exact new host,
database, separate login and `sslmode=verify-full` with the image's CA bundle.
Generation prints no URL/password and does not create users or claim readiness.
Retain these exact protected files until role/seed recovery is established;
generating new files later is credential rotation, not a lost-response retry.

Use the manual job in `../database-job/` for actual private PostgreSQL bootstrap,
migration and checks. `enrollment_bootstrap` creates only fixed non-admin
`enrollment_migrator` and `enrollment_runtime` logins. The migrator owns DDL;
runtime gets CONNECT/USAGE and exact table DML, BAA INSERT/SELECT only, version
SELECT only, no DDL/TRUNCATE/role membership/other-database access. Every additive
migration reruns the exact grant projection; there are no broad future grants.
Known Azure-owned `azure_maintenance`/`azure_sys` databases are never changed;
the check requires them inaccessible to runtime and rejects unrelated databases.
Existing BAA triggers protect receipts even from migration-owner update/delete.

Bootstrap job failure remains unqualified. Recover with the same protected
URLs/reference versions. Delete the bootstrap job, identity and its three
secret-read assignments through a reviewed plan after successful preparation;
keep migration/check authority separate and unscheduled. Do not grant bootstrap
or migration references to the API. `../runtime/main.tf` explicitly rejects them
and authorizes only the actual rendered application secret names.

## Integration and remaining hosted measurements

1. Review actual names, `/20` non-overlap, exact operator IP, subscription/tenant,
   resource-provider registration and Central US PG16/Consumption capacity, then
   inspect/apply the protected foundation plan. Preserve its encrypted state.
2. Export public foundation coordinates. Initialize database-job and runtime
   separately against the new `state_backend` coordinates, with the distinct
   Blob keys above and private provider-data directories. Verify actual storage
   encryption, Entra authentication, exact-IP access and backend locking with
   the approved operator's existing scoped state-container authority; a mock
   plan or control-plane storage response does not establish this data path.
3. Publish the CI-qualified application image into the new Basic ACR, and build
   the small database job image from that exact digest. Seed the three DB URLs
   through ARM; prepare/run the manual bootstrap, migrate and check jobs.
   Measure private DNS/TLS, failure/retry/restart and an actual independent
   restore. A job output that checks SQL grants is not restore qualification.
4. Root handles the matching development Clerk app and Stripe **test** resources
   and seeds their protected values. Renderer inputs contain only versioned
   references. Use app `https://onboarding.staging.cosmas.ai` and API
   `https://enrollment-api.staging.cosmas.ai`; leave the existing beta app intact.
5. Feed `foundation` output's RG/location/CAE/ACR/KV fields directly to
   `../runtime/main.tf`, together with the reviewed renderer directory. Keep
   `deploy_workload=false` and `database_preparation_qualified=false` until actual
   DB role/isolation/restore checks. The account web stage also requires this
   qualified API deployment and its own reviewed image digest. Keep every
   registration/billing/acquisition/activation flag false until its corresponding
   source-bound measurements and signed practice/browser/Stripe receipts exist.
   DNS/TLS, vendor validation,
   provisioning/admission, signature/webhook/portal and cancellation/recovery
   are measured deployment work; this definition invents none of those proofs.

The October 31, 2026 Azure price-metadata review, using 730 hours/month in Central
US, estimates a **$31.55/month** fixed foundation footprint. The two isolated
practice stores add **$134.73/month**, for **$166.28/month combined**. Container
Apps and manual-job Consumption usage is additional, as are variable Blob
storage/transactions, vault operations, telemetry, egress, backup overage,
third-party vendors and taxes. Free Consumption grants are shared at subscription
level. No VM/NAT/Premium ACR or Dedicated compute is budgeted. These metadata
estimates are not an Azure bill or allocation guarantee; retain the actual
reviewed subscription/region/SKU metadata with the protected deployment receipt.

## Local checks (synthetic only)

```sh
tofu -chdir=infra/enrollment/foundation fmt -check -recursive
tofu -chdir=infra/enrollment/database-job fmt -check -recursive
tofu -chdir=infra/enrollment/runtime fmt -check -recursive
```

With the pinned provider initialized in a separate temporary `TF_DATA_DIR` and
an invented private `TF_VAR_bootstrap_key_file` for foundation tests, run `tofu
validate` / `tofu test` in those three roots. Every `.tftest.hcl` uses mocked
providers. Runtime hosting also exercises mock-only applies in temporary local
state; no Azure backend or real resource apply is involved. Run the six
protected transport tests and fourteen temporary-PG role tests:

```sh
python -m pytest infra/enrollment/foundation/tests/test_bootstrap.py infra/enrollment/database-job/tests/test_roles.py -q --basetemp=/private/tmp/owned-enrollment-foundation-pytest
```

`test_roles.py` always starts/stops its own loopback PostgreSQL (set
`ENROLLMENT_FOUNDATION_POSTGRES_BIN` if `pg_config` selects another installation).
It never accepts a remote database URL or silently skips. Fake commerce verifies
the existing service can persist a synthetic journey under the restricted SQL
login; it does not claim Stripe/Clerk/Azure verification.

API reference:
https://learn.microsoft.com/en-us/azure/templates/microsoft.keyvault/2024-11-01/vaults/secrets
