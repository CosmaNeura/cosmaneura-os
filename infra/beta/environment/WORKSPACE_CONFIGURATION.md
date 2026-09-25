# Operational workspace deployment inputs

The existing API and worker now receive the current workspace feature settings
and versioned secret references through `modules/workspace-runtime`. The static
web Container App keeps its separate identity and receives none of these secrets.
All prior private-network, Box, identity, data, release and deployment guards
remain in force. Native authorized-data admission now has a separate explicit
operational identity/release profile; the legacy synthetic behavior is retained.

`workspace_hosted_enabled` remains the explicit foundation. Use
`workspace_features` for supported backend feature flags and
`workspace_public_configuration` for the reviewed Core/Scheduling origins, tenant
mapping, public OAuth client identifiers and supported capture/model settings.
The module rejects unknown flags, missing dependencies and public secret fields.
It derives each OAuth callback from the API origin and fixed product route, each
connection return from the web origin, and the Core managed identity from the
existing runtime identity. Core must independently authorize that identity and
scope; setting these values does not configure Core or Athena on its behalf.

`workspace_secret_references` maps supported environment names to an object with
`secret_name` and an immutable 32-hex `version`. References resolve only inside
this beta's dedicated Key Vault using the existing runtime identity. Populate
those versions through the separately authorized secret-provisioning process.
This module does not read secrets, accept plaintext values, create accounts or
grant reviewed connector/action authority. Key rotation is an explicit revision.

For managed messaging/fax/payment accounts, `workspace_managed_manifest` supplies
the manifest's `secret_name`, immutable `version` and exact-byte `sha256`. The API
receives the JSON as `MANAGED_SERVICES_CONFIG_JSON`, redacted by Settings, plus
the digest. Keep it within Key Vault's 25 KB limit. Referenced account/API/SAS
secrets use the `COSMAS_MANAGED_SECRET_<NAME>` namespace. The JSON schema and
account/credential/action boundaries are documented in the API's managed-services
guide. The local mounted-file form remains supported separately.

Vendor/payment work, I/O and callback flags remain independent; configuration
does not enable them automatically. Stripe production is still refused by the
current application catalog. Portal setup/work flags can expose the existing
workflow, but a named portal provider still needs its separately supported host
configuration. No generic portal I/O enablement is offered by this module.
Athena exposes only the existing Core read-only connection and reviewed visit
links; there is no Athena write flag or write credential input.

Database-preparation attestations now require the current API's exact
`c83a2f19b650` revision from `release-schema.json`; older release schema
attestations remain invalid. The
manual preparation job must run the same immutable current API image and retain
its existing exact Box/server/execution evidence. No database command runs during
configuration or local module tests.

The pure module tests use only OpenTofu's built-in local resource and invented
values; no Azure provider, backend or credentials are involved. These tests cover
configuration construction and refusals. They do not establish cloud deployment,
Key Vault access, provider acceptance, physical-device behavior or signed release.

## Operational native identity

`workspace_operational_identity` accepts the existing public desktop identity
schema: version 1, profile `operational-beta-v1`, client `desktop`, API origin,
production Clerk public key/frontend, organization and audience. The value must
agree with this environment's derived API origin, Clerk issuer, fixed JWKS URL,
organization and audience. The key's encoded host must match that frontend.
The same identity is used to prepare the iPhone and web build inputs through
the client repository's `scripts/prepare-workspace-identity.mjs` command.

The existing native switches still control exact `app://cosmas` and
`capacitor://localhost` origins for CORS and Clerk authorized parties. In
`authorized_beta`, enabling either switch additionally requires
`workspace_native_release`: the exact public `identity_sha256`, distinct
`desktop_archive_sha256` and `iphone_archive_sha256`, and a human-controlled
`acceptance_reference` for those signed/qualified clients. The ordinary build
preparer does not populate this field. A supplied reference is configuration,
not cryptographic proof of signing or device acceptance; the owning release
review must verify the actual evidence before deployment.

API and worker resources explicitly depend on the workspace profile guard, so
native admission cannot race ahead while a derived identity check is unresolved.
No public key or release reference is put into the API runtime environment.
The existing clinic/BAA/data approval, private registry, schema, deployment and
provider requirements still apply. Synthetic configuration checks cannot satisfy
those real release prerequisites.
