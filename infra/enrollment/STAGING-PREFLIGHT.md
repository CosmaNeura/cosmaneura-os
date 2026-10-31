# Synthetic Development intake preflight

The first practice must be saved before the protected provisioner/private clock
composition can bind its owner, BAA, Box and Clerk Org. A complete journey cannot
therefore be a prerequisite for that first intake. The renderer accepts a
distinct `enrollment-staging-intake-preflight.v1` operator attestation only for
`https://onboarding.staging.cosmas.ai` and
`https://enrollment-api.staging.cosmas.ai`, with synthetic data and a matching
Development Clerk instance. `stripe_acquisition_enabled`,
`activation_available` and `production_qualified` must all remain false.
The existing full journey gates for acquisition/activation and all production
paths remain unchanged. The receipt grants no workspace entitlement, billing
permission, provider authority or deployment by itself.

There is no default trusted key or preflight proof in the repository. The
deployment operator maintains a separate Ed25519 signing key and independently
trusted public key outside the checkout. Both are regular owner-owned 0600 PEM
files in owner-owned 0700 directories, with no symlink path. The untrusted
manifest cannot name a trust key. The renderer receives the pinned public-key
path as its separate `--preflight-trust` operator argument. Protect that operator
configuration together with deployment authority; never accept the key from a
customer or a caller-supplied manifest.

## Actual evidence before signing

Deploy the source-bound closed central images first, using the real owned
foundation and restricted enrollment runtime database credentials. Retain the
actual database job execution metadata and its
`enrollment-database-check.v2` receipt. Run the existing
[HTTPS host verifier](STAGING-HOSTING.md) against the fixed custom domains and
retain its `enrollment-staging-hosts` JSON. It must show the selected account
source, real TLS/routes and the central database operational, while enrollment,
activation and journey/production qualification remain false.

Review actual Development Clerk Frontend API environment and Backend API
instance metadata for the issuer, matching test publishable key, exact account
party, invite-only policy and configured/enabled password, Google and Microsoft
methods. Retain sanitized structured configuration evidence. These are method
configuration checks, not completed end-to-end sign-ins: the account UI becomes
available only after this intake preflight. Perform actual password and OAuth
sign-ins afterward as part of the full journey. Do not store credentials, JWTs, personal customer
information or vendor secret values in these artifacts. Operator attestation
requires actual retained evidence; a synthetic test, a mock plan, a successful
health probe alone or an arbitrary hash is insufficient.

Prepare a protected draft payload with exactly these fields:

| Field | Required binding |
| --- | --- |
| `contract_version`, `purpose`, `environment`, `synthetic_only` | `enrollment-staging-intake-preflight.v1`, `development-intake-only`, `staging`, `true` |
| `source_commit`, `image` | Exact reviewed 40-hex source and immutable API image digest from its owned staging ACR; review actual execution/deployment metadata against these values |
| `app_origin`, `api_origin` | The two fixed separate HTTPS origins above |
| `issued_at`, `expires_at` | Physical Unix seconds; already issued, not expired, maximum 24-hour lifetime |
| `database` | Owned subscription/tenant UUIDs, staging resource group, Central US or East US 2 location, matching ACR/vault/PostgreSQL names, `cosmabot_enrollment` / `enrollment_runtime`, exact versioned runtime DB secret reference, execution evidence SHA-256 and actual `check` JSON |
| `hosting` | Exact closed-host verifier JSON, including matching source, five account routes, TLS and operational database checks |
| `clerk` | Exact `.clerk.accounts.dev` issuer and matching `pk_test_` key, `authorized_parties: [app_origin]`, `invite_only: true`, `configuration` projection derived below, `policy_evidence_sha256` for the actual successful FAPI environment file, `instance_evidence_sha256` for the actual BAPI instance file, `identity_binding` / `identity_evidence_sha256` as described below, and `methods` containing exactly `password`, `google`, `microsoft`, each `{configured: true, evidence_sha256: "<same actual FAPI file SHA-256>"}` |

The database binding uses the existing foundation names for one shared suffix:
`rg-cosmabot-enrollment-staging-<suffix>`,
`acrcbotenrstg<suffix>.azurecr.io`,
`https://kv-cbot-enr-stg-<suffix>.vault.azure.net/` and
`psql-cosmabot-enrollment-staging-<suffix>.postgres.database.azure.com`.
Its runtime reference is the exact version of `enrollment-database-url` in that
vault. Every selected application secret reference must belong to the same
owned vault. The database check must confirm the current
`enrollment_20261031_v1` schema, restricted runtime role, immutable receipts and
nine grant tables. The v2 receipt must additionally report
`managed_database_ownership_acl_checked: true`,
`provider_database_default_access_allowed: true` and
`provider_database_count: 2`. These checks recognize only the known provider
databases' owner/default ACL policy on the isolated owned PostgreSQL server;
they do not grant application roles, mutate provider databases, permit unknown
owners/ACLs or allow PUBLIC CREATE. Application database roles, TLS and table
limits remain exact. Legacy v1, missing/false checks and other counts are
rejected. Its existing connectivity/restore/journey qualification
fields remain false; the operator reviews actual execution and host evidence
separately and does not rewrite those fields to claim wider qualification.

