# Private staging Stripe clock journal

This module adds a separate private PostgreSQL 16/B1ms/32GiB server to the
already-owned enrollment staging foundation. It never alters the central
`cosmabot_enrollment` server, clinical databases, beta resources, public API
renderer, existing secret allowlist, or production settings. Only `centralus`
and `eastus2` are accepted; use the actual foundation's region (currently
Central US, after the subscription's East US 2 provisioning restriction).

The dedicated database is `cosmabot_enrollment_clock_lab`. It stores only the
private synthetic clock journal and immutable journal-role ownership. Two
approved `ClockLabBinding` documents later pin exactly two separate practice/Box/Org/
TEST-customer/clock scopes. Their canonical hashes, including the new journal
host, are public Terraform inputs; the documents remain protected operator
inputs. This setup does not prepare or advance Stripe clocks, check Clerk, or
qualify a registered runtime. `hosted_qualified` remains **false**.
Closed capacity starts with `binding_sha256:{}` and no job/runtime secret grants;
no placeholder hashes or customer bindings are needed before the server exists.

## Scope and custody

* A new private PostgreSQL DNS zone links only the owned VNet. The server uses
  the existing delegated `snet-postgres`; public PostgreSQL access is disabled.
  TLS `verify-full` with the system CA bundle is mandatory for job connections.
* The existing private enrollment vault receives **new** journal-only names.
  `seed_secret.py` uses ARM secureString parameters, captures all provider
  streams, and returns only an exact versioned secret reference. It refuses
  central/clinical credentials, foreign database/TLS URLs and unbound manifests.
  No vault firewall exception or broad vault role is added.
* `clock_bootstrap` is the server administrator used only by the manual setup
  job. `clock_journal_a` and `clock_journal_b` have no superuser, CREATEROLE,
  CREATEDB, replication, BYPASSRLS, role membership, schema CREATE, database TEMP,
  INSERT, DELETE, TRUNCATE or trigger privileges. They can SELECT/UPDATE only
  their pinned row under forced RLS. The owner policy is limited to the two
  registered rows; runtime roles cannot read the ownership table.
* Database guards preserve row identity, immutable original subscription and
  exact 1,209,600-second trial tuple, monotonic high-water and an unsettled target.
  Repeated bootstrap checks the original bindings and does not reset rows or
  pending progress. Only the clock module's normal row locks update progress.
  Azure's `azure_maintenance` and `azure_sys` databases are allowed but untouched;
  any other user database or unrelated table/view aborts setup.
* The job is unscheduled/manual, one replica, no retries, Consumption 0.5 vCPU/
  1GiB. Bootstrap gets four selected secrets; check gets three and excludes the
  administrator. Each separately reviewed composition identity receives only
  its own journal credential's **per-secret** Secrets User role. This module
  cannot attest preexisting grants on those identities; the operator must verify
  their ownership and absence of broader vault/administrative access.
* OpenTofu is exactly 1.12.5; AzureRM is exactly 4.81.0 with the portable lockfile.
  Separate local plan/state encryption is enforced with PBKDF2/AES-GCM.
  `administrator_password_wo` is ephemeral and never an ordinary state/input
  value. The protected wrapper seals source, foundation, backend, input and
  executable hashes, captures provider errors, and applies only the reviewed
  encrypted plan SHA. Concurrent operator commands are refused.

## Operator preparation and review

Use the actual exported foundation coordinates and a fresh reviewed journal suffix
for closed capacity. Approved protected bindings and the accepted application/job
image digest are needed only for later binding freeze and bootstrap.
**No cloud operation runs during prepare.**
All inputs and receipts must be owner-owned regular 0600 files; the new operator
directory is absolute 0700 and outside the source checkout. Never pass values in
arguments, print a password/URL/manifest, or use debug transport logging.

1. Prepare a 0600 public input JSON containing `subscription_id`, `tenant_id`,
   `resource_name_suffix` and `foundation_file`. Omit `binding_sha256` (defaults
   to `{}`), job inputs and runtime principal IDs initially; the closed server plan
   creates five Azure resources plus a Terraform guard and no workload/role assignment.
2. Run `python prepare.py prepare --inputs <public-inputs> --directory <fresh-private-directory>`.
   Immediately make a protected persistent backup of **the entire directory**,
   including source snapshot, receipt, encryption passphrase, admin/a/b
   passwords, and later encrypted state/plan. A `/private/tmp` copy alone is not
   durable custody. Verify backup file permissions and hashes without printing
   contents. Loss of the passphrase prevents decrypting the state; there is no
   reset/bypass/fallback key. Retain the reviewed source and pinned executable
   so the custody hashes can be revalidated during recovery.
3. Explicitly run `plan`, then `review-plan --output <fresh-private-review-json>`
   with the same `--directory`. The review JSON contains only addresses/types/
   actions and source/input/plan hashes. Review the actual scoped create plan and
   cost before `apply --plan-sha256 <reviewed-sha>`. No apply is authorized by
   preparing this module. Export actual coordinates with
   `export --output <fresh-private-coordinates>`; no generated key/state is exported.
