# Managed delivery and finance service configuration

Container deployments can supply the exact manifest bytes through the protected
`MANAGED_SERVICES_CONFIG_JSON` environment secret instead of a mounted file.
`MANAGED_SERVICES_CONFIG_SHA256` is required in both forms; supplying both JSON
and a path is refused. The JSON field is redacted in Settings representations.
The Azure deployment module binds it to an immutable secret version in the same
dedicated Key Vault, avoiding dependence on the platform's secret-volume symlinks.
Keep a Key Vault manifest within the provider's 25 KB secret limit; the local file
form retains its 256 KiB bound. Empty JSON leaves the existing file/default mode.

The ordinary `uvicorn cosmas_os.api.app:app` entry point can now read a
deployment-owned account manifest. Set `MANAGED_SERVICES_CONFIG_PATH` to its
absolute canonical mounted path and `MANAGED_SERVICES_CONFIG_SHA256` to the hash
of its exact bytes. Mount the file read-only. The path cannot be a symlink; the
document is limited to 256 KiB and duplicate/unknown keys are rejected. The
manifest's Box must match `BETA_BOX_ID`. See `managed-services-config.example.json`
for invented structure; its zero credential hashes are intentional placeholders.

The manifest supplies delivery accounts (Spruce, SRFax, Documo, eFax Corporate), Stripe sandbox
accounts, optional exact account-version callback routes and optional private
document storage. Production Stripe remains unavailable in the existing catalog.
Portal contracts are configured separately. These are the existing installed
accounts; no new connector implementation is loaded from a path or package name.

Each optional credential reference contains a dedicated
`COSMAS_MANAGED_SECRET_<NAME>` environment variable name and the SHA256 of the
expected secret bytes. Populate those environment variables through the host's
secret manager; never put values in this JSON, client bundles, logs or source.
The installation's credential reference and configuration digest must be the
reviewed values used by that account version. A changed secret is refused until
the manifest's expected hash is deliberately updated. A changed account identity
or configuration still requires the existing account-review flow.

API credentials are read afresh only when the existing executor presents the
complete exact active-account selection. The installation ID itself cannot stand
in for the separate reviewed active account-version ID. Missing or changed values
fail without exposing their contents. Omitting a credential leaves that account
available for setup only. Callback signing secrets are snapshotted at startup
only for explicitly configured routes bound to a matching active account version.
After account activation, add its full selection and route ID, update the manifest
hash and restart. A callback still only records a signed candidate or untrusted
fax hint; it does not authorize submission or automatically read provider data.

Optional artifact custody reuses `AzureVendorArtifactStore` and its bounded
transport. Its account and private container must match the workspace's configured
Azure store. Supply an unexpired, HTTPS-only container SAS with read and create/
write permissions; list/delete permissions are refused. The selected SAS is
re-read and checked for each operation. Each operation creates and closes its own
bounded container client, observes the caller and credential deadline, and retains
the existing exact Box/document commitments and exclusive-publication behavior.
No container is provisioned by this configuration path.

Loading creates no database rows, calls no vendor/Azure service, reads no API or
artifact credential, and enables none of the independent setup, work, I/O or event
flags. The hosted profile's existing identity/data/deployment checks still apply.
Malformed or conflicting configuration fails startup. Each application restart
loads the pinned manifest anew. Changes to a file without a matching hash do not
silently replace the installed runtime. Deferred device/service/deployment
acceptance still has to be completed before provider operation.

Explicit host composition remains supported when no manifest settings are
supplied. Supplying both forms is rejected instead of merging account authority.

The ordinary API lifespan accepts an explicit host profile for existing managed
Spruce, SRFax, Documo, eFax Corporate and Stripe application flows. Install it once, before the
first startup, using `configure_managed_services(app, ManagedServiceProfile(...))`.
The profile supplies delivery/finance installation catalogs, an optional private
artifact store and an asynchronous credential provider. Omitting credentials
allows reviewed setup without execution. Omitting the profile retains empty
catalogs and unavailable execution. Startup performs no credential lookup,
database mutation, account activation or vendor request.

The authenticated local workspace gate is still required. Setup, work, I/O and
event flags retain their independent meanings. This composition does not enable
hosted deployment, production Stripe, native identity or real account onboarding.
An installed account is configuration; the existing application must separately
record the owner-reviewed account and recipient/customer versions, exact action
approval and durable once-ever submission claim. Renderer input cannot select a
secret, transport, origin or installation catalog.

The provider receives a validated `ConnectionSelection` and must return a typed
`Credential` with its exact selection commitment, credential reference and secret.
The selected active account version must match exactly one configured installation
and cannot reuse the installation's identifier. Existing execution verifies the
current database account, recipient/customer, source, approval and request identity.
Credentials are freshly requested for each operation and are not stored or cached
by this composition. Gate changes during asynchronous identity or credential
checks invalidate dispatch. Provider failures are reduced to a closed public
error, without exposing the provider exception or credential.

Ordinary transport retains fixed HTTPS vendor endpoints, bounded exchanges and
the existing no-retry submission behavior. An optional host-only transport factory
supports explicitly scoped embedding or injected qualification. The host owns the
artifact store and its private storage lifecycle. Runtime shutdown clears the
installed request ports and blocks fresh credentials/dispatch; durable uncertain
outcomes and private late observations remain available to existing recovery.

