# One public identity for the operational workspace

The existing desktop identity JSON is now the shared public build input. Its
production Clerk public key, frontend/issuer, organization, audience and API
origin are validated by the same native validator already used by both release
composers. No service login or credential lookup occurs.

Prepare a new directory from explicit reviewed values:

```sh
node scripts/prepare-workspace-identity.mjs \
  --identity /absolute/path/desktop-identity.json \
  --web-origin https://workspace.example.invalid \
  --core-web-origin https://core.example.invalid \
  --capture-upload-origin https://uploads.example.invalid \
  --output /absolute/path/new-identity-inputs
```

The example origins are invented and cannot be used for a real release. Supply
the actual reviewed public values before building the release candidates.

Use `desktop-identity.json` and `apple-identity.json` with the existing native
composers' `--native-identity-config` argument. The three `*-build-env.json` files
contain the full operational feature profile for Vite; `web-build-arguments.json`
contains the seven public arguments accepted by Dockerfile.web. Feed these values
through the existing builders; JSON is not a shell file and must not be sourced.
The selected capture modes remain browser microphone for web/desktop and native
PCM for iPhone. Existing native custody, packaging and signing requirements apply.

`os.identity.tfvars.json` binds those same values to OS deployment. Its API origin
must match the origin derived from the actual environment. Its web origin must
match the existing environment/custom-domain rules. No deploy or native-enable
flag is emitted. Core/Scheduling service identity and provider grants remain
separate configuration work; these files do not authorize another service.

The identity receipt includes a deterministic SHA256 compatible with OpenTofu's
`sha256(jsonencode(workspace_operational_identity))`. Native release evidence must
bind that hash to the actual desktop and iPhone archives and their independent
acceptance reference. This preparer does not generate that evidence. It does not
claim an account is connected, a device is accepted, or a release is authorized.

The input must be one bounded regular JSON file with no duplicate or extra fields.
The output must be a new directory. Incomplete output retains `.incomplete` for
inspection; it must not be consumed as a finished build input set.

## Shared identity in synthetic staging

The owner selected shared Cosmaneura identity with separate product permissions
on September 27, 2026. Shared staging (`staging.cosmas.ai`) uses its own Clerk
instance, `clerk.staging.cosmas.ai`, with a `pk_live` key, on the API's
`CLERK_SESSION_POLICY=audience` with audience `cosmas-os-beta-api`.
`operational-staging-v1` accepts that key when the decoded host is
`clerk.staging.cosmas.ai`, the frontend origin is `https://clerk.staging.cosmas.ai`,
the audience is non-empty, and the build explicitly selects `synthetic` data.

The `shared_staging` policy stays the development-instance path
(`*.clerk.accounts.dev`, empty audience). `operational-staging-v1` still accepts
a matching `pk_test_` key for that frontend when the audience is the empty
string and the build selects `synthetic` data. That path selects the development
instance's default session contract: the signed JWT must omit `aud` entirely.
Null, empty and foreign audience claims are rejected; issuer, signature,
session, origin and organization checks remain. `operational-beta-v1` continues
to require a production key/frontend. This identity profile does not change the
feature profile, grant workspace access or enable Core capabilities.

The development-instance path emits public VM settings in
`os.runtime-identity.json`. It explicitly selects
`CLERK_SESSION_POLICY=shared_staging` with an empty `CLERK_AUDIENCE`; the API
refuses this policy outside synthetic staging with a development issuer. The
audience policy used by `staging.cosmas.ai` requires `cosmas-os-beta-api`.
The development path does not emit `os.identity.tfvars.json`, because the
existing Terraform environment accepts only production identity profiles. The
production profile's outputs remain unchanged. Preparing settings does not
apply them to a host.

CosmaBot still requires its configured organization, an active local external
identity binding and an active human principal in its own Box. Platform account
membership alone grants no CosmaBot permission. Shared staging credentials use
a frontend-specific native Keychain service, leaving prior credentials intact.
An existing desktop installation still refuses an unreviewed identity change;
the explicit account and saved-state transition must complete before rollout.
