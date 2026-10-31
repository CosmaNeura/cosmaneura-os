# Two synthetic onboarding practice workspaces

This staging-only bridge deploys the two isolated Boxes needed for the real
account → legal practice → agreement → owner setup → trial → Chief rehearsal.
It calls `infra/beta/environment/modules/workspace-runtime` unchanged and reuses
the existing beta image, migration/grant contract, first-owner reservation,
Blob adapter, worker and signed enrollment admission. No existing beta resource,
central enrollment database table, Core service or production identity is changed.
Configuration preparation performs no cloud calls and proves no readiness.

## Resources and boundaries

Reuse only the new enrollment foundation's VNet, private subnets/DNS, Container
Apps environment and ACR. Each practice gets its **own** PostgreSQL 16 server
with a `cosmas_os` database, private Blob account/container, private Key Vault,
private Azure Managed Redis broker, API/worker identity and separate browser
identity. The enrollment registry remains on its own server/database.

The browser identity receives ACR pull only. API/worker receive their own Blob
container role and three exact per-secret grants: runtime DB, broker and derived
admission key. They receive no admin URL, reservation manifest, central admission
master, Clerk backend key, Stripe key or another Box's secret. Manual migration
and reservation jobs have distinct identities; reservation uses the Box admin
connection because the established runtime grants intentionally prohibit INSERT
on `practice_owner_reservations`. They receive no Blob or deployment role.

