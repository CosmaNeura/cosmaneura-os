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

The next prepared backend, `standalone_clerk_synthetic`, uses the existing Clerk
verifier with an explicit reviewed issuer allowlist. It retains the independent
database, restricted local operations and synthetic-only data boundary. It does
not turn the offline test owner into a real person or enable models and vendors.
The ordinary audience policy requires an explicitly configured application
audience in actual session tokens. It need not equal the storage instance UUID:
the audience identifies the application recipient, while exact issuer,
organization and reviewed owner bindings restrict account access. Two runtimes
deliberately configured for the same identity contract can accept the same
bearer token; storage UUIDs do not imply independent bearer-token audiences.
The explicit `shared_staging` policy supports the existing development
identity schema with an exact development issuer, organization and authorized
parties and an empty audience. Neither policy falls back to the other. A named
JWT template alone is not enough: the current clients request ordinary sessions.
Production readiness requires the separately reviewed production identity path.
An existing application audience can therefore be reused without changing
global Clerk claims or introducing named JWT templates. Actual signed sessions
must still be qualified; a dashboard configuration review is not a login test.

The standalone web build also carries the exact reviewed organization from the
same identity input used by the native clients. Before loading work, it reads
the signed-in user's actual memberships and requires that practice to be active.
If another practice is selected, a single Continue button selects the verified
membership. A completed selection request alone does not unlock the workspace.
Token requests check the current user, session and practice before and after
renewal so an account switch cannot reuse an old workspace's token request.
This gate neither creates memberships nor changes Clerk configuration.

The account portal and its destination must use the same production application.
A production portal that returns to a development-configured web build requests
a second login and shows that development application's organizations. The own
web build uses its matching identity directly; do not use that old redirect as
proof of standalone account access or change shared portal settings to mask it.

Independent HTTPS hosting preparation belongs under `infra/standalone/`. Its
target is a dedicated CosmaBot host with its own processes, service identities,
data directories and loopback PostgreSQL. Public client configuration comes from
the existing identity generator so web, Apple and desktop claims/origins agree.
These are review-only inputs with startup held. Rendering them does not prove
host ownership, TLS operation, network egress restrictions, secret custody,
backup restoration or real account access, and does not provision any resource.
The old staging renderer is not a deployment dependency for this instance.

Complete account administration only after verifying the CosmaBot Clerk
application. Review John's exact issuer, subject and new Cosmas MD organization
membership, then reserve those claims in a fresh database and have the signed
owner complete setup. Preserve the fixture practice as fixture evidence rather
than renaming or remapping its owner. The remaining acceptance is real sign-in,
saved notes/draft recovery, correct availability in Connections, and a matching
signed mobile client against the independently hosted service. The qualified
Preview50 on the phone remains separate from these new standalone profiles.

The current standalone stage exposes saved notes and editable drafts. AI Send,
external connector operations and member management stay unavailable because
this runtime has no corresponding execution service. Connections retains the
compact vendor requirements directory. Do not replace the fuller Preview
experience with this preparation build before its service capabilities and
signed mobile workflows are ready.

Future historical access should use a separately verified, revocable read-only
Cosmaneura account link with source provenance and patient authorization. It
must not merge principals or silently equate patients by names. The earlier
isolated Core read-API preparation remains undeployed and is not required for
the fresh practice workflow.
