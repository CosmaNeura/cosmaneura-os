# Independent Cosmas enrollment API

This module owns signup progress, practice registry, authorized human enrollment,
immutable BAA execution, the Cosmas SaaS subscription and its signed event inbox.
It contains no patient records and imports no clinical database/model/config.

Run the API with `uvicorn cosmas_os.enrollment.api:app`; use its own database and
the `ENROLLMENT_` settings defined in `config.py`. All external/qualification
flags default off. `/health` reports the process; `/ready` reports actual signup
readiness separately from verified billing and activation. Configuration errors
keep `/config.enabled` false and authenticated signup returns an actionable 503.

Apply `python -m cosmas_os.enrollment.migration upgrade` to an independent empty
PostgreSQL database, then run `check`. The additive migration refuses a database
with clinical tables. BAA receipts have database-enforced update/delete guards.
Readiness checks every expected table/column, not only a version row. An older
pre-release schema needs an explicit additive migration; upgrade never silently
marks its missing fields ready or deletes its receipts.
Do not downgrade/delete the registry or legal receipts to recover application
code. Retain original identity, workspace mapping, provider attempt and trial
clock. Roll application images forward/back while preserving this schema.

The Clerk contract is a default session: RS256, pinned issuer, exact authorized
app origin, exp/iat/nbf/sub/sid and no `aud` claim. Named JWT templates omit sid
and cannot establish this session. The adapter verifies live session status and
user ID, then reads the user's verified primary email from trusted Clerk API
evidence. Organization/email-domain claims never grant registry ownership.
Enrollment uses a separate Clerk key/issuer policy and changes no shared Core
claims. Google, Microsoft and password methods must be verified by the operator;
the enum in public config alone proves no OAuth journey.

The approved self-serve offer is $300 for the first human plus $100/additional
human monthly, 1–10 humans. Every owner/admin/staff is a human seat. The initial
selected number purchases that many human seats; pending invitations reserve
one, and a paused member retains one until removal. Agents cannot use these
human enrollment APIs. Seat growth above the purchased number, mid-cycle seat
changes, removal/repricing and 11+ negotiated quotes stay unavailable until an
explicit commercial/control implementation exists. The API never clamps an
11-human practice to the ten-human price. Tax, notification and cancellation
terms must be approved before `COMMERCIAL_TERMS_VERIFIED` enables billing.
The current Checkout explicitly adds no tax, discounts, fees or add-ons.

The two fixed recurring Stripe prices are independently verified: $300 × 1 and
$100 × (humans − 1), USD monthly licensed/per-unit, with an exact 14-day trial
and payment-method collection always. Root deployment operators must create
Cosmas-specific products/prices and a pinned portal configuration; the adapter
performs no account/catalog mutation. The portal allows payment methods/invoices
and cancellation at period end; plan/customer edits are disabled. Verify in a
real Stripe test clock that trial cancellation prevents the first charge and
that configured reminders are delivered. Mocked transports do not prove this.

Checkout starts only after the private provisioner records a qualified ready
workspace. The browser cannot mark a workspace ready. Root's provisioner owns
Clerk Organization creation, owner membership, independent Box/data store setup,
runtime owner reservation/completion and readiness evidence; it calls only
`EnrollmentService.record_workspace(practice_id, box_id=..., organization_id=...,
url=..., proof_sha256=..., status=...)`. Box and Org bindings are permanent and
unique. URL origin must be explicitly approved. A ready Box is insufficient:
the status returns its destination only for current human membership, exact BAA,
and recently authoritative trial/paid entitlement. The frontend activates the
returned Clerk Organization; the selected runtime must independently reverify
session and local membership. Enrollment does not bypass that runtime gate.

Checkout freezes the exact request before calling Stripe. Repeated keys with
different payloads fail; lost responses reuse the same provider attempt. The
server confirms open/completed/expired state rather than trusting redirects.
An unknown result older than 23h55 requires operator reconciliation and cannot
silently create another subscription. No automatic second trial is granted.
Operators must inspect Stripe's session/subscription inventory before resolving
that state; a production reconciliation command for that decision is not yet
exposed. A provider-confirmed expired session without a subscription can rotate.

Stripe webhook URL is `/enrollment/v1/webhooks/stripe`. Signature, five-minute
window, account/mode/API version and event identity are verified; a minimal
inbox row commits before 200. Run `python -m cosmas_os.enrollment.reconcile` from
the private scheduler every minute. Worker outages leave durable retry state.
Only fresh provider reads grant entitlement; signed failures can revoke pending
verification. Event IDs deduplicate and older events cannot regress state.
Every saved subscription update/deletion invalidates cached billing evidence
before acknowledgement, including delayed events. Admission then reads the
canonical subscription; provider outage cannot grant access from the old cache.