Sizing is deliberately bounded: two B1ms PostgreSQL servers (32 GiB each,
seven-day backups), two HA Azure Managed Redis `Balanced_B0` instances
(`NoCluster`, TLS, DB 0, `NoEviction`, AOF every second), four API/worker replicas
at 0.5 CPU/1 GiB and two static web replicas at 0.25 CPU/0.5 GiB, max one each.
The currently published Redis HA B0 example is about $26.28/month per broker;
the actual East US 2 quote, PostgreSQL, Container Apps, storage, Key Vault and
telemetry charges must be checked before apply. No legacy Azure Cache for Redis
resource is introduced. Availability/capacity remains an actual deployment gate.
[Managed Redis](https://learn.microsoft.com/azure/redis/overview),
[pricing](https://azure.microsoft.com/pricing/details/managed-redis/).

## Prepare the authoritative manifest

Use the real standalone enrollment API and an owned test login for each synthetic
practice. Save the full accepted BAA receipt first. The existing protected
provisioner creates/recovers the Clerk Org and stable Box; it starts no trial:

```sh
python -m cosmas_os.enrollment.provisioning prepare --practice-id <saved-practice-uuid> --api-origin https://api.<practice-slug>.staging.cosmas.ai --workspace-url https://<practice-slug>.staging.cosmas.ai/chief --source-commit <exact-api-source> --image-sha256 <api-image-digest> --output /protected/practice-a.plan.json
python -m cosmas_os.enrollment.provisioning prepare-admission-key --practice-id <same-saved-practice-uuid> --output /protected/practice-a.admission-key
```

Repeat for B using its own saved practice. Use the central enrollment environment
only for these commands; its credentials never enter a Box manifest. Each output
is protected. The derived key is practice/Box/Org-bound; do not copy A's key to B.

The version-1 input to `render.mjs` contains `environment: "staging"`,
`synthetic_only: true`, a fresh six-to-eight-character `namespace`, and a reviewed
public `release_operator_object_id` for the operator record, plus:

- `foundation`: the selected `enrollment-foundation.v1` public coordinates;
  retain only contract/environment, subscription/tenant/group/location,
  VNet/Container Apps environment/ACR IDs and registry server,
  `postgres_subnet_id`, `private_endpoint_subnet_id`, `vault_private_dns_zone_id`.
- `account`: the exact central `app_origin`, `api_origin`, selected development
  Clerk `issuer` and matching public `publishable_key`. This bridge requires
  `https://onboarding.staging.cosmas.ai` and
  `https://enrollment-api.staging.cosmas.ai`; older beta or account aliases are
  rejected, so recovery stays on the same enrollment Clerk instance.
- `release`: immutable `source_commit`, `api_image` and `job_image` in that ACR.
  Use `job_image: null` only during stores/build preparation. Build the job from
  that API digest with `Dockerfile.job`; measure its digest before creating jobs.
- Two `practices` entries, keys `a` and `b`: each exact saved `plan`, bounded
  `owner_display_name`, `practice_display_name`, `reviewed_by`, `evidence_ref`,
  its own immutable `web_image` (initially `null` until its public bundle is built), `secret_references` (initially empty),
  `migration_receipt_sha256: null`, `reservation_receipt_sha256: null`,
  `dns_ownership_qualified: false`.
- Explicit false gates: `create_migration_jobs`, `create_owner_reservation_jobs`,
  `deploy_workloads`, `bind_domains`.

```sh
node infra/enrollment/workspaces/render.mjs --input /protected/two-practices.json --output /protected/new-workspace-render
python infra/enrollment/workspaces/prepare.py prepare --directory /protected/new-workspace-credentials
```

Outputs include public per-Box web build environments, protected first-owner
manifests and `deployment.json`. The renderer verifies the provisioner's actual
UUID5 Box mapping, distinct practices/Orgs/paired origins and release identity.
All secrets are exact versioned references in `kv-cews-<namespace>-a|b`.
The web builds use the existing standalone synthetic feature profile, their
explicit Org and API, disabled Core/capture/provider/model integrations, and
the central account recovery route. These bundles do not offer a second signup.

Build each web bundle using its emitted `web-a|b.env.json`, then package its
`dist` with `Dockerfile.web` and `serve_web.py` into the selected ACR. Validate
the built version/commit and actual API/Org configuration before pinning the
web digest. The static host serves `/healthz` on 8080 and SPA routes; it has no
application secrets. Building/pushing images is separate operator work.
`build.mjs` prepares a fresh minimal context and, for A/B, runs the current web
build with the emitted public environment. It rejects local Vite overrides,
changed tracked source, a source SHA different from the selected API release,
or a built version/Org/API/profile mismatch. It performs no image build/push.
Run with Node 24 or newer from the integrated, clean exact release checkout.
The existing web TypeScript build also resolves the repository's shared capture
package types; install both locked public dependency sets, without lifecycle
scripts or network resolution. This does not enable a capture integration or
modify a native application:

```sh
COREPACK_ENABLE_NETWORK=0 corepack pnpm@9.15.9 --dir web install --offline --frozen-lockfile --ignore-scripts
COREPACK_ENABLE_NETWORK=0 corepack pnpm@9.15.9 --dir clients/capture install --offline --frozen-lockfile --ignore-scripts
```

Prepare only `Dockerfile` and `job.py` for the job;
`Dockerfile`, `serve_web.py`, a public receipt and built `dist/` for the web.
Pass the immutable API digest as `APP_IMAGE`. Do not use
the repository root context, whose application `.dockerignore` excludes this
new infrastructure directory, or copy a protected manifest into either context.

```sh
node infra/enrollment/workspaces/build.mjs --input /protected/two-practices.json --practice job --output /protected/new-job-context
node infra/enrollment/workspaces/build.mjs --input /protected/two-practices.json --practice a --output /protected/new-a-web-context
node infra/enrollment/workspaces/build.mjs --input /protected/two-practices.json --practice b --output /protected/new-b-web-context
```

Build/push these contexts into the **owned staging ACR** through the existing
operator image procedure, then record each measured digest. Fill the job digest
and both web digests in the protected manifest; placeholders never qualify a
job or workload.

## Apply in ordered stages

1. Initialize this root with a **new** protected backend key such as
   `cosmabot-enrollment/staging/workspaces-<namespace>.tfstate` in the foundation's
   Entra-only state container. Never reuse central runtime/database-job state.
   `prepare.py tofu` supplies generated passwords only through the child's
   ephemeral environment; state/plans are encrypted with the protected
   `encryption.passphrase`. Preserve this file and both admin passwords for
   recovery. Do not put variables or credentials on the command line.
2. Plan/apply with all gates false and
   `-var=deployment_file=/protected/new-workspace-render/deployment.json`.
   This creates only the new stores/network endpoints/identities. Record the
   measured resource IDs and actual private connectivity. Existing beta and
   central registry resources must have zero changes/deletes in the plan.
3. Obtain each broker's key directly into a protected 0600 file. Use `prepare.py
   urls --directory ... --namespace ... --practice a --redis-host <measured-host>
   --redis-key-file <protected-file>` for each Box; it writes separate admin,
   runtime and broker URLs using required verified TLS. Seed those URLs, the
   provisioner's derived key and the emitted exact `owner-a|b.json` through the
   operator-only `seed_secret.py` ARM secureString path. It never opens the vault
   publicly, prints a value or puts one in process arguments/receipts.
   This reuses the foundation's control-plane secret-seeding procedure under
   inherited deployment authority; it adds no vault-wide data-plane publisher.
4. Put the returned versions in each entry's `secret_references`:
   `DATABASE_URL`, `REDIS_URL`, `WORKSPACE_ENROLLMENT_ADMISSION_SECRET`,
   `DATABASE_ADMIN_URL`, `OWNER_MANIFEST`. Render a fresh output with only
   `create_migration_jobs: true`; apply, then start each manual job once.
   Require its exact current schema/non-admin/immutable-audit evidence and
   recorded Azure execution identity, then fill `migration_receipt_sha256`.
5. Render/apply with `create_owner_reservation_jobs: true`, still no workloads.
   Start each reservation job once. Require exact Box/Org/owner/release/manifest
   readback and `owner_ready: false`; save its receipt/hash. Consume the reserved
   owner setup within its existing seven-day expiration. Disable/remove the
   manual job resources and their secret-reader identities after recording
   evidence; preserve database credentials and legal/account records.
6. Only with both receipts recorded, render/apply `deploy_workloads: true`.
   Create/verify exact practice CNAMEs, domain ownership and Azure managed TLS
   for each API/web app using the existing beta custom-domain procedure. Domain
   bindings remain off until DNS ownership is qualified; `bind_domains: true` creates them, and
   HTTPS certificate issuance/binding must then be measured. No DNS is inferred
   from a slug or provider-generated FQDN.
   `workspace_resources` exposes the selected A/B API/web FQDNs. The separate
   sensitive `domain_verification` output preserves the existing protected
   handling of the app-specific `asuid` TXT values. Retrieve those only to a
   protected operator artifact for exact CNAME and TXT records. Follow the
   managed certificate sequence in `docs/beta/WEB_RELEASE.md`, applied only to
   these four new app IDs/hosts; do not run the old beta deployment package.
7. Through the real account UI, select each saved practice and confirm its
   scoped Clerk account. The existing confirmer consumes the actual owner
   reservation/setup and checks health, schema, membership, Box/Org/release and
   signed central admission. A deployment receipt never marks the registry ready.
   Before that proof, no workspace URL, Checkout, trial or clinical access.
8. Complete the hosted **Stripe TEST** Checkout only after usable readiness;
   verify exact 14-day dates, owner Chief and invited paid staff. Cross-practice
   sessions, wrong Org, revoked membership, absent BAA and canceled/unpaid
   subscription must remain denied on bookmarked API and queued worker paths.
   Recovery goes to the exact central account origin. Keep provider integrations
   dark and synthetic data only. Production remains a separate package/journey.

Example explicit operator commands (the implementation task runs none):

```sh
python infra/enrollment/workspaces/prepare.py tofu --directory /protected/new-workspace-credentials --tofu-argument=init --tofu-argument=-backend-config=/protected/workspace-backend.hcl
python infra/enrollment/workspaces/prepare.py tofu --directory /protected/new-workspace-credentials --tofu-argument=plan --tofu-argument=-var=deployment_file=/protected/new-workspace-render/deployment.json --tofu-argument=-out=/protected/workspace.tfplan
python infra/enrollment/workspaces/seed_secret.py --deployment /protected/new-workspace-render/deployment.json --practice a --secret-name enrollment-admission-key --value-file /protected/practice-a.admission-key --output /protected/new-a-key-reference.json
```

Focused offline checks use the exact cached provider with backend disabled and
mock Azure resources. Local checks prove wiring/refusals, not Azure creation,
Key Vault reachability, DNS/TLS or a real customer's owner/Chief journey.

```sh
node --test infra/enrollment/workspaces/render.test.mjs
node infra/enrollment/workspaces/fixtures.mjs
tofu -chdir=infra/enrollment/workspaces init -backend=false -lockfile=readonly
tofu -chdir=infra/enrollment/workspaces test
python -m pytest infra/enrollment/workspaces/test_bridge.py -q
ENROLLMENT_WORKSPACE_LOCAL_REHEARSAL=1 python -m pytest infra/enrollment/workspaces/test_bridge.py -q --basetemp=/private/tmp/new-owned-workspace-rehearsal
```

For mock plans, set `TF_VAR_encryption_key_file` to a disposable invented 0600
passphrase file outside the repository and use the exact cached provider mirror;
never load actual deployment credentials or backend state into these tests.
The opt-in rehearsal creates/stops only its two fresh loopback PostgreSQL 16
clusters. It executes the established migration/grant implementation, private
job reservation/readback and real signed runtime setup/qualification HTTP routes.
Provider identity and commerce remain explicitly synthetic. It checks that no
principal or trial exists after reservation, incomplete Checkout grants no
access, account bootstrap tokens grant no ordinary workspace access, fresh Box
tokens require entitlement, wrong humans and canceled status are held, and a
reconciliation must restore authoritative billing before access resumes. A real
loopback static response check preserves the existing browser security headers.