This profile does not register webhook routes or portal transports. Those require
their own explicit service configuration and current authority. Account review,
local activation and action submission remain separate user decisions.

## eFax Corporate outbound adapter

eFax requires a Corporate or Enterprise account with access to its Fax Services
API; an ordinary eFax subscription does not establish API access. Configure an
installation with vendor `efax`, environment `production`, capability `efax_fax`,
the provider's API `user-id` as `remote_account_id`, and a reviewed North American
`caller_id` consisting of ten digits. The transport uses only
`https://api.securedocex.com`; it does not accept a renderer-supplied origin or an
unverified sandbox endpoint. These installation values contain no credential.

The credential provider must supply a **current bearer token**, bound to that
exact account selection. An eFax API key is not a bearer token. The official
documentation describes 24-hour tokens and says requesting a new token expires
the previous one. CosmaBot therefore does not mint or rotate a shared token per
fax. The host must coordinate token renewal and update its protected credential
binding through the existing managed-secret process. Automatic token lifecycle
and self-service account provisioning are not part of this adapter.

The adapter submits one reviewed PDF to one reviewed destination through the
existing account, recipient, document and action approval workflow. It records a
successful submission as **accepted**, then checks the returned fax identifier's
metadata for delivery. Image storage is not delivery proof. A completed
transmission requires the matching outbound fax and destination, a positive page
count, a completion timestamp and no reported transmission error. An uncertain
submission is not automatically sent again; its durable submission claim remains
in place. Both documented legacy retry counts are set to zero in the request.

The outbound adapter covers submission and delivery status. The separate inbound
path is described below. Neither path registers callbacks, cancels or deletes
transmissions, or creates provider accounts. Local tests use invented documents and mocked API responses;
they do not establish live credential validity or successful provider delivery.
Before enabling a real account, qualify token renewal, caller ID, recipient
format and a reviewed test transmission with that account. Nothing in this
configuration activates vendor I/O or deploys a release.

The official protocol references and interpretation are recorded in
[`validation/efax-api-reference.json`](validation/efax-api-reference.json).

## Received eFax and reviewed encounter passages

Inbound metadata, image acquisition and encounter-source sharing have separate
controls. Both `EFAX_INBOUND_ENABLED` and `EFAX_INBOUND_SOURCE_ENABLED` default to
false. The source path also requires the authenticated workspace with Clerk JWT
identity. The full operational client profile includes
`VITE_EFAX_INBOUND_ENABLED` and `VITE_EFAX_INBOUND_SOURCE_ENABLED`; the restricted
first-owner staging profile keeps them false. A client build flag does not
authorize provider access or replace a reviewed account grant.

The managed manifest has an optional `efax_inbound` array. Each entry supplies an
exact `ConnectionSelection`, a label, explicit `metadata_enabled` and
`image_enabled` booleans, and an optional protected credential reference. The
selection identifies the reviewed inbound account version; it is not inferred
from an outbound installation. Manifest loading creates no grant and makes no
provider request. The owner must review the installed account and independently
grant metadata access and, if desired, image access in the application.

Metadata reads cover one bounded page of at most 25 faxes within a maximum
seven-day interval. The transport accepts only the fixed
`https://api.securedocex.com` origin and refuses redirects. Opening a provider
image marks the fax downloaded/read at eFax. It therefore requires explicit
human approval of the exact image command through F-8. The application commits
its immutable once-ever claim before the image GET. An unknown result retains
that claim; recovery reads local custody and never automatically repeats the
provider request.

The server inspects received PDFs in a separate process: at most 1 MiB and 50
pages, five seconds elapsed, three seconds CPU and a 256 MiB memory bound. It
rejects encrypted documents, embedded files, forms, scripts and external actions.
The pinned optional dependency is `pypdf==6.19.0`. For a local runtime, install the
`efax-inbound` extra from the reviewed lock. The API image includes this extra;
an absent parser or unsupported resource fence leaves image acquisition
unavailable. This inspection supplies a page count, not OCR or a transcription.

After acquisition, a human chooses the confirmed encounter, reviews the exact
document and explicitly enters a passage with selected page numbers. Sharing
requires four acknowledgements covering patient, document, exact text and the
untrusted source. The resulting source is bounded to 12,000 characters and
records the original document, receipt, selection and content hashes. It does
not overwrite an existing clinical note or imply whole-document coverage.
Chief and specialist tools can read only that currently authorized exact source.
Revocation, changed account authority or a superseded selection withholds it and
its derived drafts from current views; historical receipts do not grant access.

The source-review and handoff-review interfaces store pending commands in the
existing encrypted private draft journal before dispatch. After a lost response,
the user can restore the command, check its saved status and explicitly retry
the same command and key. A retry does not reacquire the provider image or create
a second review. Refresh, restart, grant changes and human acceptance must be
qualified against the exact release before real use.

Synthetic signed API and mounted-interface checks exercise these paths with
invented accounts, documents, model responses and provider transports. Real API
entitlement, coordinated bearer-token renewal, controlled delivery/receipt and
the matching native installation remain separate acceptance requirements.
