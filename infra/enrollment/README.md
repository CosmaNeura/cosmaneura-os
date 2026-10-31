# Customer enrollment deployment preparation

This component serves customer account/practice setup, BAA receipts and SaaS
subscription state. It stores no clinical records and grants no access to the
clinical database, Blob storage, Core services or another product's credentials.
The owner approved building it on October 31; production follows the staged
customer journey.

`render.mjs` prepares exact source/image, owned app/API origins, Clerk identity,
public pricing settings and versioned Key Vault references. It accepts no secret
values. It refuses mismatched Clerk keys, cross-product origins, staging identity
in production, unknown secret names and trial activation without its underlying
registration/provisioning/billing admission. A rendered contract is marked
`deployed: false`; it is never evidence that the app or billing has been qualified.

```sh
node infra/enrollment/render.mjs --input /protected/reviewed-enrollment.json --output /protected/new-enrollment-output
node --test infra/enrollment/render.test.mjs
```

Use version 1 manifests with `environment` (`staging` or `production`), exact
40-hex `source_commit`, `image` (owned ACR repository plus SHA-256 digest),
`app_origin`, `api_origin`, and `workspace_origins`. Production signup is
`https://app.cosmas.ai/onboarding`; `/sign-in` is the returning-user entry.
Staging origins must be `staging.cosmas.ai` or its subdomains; production must
use the admitted CosmaBot app/API/Clerk hosts. Independent production workspace
origins may use `<practice-slug>.workspace.cosmas.ai`, paired with
`api.<practice-slug>.workspace.cosmas.ai`; the controlled cohort admits at most
20 exact workspace origins. DNS/TLS must be provisioned and qualified, rather
than inferred from the naming pattern. Enrollment routing is separate
from existing native and clinical API routing.

The `clerk` object contains `issuer`, its matching `publishable_key` and
`session_policy: "default_session"`. Staging also admits the selected matching
`*.clerk.accounts.dev` issuer. The selected instance must actually enable
Google, Microsoft and email/password. Default Clerk session tokens have no
audience claim; verification requires their session ID, exact issuer/authorized
app origin and a live active session with verified primary email. Custom token
templates and Core's sign-in settings are not changed. Rendering configuration
does not create or qualify that Clerk setup.

`stripe` contains only `account_id`, `base_price_id`, `additional_price_id` and
`portal_configuration_id`. The base is $300/month, additional humans are
$100/month, USD, one through ten; eleven or more is negotiated. Every human
role is paid. Base/extra line items preserve the reused Checkout API's trial
behavior. The backend verifies catalog, currency, intervals, modes, portal
configuration and resulting objects before it trusts billing.

`secret_references` is an environment-name map of exact versioned
`https://<owned-vault>.vault.azure.net/secrets/<name>/<32-hex-version>` references
for the independent database, Clerk backend key, stable invitation-signing key,
Stripe key and Stripe webhook secret. Keep references in protected deployment inputs; actual values remain
in Key Vault. Browser build output receives only enrollment enable/origin
settings; the browser obtains public Clerk/pricing/readiness from `/enrollment/v1/config`.

`readiness` contains explicit booleans corresponding to the backend admission
flags. All omitted flags are false. `qualification.source_commit` binds the
selected source; enabling registration/verified methods/acquisition also needs
the staged `journey_sha256`. Production registration additionally requires the
actual `production_sha256` and `production_qualified`. These are reviewed
receipt references, not new user approval prompts or a replacement for runtime
validation. Unusable workspaces never start a fourteen-day trial.

## Independent Azure foundation and runtime

Prepare a dedicated `rg-cosmabot-enrollment-staging-<id>` or
`rg-cosmabot-enrollment-production-<id>` foundation with its own remote state,
networked Container Apps environment, ACR, private PostgreSQL, private Key Vault
and telemetry. Reuse the already established Azure components and deploy
identity pattern; do not share Core or clinical workspace state. Provision the
central enrollment database and runtime role independently from per-Box data.

`runtime/main.tf` consumes those owned foundation resources and the rendered
directory. It rejects cross-resource-group vault/registry/environment inputs.
The enrollment identity can pull its ACR image and read only its dedicated
vault. It has no Blob, VM, deployment or workspace-administration role. Workload
creation defaults off until the independent database migration/role/isolation
check is recorded. Secrets enter the process through managed identity Key Vault
references rather than credential values in Terraform variables or browser code.

Run the dedicated migration from the reviewed application image using a
separate, protected migration database role:

```sh
python -m cosmas_os.enrollment.migration upgrade
python -m cosmas_os.enrollment.migration check
```

Use the backend's `ENROLLMENT_DATABASE_URL` for that process only; do not dump
its environment or reuse a clinical database. Runtime access must remain
non-admin. The migration checks that the target is not a clinical schema.
Record actual schema checks, restart/recovery and a tenant-specific restore
before setting `database_preparation_qualified`.

Initialize `runtime/` with its own protected Azure backend coordinates. Never
copy a clinical/D2/Core backend or state file. A `terraform validate` or plan
with workloads off is preparation, not production creation. The eventual
reviewed apply creates the separate identity/roles and enrollment app; it does
not replace the current clinical API or its web/native identities.

After runtime qualification, bind the reviewed app/API domains and TLS, then
enable the marketing site's `pending` or `ready` enrollment state appropriately.
Marketing D1 remains contact storage only. Keep the agreement/receipt,
subscription and enrollment registry durable across image rollback; preserve
pricing and original attempts, never restart customer trials on deployment.

## Trusted practice provisioning and account confirmation

`cosmas_os.enrollment.provisioning` runs with the independent registry and its
Clerk key. It has no clinical database or Azure workspace deployment credential.
The protected deployer creates each isolated Box with the existing CosmaBot
workspace deployment pattern; this bridge does not clone or deploy Core.

`prepare` recovers Clerk organization creation by a deterministic practice slug,
checks private practice/Box/issuer/owner metadata and the initial owner's actual
membership, then saves the immutable Box/Org binding and selected release. It
leaves the workspace provisioning and starts no subscription or trial:

```sh
python -m cosmas_os.enrollment.provisioning prepare --practice-id <registry-practice-uuid> --api-origin <paired-api-origin> --workspace-url <admitted-workspace-url> --source-commit <40-hex-workspace-commit> --image-sha256 <64-hex-workspace-image-digest> --output /protected/new-workspace-plan.json
```

Inject `WORKSPACE_RELEASE_SOURCE_COMMIT` and `WORKSPACE_RELEASE_IMAGE_SHA256`
into the independently deployed workspace from the same reviewed immutable
image/source manifest. Its additive signed
`/practice-access/enrollment-qualification` endpoint is unavailable when these
are empty. It returns the server's Box, Org, issuer, authenticated subject, role
and deployed release configuration only after existing runtime membership
checks. The enrollment bridge also measures `/health` and `/ready` and rejects
any mismatch. A selected operator plan is not measured runtime evidence; the
protected deployer must independently verify its actual Azure image digest.

Account confirmation synchronizes only an active registry-authorized Clerk
membership, then lets the human select the saved practice and obtain a fresh
scoped session. The signed enrollment confirmation route accepts that token;
it takes no caller-supplied destination, Box, role or ready flag. Verification
must pass the independent runtime's actual local human access checks. The
registry stores the proof hash, never the session token. Membership creation
alone does not grant local runtime authority or start a trial.

The private `prepare-memberships`/`qualify-member` commands remain available for
controlled cohort operations and recovery. Token files must be regular files
with mode 0600 and are never written to a receipt. Signed confirmation plus
qualified access is required for each staff member; an owner proof cannot
stand in for a staff member's access.