4. After capacity exists, prepare the real Dev owner/practice/Box/release and
   approved TEST clock/customer bindings with the actual exported journal host,
   port 5432 and fixed journal database. Compute their canonical protected hashes.
   Run `configure-job` with all five closed-job fields (`operation:"check"`,
   `create_job:false`, `image:""`, `secret_references:{}`, `runtime_principal_ids:{}`)
   **plus** `binding_sha256:{a,b}`. This first freeze permits exactly two distinct
   hashes; subsequent changes/removal are refused. Plan/review/apply the output
   update and re-export coordinates containing the frozen hashes. Jobs and
   runtime secret grants are refused while bindings remain empty.
   Then run `urls` with the same directory. It writes fresh 0600 `admin.url`, `a.url`,
   and `b.url` files and prints no values. Pack the two already-qualified
   protected manifests with `prepare_bindings.py --coordinates <actual-coordinates>
   --binding-a <protected-a> --binding-b <protected-b> --output <fresh-protected-manifest>`.
   Pack validates canonical hashes and distinct scopes; it does not qualify
   vendor/runtime facts or modify the original binding documents.
5. Seed each selected value using `seed_secret.py --coordinates <actual-coordinates>
   --secret-name <fixed-name> --value-file <protected-file> --receipt <fresh-private-reference>`.
   Fixed names are `enrollment-private-clock-bootstrap-url`,
   `enrollment-private-clock-journal-a-url`, `enrollment-private-clock-journal-b-url`,
   and `enrollment-private-clock-bindings`. Preserve exact versioned references.
6. Build the one-purpose `Dockerfile` from the accepted owned application
   image@SHA, verify that it imports the clock module and SQL helper, then use
   the resulting owned job image@SHA. Do not use a tag or an image lacking the
   qualified clock source. This source check has not built or deployed that image.
7. Create a 0600 job-only configuration with **exactly** `operation`,
   `create_job`, `image`, `secret_references`, `runtime_principal_ids`. Do not
   resupply or change the previously frozen binding hashes.
   Bootstrap uses `operation:"bootstrap"`, `create_job:true`, exact selected
   reference keys `admin,a,b,bindings`, and optionally the separately reviewed
   composition principal map `a,b`. Run `configure-job --inputs <job-only-config>`.
   This explicitly revises workload inputs (and allows only the initial binding freeze), archives the previous receipt,
   preserves all server/binding/key/password scope, and invalidates the old plan.
   A torn revision fails closed; restore both sealed files from its protected
   configuration archive, verify hashes, and replan. Plan/review/apply again.
8. The operator explicitly starts the exact manual bootstrap job and retains
   the fixed-output execution receipt. It imports the production journal ORM,
   installs the rows/guards/roles, and validates both runtime credentials.
   Then configure `operation:"check"` with reference keys `a,b,bindings`, replan,
   review and apply to withdraw the old bootstrap job identity/admin grant.
   Run the manual check only when requested; no schedule is created.

## Private composition handoff and remaining hosted gate

Give each private composition only its own versioned journal credential and
protected original binding. Construct `PostgresClockJournal` using that scoped
SQLAlchemy `postgresql+psycopg` engine, then supply it to the existing
`create_clock_lab_app` private factory. Never run `prepare_database` using a
runtime role. Do not route an ordinary customer/API request to a selected clock,
customer or date. The default/production entrypoint remains unchanged.

The journal uses durable PostgreSQL row locks and therefore supports two private
compositions and multiple processes without sharing their grants. Actual hosting
must still measure restart/high-water and pending recovery, physical billing
freshness/JWT/HMAC behavior, signed runtime setup/admission, exact trial end before/
after, cancellation without first charge, same-invoice failure/recovery and
duplicate recovery. Database/job provisioning cannot substitute for those
registered-runtime HTTPS measurements. Retain `hosted_qualified:false` until they
are accepted; public enrollment and production remain held by their current gates.

## Cost and source checks

2026-10-31 Azure retail assumption, Central US, 730 hours/month: B1ms
`$0.01921/hour` = **$14.02/month**; 32GiB at `$0.13/GiB/month` = **$4.16**;
private DNS zone about **$0.50/month**, plus queries. Fixed addition is about
**$18.68/month**; reserve **$20–30/month** including small job/log/query/storage
operations. Existing vault/PE, VNet, CA environment, registry and log workspace
are reused without new fixed instances. A ten-minute 0.5vCPU/1GiB manual job is
about `$0.009` before Consumption allowances. No HA/geo backup or auto-grow is
enabled; quota/actual regional allocation and actual hosted costs remain operator
checks. No retail or Azure API was called while authoring this module.

Source qualification: `tofu fmt -check -recursive`, mirrored-provider
`tofu init -backend=false -lockfile=readonly`, `tofu validate`, and six mocked
plans in `tests/wiring.tftest.hcl`. Run
`python -m pytest infra/enrollment/private-clock/tests/test_private_clock.py -q`
with PG16 tools on PATH; four checks use only an owned loopback cluster and fake
bindings/credentials. PostgreSQL absence is an error, never a silently skipped
authority test. No actual image, Azure, Clerk, Stripe or hosted journey claim.