The pure `clerkConfigurationFromReceipts(frontend, backend)` export derives
`configuration` from the retained metadata. The FAPI artifact must be the actual
successful environment GET (`http_status: 200`, `vendor_writes: false`), with
`settings.auth_config.object: "auth_config"`, `test_mode: true`,
`password: "required"` and all three first factors. It checks Development
`display_config`, required/enabled email and password attributes, verified-email
signup configuration, `user_settings.sign_up.mode: "restricted"`, and actual
`social.oauth_google` / `social.oauth_microsoft` enabled/authenticatable
strategies with selectable, nondeprecated configuration. The BAPI artifact must
be the actual `cosmabot.dev-clerk.instance-read.v1` inspection, with an
`instance` object, Development environment, real instance ID, and independently
checked matching test-key correspondence. Its original allowed-origins metadata
is retained as `null` or the exact account origin; `null` is not a provider
allowlist claim. The existing backend's exact authorized-party verification
still binds every actual JWT to the account origin.

This projection contains the actual instance/environment and method settings,
not an arbitrary sign-in success flag. It omits organization membership mode,
seat capacity and setup readiness: pending provider settings are not silently
qualified by method configuration. `clerk_methods_verified` is the existing
readiness flag used to expose the account UI for this configured-method
preflight; it does not assert completed end-to-end sign-ins.

Retain a separate actual public identity-binding artifact during the measured
requests. The earlier sanitized wrappers alone omit their request issuer/key
context; their matching-key Boolean cannot prevent transferring configured
metadata to another Development instance. Do not manufacture this binding from
the draft. It must record the actual request context, selected instance and
retained artifact bytes, with exactly:

```text
kind: "cosmabot.dev-clerk.identity-binding.v1"
observed_at: physical Unix seconds at the actual inspection
issuer: exact selected Development HTTPS issuer
publishable_key_sha256: SHA-256 of the full actual pk_test_ UTF-8 string
authorized_parties: ["https://onboarding.staging.cosmas.ai"]
instance_id: actual BAPI selected instance ID
frontend:
  url: issuer + "/v1/environment"
  http_status: 200
  environment_sha256: SHA-256 of exact retained environment artifact bytes
backend:
  url: "https://api.clerk.com/v1/instance"
  http_status: 200
  instance_sha256: SHA-256 of exact retained instance artifact bytes
```

`authorized_parties` records the independently checked current backend party
configuration, explicitly not a Clerk origin allowlist. The observation must
precede preflight issuance by no more than 24 hours. Copy this measured artifact
to `clerk.identity_binding` and set `identity_evidence_sha256` to its exact file
hash. Signer and renderer compare its issuer, key digest, instance, party,
request URLs and artifact hashes to the configured metadata and selected
intake. The signer also requires equality with the independently protected
retained artifact. Absent concrete request identity evidence fails closed.

Prepare a separate protected evidence-path JSON with exactly
`database_check`, `database_execution`, `hosting`, `clerk_environment` and
`clerk_instance`, plus `clerk_identity`, mapping to absolute protected artifact paths. Artifact
files and their immediate directories require the same owner-only custody as
the keys and must be outside the checkout. The signer parses the DB/host JSON
and requires exact equality with the payload, independently hashes the actual
execution, two provider metadata files and actual identity-binding file,
derives and validates the configuration projection, and requires equality with the draft before using
the operator key. Signing checks
structure, scope, freshness and retained bytes; it is an explicit operator
attestation after reviewing actual measurements, not a vendor measurement.

```sh
node infra/enrollment/staging-preflight.mjs \
  --input /protected/preflight-draft.json \
  --evidence /protected/evidence-paths.json \
  --private-key /protected/signing-key.pem \
  --output /protected/new-intake-receipt.json
```

This command creates no signing key or vendor measurement. It signs the
reviewed existing evidence and refuses to overwrite output. Add the resulting `{payload, signature}` object to
`qualification.staging_preflight` in the protected renderer manifest, retaining
the matching `qualification.source_commit`. Set only measured intake/auth
readiness as needed; acquisition and activation stay false. Then render with
the independently trusted public key:

```sh
node infra/enrollment/render.mjs \
  --input /protected/reviewed-intake-manifest.json \
  --output /protected/new-intake-render \
  --preflight-trust /trusted-operator/verification-key.pem
```

Verification rechecks the signature, physical freshness, exact source/image,
fixed hosts, Development key/issuer/party and owned versioned DB binding. The
protected deployment contract retains the signed receipt and computed digest;
the browser and public API configuration receive no signature, evidence or
trust-key path. Freshness is a rendering gate, not an ongoing auth lease. Close
intake and remeasure before changing source, images, DB credentials, host or
Development identity/policy; ordinary live Clerk verification and all runtime
authorization remain required.

## Intake to the full journey

The admitted account host now permits actual password and both OAuth end-to-end
tests. The invited synthetic owner signs in through real Development Clerk and saves
profile, practice and accepted BAA through the normal API. Prepare/bind its
private Org and isolated Box using the trusted provisioner. The explicit private
clock composition then requires that saved immutable scope, original-trial
checks and its separate durable PostgreSQL journal before admitting TEST
Checkout for the one owner. Its broader public acquisition remains false.

Complete and retain the actual two-practice owner-to-Chief acceptance journey.
Remove `qualification.staging_preflight` before rendering acquisition or
activation with the full staged `journey_sha256`. Never use this receipt on
production, enable acquisition from it, or replace the journey with manual
entitlement. The operator still deploys measured configurations separately;
the signer and renderer make no cloud calls.