Synthetic qualification: `python -m cosmas_os.enrollment.synthetic --port 8041`
binds only loopback and uses its own in-memory synthetic registry, signed RSA
fixture sessions and fake provider. `/lab/session`, `/lab/qualify`,
`/lab/checkout/complete`, `/lab/checkout/expire` and `/lab/reset` exist only there.
Production API contains none of those routes and rejects injected fake adapters.
Run focused tests with `pytest tests/enrollment`; run the real PostgreSQL lock/
constraint rehearsal with `python tests/enrollment/run_postgres.py`.

Production qualification remains explicit and false by default. Real OAuth,
password recovery, Stripe test-clock cancellation/reminders, provisioner/Org
work, tax/export/retention terms and actual production acceptance remain operator
milestones. Passing local mocked tests does not label those integrations ready.

The sweep also refreshes bound subscriptions without relying on incoming events.
Ordinary active human status polling may refresh stale provider evidence, including
staff without billing authority. Signed payment failure binds the exact failed
invoice; subscription state alone cannot undo that hold. Recovery requires the
same authoritative invoice to be paid. Exact trial/paid period expiry fails
closed without an implicit grace period or a renewed free trial.

Provisioned staff require their own runtime/Clerk synchronization proof.
Root reads `pending_human_memberships(practice_id)` and records
`record_membership_ready(practice_id, issuer=..., subject=..., organization_id=...,
proof_sha256=...)` after verification. Until then the member sees finishing setup
with no workspace destination. GET `/practices` and POST `/select-practice` choose
only current authorized memberships; switching never merges practices.

The signed POST `/workspace/confirm` receives only `expected_revision` and a
fresh `workspace_token`, plus the ordinary enrollment bearer and idempotency
header. The token remains in memory; commands retain its SHA-256. Root's real
`provisioning.create_workspace_confirmer(settings, service)` factory must return
a `ProductionWorkspaceConfirmer`. Its frozen request contains only the stored
Box/Org, API/app origins, release commit/image and active registry human scope.
The callback prepares only that authorized Clerk membership and measures the
matching signed runtime; it never writes registry readiness. No selected Org
returns `WorkspaceConfirmationResult(None)`, asking the browser to refresh its
memberships, activate the saved Org and reconfirm with a fresh token/new key.
A measured SHA-256 proof commits only if the member remains active and its role,
practice, destination and release binding still match. Staff cannot qualify the
owner's unfinished workspace. Missing real callback disables activation config.
The synthetic `/lab/session` accepts optional `organization_id` solely for this
two-stage fixture proof. No synthetic proof is production qualification.

Managed runtime admission is opt-in with `WORKSPACE_ENROLLMENT_MANAGED=true`.
The Box receives immutable practice/Box/Org/issuer settings, exact owned control
and account origins, and `WORKSPACE_ENROLLMENT_ADMISSION_SECRET`, a per-Box key
derived with `derive_runtime_admission_key`. Only enrollment holds the master
`ENROLLMENT_RUNTIME_ADMISSION_SECRET` and Clerk backend key. No Box receives either
global secret. `CLERK_SESSION_POLICY=enrollment_default` requires managed admission
and an explicitly empty audience; old audience/shared-staging profiles retain
their policy. Managed native sessions without separately qualified origin proof
remain unavailable.

The owned HTTPS `/enrollment/v1/runtime/admission` authenticates request and
response with scoped HMAC, nonce, immutable scope, token hash and a 30-second
bound. Normal signed human requests additionally verify live Clerk session,
verified user and exact current Org membership. Registry human/BAA/seat/billing
checks apply on every identity and mutation fence, without a runtime cache.
Default-session JWT verification in the Box never needs a Clerk backend key.
Fixed denial headers distinguish `workspace_enrollment_access_required` (403)
from `workspace_enrollment_admission_unavailable` (503). GET `/account/identity`
is a protected recovery probe; public no-store `/config` returns only the pinned
account recovery URL and managed flag. Local invite/approve/bind/reactivate and
owner-change HTTP paths are unavailable on managed Boxes; paid roster reads stay
available.

Qualification is a bounded pre-billing exception for the exact registered owner
after signed BAA. Reserved-owner setup must complete before actual qualification
reports `initial_setup_complete=true`. The public enforcement marker has exactly
four keys: contract_version/enforced/practice_id/purpose. Invited staff/admin can
receive a non-owner local human binding only from paid, active capped registry
authority and fresh signed qualification. This grants no patient/resource scope,
never repairs revoked local bindings, and still requires the private verified
membership-ready transition before normal workspace access.

Queued Chief/private-handoff work checks retained immutable local human lineage
before dispatch, each tool execution and result publication. The scoped worker
purpose carries operation/revision hashes rather than a persisted bearer. Central
live Clerk user/Org membership, registry and billing checks remain mandatory;
logout alone does not revoke retained approved work. Routines and the legacy
operation worker also require retained human authority; missing lineage denies
managed execution. Denied model output is withheld while immutable observed usage
and a failed authority outcome remain durable. No service admission grants human
approval or external action authority.
