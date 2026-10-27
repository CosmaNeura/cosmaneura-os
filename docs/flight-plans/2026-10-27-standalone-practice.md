# CosmaBot owns its practice independently of Core

Owner direction: start a fresh synthetic Cosmas MD practice for CosmaBot without
changing or deploying the separate Cosmaneura platform. Existing users should
eventually be able to link their Cosmaneura dashboard account and read historical
patient transcripts and summaries in CosmaBot. That history connector is later
work; it must not become a prerequisite for CosmaBot's login or local records.

CosmaBot already owns Box identity, reviewed owner setup, memberships, local
appointments, private notebooks and drafts. Use those services in a dedicated
database instead of cloning the full Core runtime, its startup migrations,
workers, billing configuration and callbacks. Preserve existing Core integrations
as optional code, disabled in the standalone configuration.

The new `standalone-practice-v1` client feature profile composes web, Apple and
desktop clients with verified identity, Messages and independent connector UI.
Core, capture and Session Prep gates are off; Core and upload origins are empty.
Client capabilities do not activate provider accounts or backend permissions.
Existing operational and first-owner profiles keep their previous behavior.

The separate `standalone_synthetic` backend mode is a local proof environment.
It requires its own UUID namespace, marked PostgreSQL database, restricted API
role, private local storage and fixed public keys for an invented signed test
identity. It starts no connector lifespans or background workers. Only the
bounded local setup and notebook mutation surfaces are admitted. Legacy data
entry, retention, administration, queue dispatch and provider mutations fail
closed. A process sandbox additionally restricts outbound access to the owned
PostgreSQL port and file writes to the owned runtime directory.

Fresh practice setup has two phases:

1. A reviewed host-only manifest reserves the exact issuer, subject, organization
   and new Box in an empty, migrated and explicitly marked database. This grants
   no principal or login access.
2. The signed owner completes the existing practice setup UI. The host-only seed
   then adds the manifest's bounded invented patients and appointments. Repeating
   the exact manifest is idempotent; changed manifests, existing practices,
   revoked identities and modified seeded records are rejected.

The CLI is `bootstrap-standalone-synthetic-practice`, with `--phase reserve` or
`--phase seed` and `--confirm-reviewed-synthetic-only`. It accepts only a bounded
private manifest outside the repository. The committed fixture is an example
of the schema, not deployment authority or an account binding for a real person.

Qualification must cover signed first-owner setup through the renderer and real
local API, local appointment selection, notebook/draft persistence, exact replay,
wrong issuer/subject/organization/audience rejection, and refusal of Core or
external dispatch. Keep older hosted and native configuration regressions.
Record test credentials outside the repository; never expose keys or bearer
tokens in logs. Physical Preview50 testing is separate evidence because that
installed build does not contain this standalone implementation.

Live deployment still needs a separately owned CosmaBot hosting configuration,
HTTPS endpoints, production identity verification, backup/restore qualification
and the corresponding signed client build. The offline test issuer cannot be
used as a production login. A real owner must complete verified membership;
email addresses or matching practice names never establish account equivalence.
No main-platform data, identities or secrets are copied by this change.

Future historical access should use a separately verified, revocable read-only
Cosmaneura account link with source provenance and patient authorization. It
must not merge principals or silently equate patients by names. The earlier
isolated Core read-API preparation remains undeployed and is not required for
the fresh practice workflow.
