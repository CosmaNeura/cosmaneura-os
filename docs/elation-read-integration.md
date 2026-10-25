# Elation appointment review and sandbox setup

Updated 2026-10-25: authenticated application routes, immutable read/review
records, shared selected-source custody and a managed sandbox installation path
are implemented. Staff can review an Elation appointment from Chief's Details
or a visit's Sources and prepare an editable Chief draft without losing existing
text. This milestone is **synthetic only and off by default**. The original
local-example runtime remains mock-only; the separate managed runtime accepts
private server-configured sandbox credentials. All qualification to date uses
invented responses. No vendor account was created or contacted, and production
and actual vendor acceptance remain unavailable.

## Implemented contract

`src/cosmas_os/adapters/elation_read.py` contains `ElationReadAdapter` and private,
immutable result types. It uses the repository's existing `httpx` dependency
(BSD-3-Clause), not an unverified vendor SDK. Elation's API remains subject to
its proprietary [API agreement](https://www.elationhealth.com/api-license-usage-agreement/).
No official reusable language SDK was verified.

The constructor takes an `ElationReadScope`, an async credential resolver and
an async `authorize_read(scope)` callback. `enabled` defaults to false. The
scope binds Box, owner, connection UUID, credential-generation UUID, selected
practice ID/name and `environment="sandbox"`. Production configuration is
rejected. The resolver must return `ElationCredentials` with this exact scope
commitment and private `SecretStr` client credentials. Changed credentials
require a new generation and adapter; cached authority cannot cross that change.

The integrated service supplies fresh actor, Box, account, installation and
generation checks before dispatch and after response. It rechecks authority
after committing a result and before disclosing it or recovering it later.
Loading configuration, checking setup and installing local access perform no
provider I/O. An explicitly enabled and installed managed runtime can call the
fixed sandbox origin; tests inject `httpx.MockTransport`.

The adapter uses Elation's current
[client-credentials token exchange](https://help.elationhealth.com/articles/rest/overview/get-token)
and requests only `system/practices.read system/appointments.read
system/patients.read`. Token responses must confirm that exact set. No password
grant, clinician impersonation, refresh grant or broad `apiv2` scope is used.
Tokens stay in memory and expire early; credentials are checked on every read.

| Method | Fixed resource | Result |
| --- | --- | --- |
| `practice()` | `GET /api/2.0/practices/{selected}/` | Exact active practice, IANA timezone, active physician IDs |
| `appointments(start, end, physician_id?, cursor?)` | `GET /api/2.0/appointments/` | One page, selected practice, at most seven elapsed days, optional physician |
| `appointment(id)` | `GET /api/2.0/appointments/{id}/` | Exact nondeleted appointment in that practice |
| `patients(first_name, last_name, birth_date, cursor?)` | `GET /api/2.0/patients/` | Exact case-insensitive name and DOB matches in that practice |
| `patient(id)` | `GET /api/2.0/patients/{id}/` | Exact nondeleted patient in that practice |

Resource contracts: [practice](https://help.elationhealth.com/articles/rest/practice-api/practices/retrieve-practice),
[appointments](https://help.elationhealth.com/articles/rest/scheduling-api/appointments/list-appointments),
[patients](https://help.elationhealth.com/articles/rest/patient-profile-api/patients/list-patients).
Resource IDs remain Python integers privately, never JavaScript numbers.
Patient output excludes contacts, SSNs, insurance and free text. Appointment
output excludes description, instructions and billing fields. Returned IDs do
not create a local patient link or prove that an appointment is available.

Each `ElationReadResult` holds one page/record, its scope, request hash,
observation time, normalized rows, query-bound next cursor and content commitment.
`more_rows_available` and `end_of_results` describe pagination; the latter does
not claim that this single page contains earlier pages. The host must never
present a page as a complete practice roster/chart. An empty valid page is a
no-match; malformed/failed responses are errors, never empty successes.

The [cursor contract](https://help.elationhealth.com/articles/rest/overview/pagination)
does not require `count`. One explicit request returns at most 25 rows. A next
link may omit original filters; the adapter reconstructs them from the original
request and extracts only its cursor. Changed host/path/filter, duplicate query
keys and immediately repeated cursors fail closed. There is no URL following or
automatic page traversal. The application must reject longer cursor cycles and
bound its full read session before presenting combined pages.

Time bounds are normalized to UTC before duration checks. Both returned endpoint
instants are retained because vendor inclusivity is not documented. A day view
must use the practice timezone, deduplicate shared boundary IDs and apply its
display interval explicitly. Status is preserved without inventing availability;
an unknown status is rejected and null remains unknown. Deleted records may be
visible as deleted in a list but cannot be selected through record retrieval.

Limits are 10 seconds per HTTP call, 30 seconds for a read including authorization,
one MiB per resource response and 16 KiB per token response. Redirects, cookies,
ambient proxies and compressed responses are not accepted. There are no resource
writes, retries or background polling. A local limiter stays below three calls
per second and 150,000 calls per rolling day, including token requests. The host
now supplies a shared budget through `permit_request`, keyed by client-ID digest
across processes using the same database, including credential generations.
Quota locks are released before waiting or provider I/O. A short child request
budget bounds SQL lock/statement waits and follows parent cancellation;
connection acquisition retains the existing host database factory's timing.
Traffic from another deployment using the same key is outside that budget.

## Validated behavior

Focused adapter, configuration and contract tests pass. Signed API/PostgreSQL
checks pass for explicit installation, exact recovery, changed credentials,
transport substitution, quota contention, source review and disclosure after
commit. Legacy mock observations remain mock; changing the runtime cannot
relabel old vendor observations. Existing managed-service tests pass alongside
the EHR service after correcting a test-fixture teardown leak. The final
combined run retained unchanged source and shut down its owned database cleanly.
Ruff and focused Pyright pass.

Shared UI tests cover direct appointment-task entry, setup and lost-reply
recovery, small/large layouts, unsent Chief and coworker drafts, and withholding
a revoked source. The earlier joined browser/API/database journey also recovers
a lost successful read and prepares Chief with zero model calls. These checks
use invented provider/service responses. They do not qualify real Elation
requests or a rebuilt physical-device client.

The reproducible commands, failures and corrections, source hashes and cleanup
results are retained outside this repository in the dedicated workstream's
`evidence/elation-sandbox-backend-review.json`, `evidence/elation-sandbox-03/`
and `evidence/ehr-task/freeze.json`. The signed fixture uses fresh request-owned
SQL sessions without weakening the CaptureBoundary ownership fence. This slice
requires an authenticated Clerk external identity; a native session without one
is unavailable.

## Milestone 3: one usable selected-source journey

This is the integrated synthetic milestone. Keep F-8 as the existing
work/approval owner. Do not extend the delivery-vendor SQL enum, impersonate a
Google account, turn a static catalog into a connected status, or route through
the Core/Scribe Athena adapter.

1. **Check the configured practice.** Open **Review Elation appointment** from
   Chief's **Details → Notes and sources** or the visit's **Sources**. **Check
   Elation access** shows only this person's configured practice. If setup is
   required, **Use this practice’s Elation sandbox** records the exact local
   installation without a provider call. Credentials never enter the renderer.
2. **Load the chosen date window.** Staff enters a range in the device timezone,
   up to seven elapsed days; returned appointment times use the practice timezone.
   Persist the immutable request before OAuth/resource I/O. Show at most 25
   appointments. When additional records exist, say “Showing this page; more appointments may be
   available.” This slice has no paging command or load-more affordance; an
   explicit narrower date range starts a fresh read.
3. **Review the appointment and patient.** Staff selects a server-issued opaque
   appointment handle. Fetch that exact appointment, require unchanged patient
   identity, then fetch its patient in the same practice. For an independent
   patient search, use a later separately implemented slice. Null, deleted,
   cancelled or changed identity cannot proceed here.
4. **Save to the intended existing visit.** Display minimal patient identity,
   practice, appointment time/status and observation time together.
   Staff confirms this patient and existing workspace. Save one immutable,
   reviewed `ehr_read_source` with expected workspace revision and receipt hash.
   This confirmation does not itself create a cross-system `PatientLink`.
5. **Use the shared conversation.** A shared session action rereads the workspace,
   validates the exact source entry/revision/hash/current authority, preserves
   existing unsent directions, selects Chief and focuses editable directions.
   The staff member uses the existing Send action. No automatic model call,
   clinical write, second task queue or second approval owner is introduced.

### Implemented custody and schema

Additive models and migrations follow `google_calendar_models.py` and
`application/google_calendar.py`, with four distinct read/custody records:

* `EhrReadBinding`: immutable Box/owner/connection/generation/practice/environment
  identity and commitment; active/revoked state; no raw credential fields.
  Composite owner foreign keys must prevent cross-Box substitution. New
  credentials or practice selection create a new version rather than rewrite it.
* `EhrReadRequest`: owner-bound idempotency key, exact operation/query hash,
  binding commitment, original transport, ordinal and request timestamp. Commit
  reservation before network I/O. One key plus changed payload is a conflict.
  Client commands carry opaque appointment handles; they never accept provider
  URLs or free-form remote record IDs from the renderer.
* `EhrReadSnapshot`: one immutable request result and commitment, original
  normalized observation plus private provenance. Verify Box/owner/binding,
  request and payload hashes on every read. Only a single page is accepted by
  application commands; provider cursor details remain private and cannot be
  submitted by the renderer. Partial coverage stays explicit.
* `EhrReadSourceReview`: exact snapshot/item commitment, workspace identity and
  revision, confirming human and review time. One review creates/reuses one
  `ehr_read_source`; no unrestricted `evidence` fallback. Its history is
  immutable. Read expiry and revocation withhold content; they do not erase it.

Binding authorization must refresh the authenticated external identity and human
seat, current Box membership and installed generation before dispatch and before
publishing. Inspection, recovery, selected-source access and model-context access
repeat these checks. Changes withhold prior content and derived drafts while
retaining permitted historical provenance. The repository currently has no
source/workspace deletion endpoint. A future deletion/retention implementation
must cover the read ledger and recovery endpoints before real patient data is
permitted; the existing artifact purge does not erase EHR snapshots.

### Application and UI contract

* `adapters/elation_read_runtime.py` supplies `SyntheticElationReads`, requiring
  exact invented scopes and an exact `httpx.MockTransport`. The host installs it
  as `app.state.ehr_reads` and seeds a matching immutable `EhrReadBinding`; tests
  demonstrate this through the compact signed `ehr_case` fixture.
* `adapters/elation_sandbox_runtime.py` supplies `ManagedElationSandboxReads`
  through the existing managed-service lifespan. Private configuration binds
  the Box, owner, authenticated account, connection, generation, test practice,
  timezone and exact `SecretReference` digests. It requires both
  `workspace_ehr_read_enabled` and `workspace_elation_sandbox_enabled`; both
  default false and hosted use remains unavailable. The fixed sandbox origin
  and `synthetic_only` classification are mandatory. The two runtimes cannot
  be installed together. Operator steps are in the
  [sandbox access packet](beta/ELATION_SANDBOX_ACCESS_REQUIREMENTS.md).
* `application/elation_sandbox_installation.py` persists a human's exact local
  installation with an immutable receipt; configuration loading does not
  activate access. The command contains only `action: "install"`, opaque
  `installation_id`, `installation_sha256` and `idempotency_key`. A repeat or
  resolve returns that receipt as `installed` or `unavailable` after current
  access checks. Neither outcome proves a successful provider read. Installation
  and read commands cannot reuse one key for different work.
* Migration `n13f9b2d7654` follows `m02e8a1c6543`, adding installation receipts,
  shared quota tables and immutable request transport. `transport` is `mock` or
  `vendor_sandbox` in setup/read/review receipts and in the hash-bound private
  snapshot; access and recovery compare it to the current runtime. Legacy
  missing transport means only `mock`. Public `mode: "synthetic"` still describes
  the data restriction, and the original source content/hash contract remains
  compatible.
* `application/ehr_reads.py` implements `observe`, `verify`, `inspect_observation`,
  `resolve_observation`, `select_review`, `validate_selected_source` and
  `historical_source`; retain the existing reservation-before-I/O pattern.
  `resolve_observation` and `inspect_observation` make zero provider calls.
* Bounded POST commands under `/connections/ehr/reads` implement `status`,
  `install`, `observe`, `verify`, `inspect`, and `resolve`. There is no independent
  patient search route. Review is
  `/workspaces/{workspace_id}/ehr-read/review` with observation/item commitment,
  expected revision, explicit identity/visit confirmations and idempotency key.
  Current workspace identity, fresh mutation fences and no-store responses apply.
  Every read receipt carries exact `connection_id` and `binding_sha256` so
  the renderer can compare it to the reserved command before accepting content.
* `application/selected_connector_sources.py` dispatches `ehr_read_source` →
  `ehr_source_state`, then workspace projection/schema and source withholding.
  `web/src/session/sources.ts` and `session/conversations.ts` use the shared
  session so both app presentations have identical recovery/access.
* The shared UI uses an EHR DraftJournal address/payload validator. It persists
  the exact pending command before dispatch. Reload restores the selected source and command;
  “Check saved result” resolves that command. A fresh read uses a new key only
  after explicit Refresh. Query edits cannot overwrite the old pending command.
  A server-resolved unconfirmed reservation may be followed by an explicit new
  window request; that reservation supersedes the old window and its pending
  verifications before I/O. It does not redispatch the old key or infer success
  from a transport error. Installation recovery likewise resolves the persisted
  exact command; only a confirmed `not_found` offers an explicit resend of that
  same command against the current installation. Status, install, inspect and
  resolve perform no provider calls. A successful setup receipt triggers a new
  current-status check before reads are offered.

### Acceptance contract

1. Default/off/setup-pending surfaces and local installation/recovery make zero
   OAuth/resource calls. A current installed practice plus explicit read action
   executes the documented adapter; setup alone does not verify vendor access.
2. Cross-Box, owner, workspace, provider and credential-generation substitutions
   fail before I/O; revocation during I/O withholds the entire response.
3. Lost success response/reload resolves the original receipt with zero extra
   provider calls. A reserved-but-unsaved attempt remains unconfirmed; same-key
   replay cannot redispatch it. Changed command/same key fails as a conflict.
4. An empty page, changed/deleted appointment patient or unknown status cannot
   silently select a patient or create a local link. Independent patient search
   and duplicate-match selection are outside this slice.
5. Additional-page commands are rejected before I/O. A partial page is labelled
   explicitly and the user can choose a narrower range. UTC range checks cover
   repeated clock times and seven-day windows across DST transitions.
6. Review commits only the exact snapshot/item and expected workspace revision;
   a repeated review returns the same receipt. A changed item or revision fails.
7. Saving a source does not call a model. Preparing Chief preserves unsent edits;
   Send uses the existing shared session and existing F-8 work substrate.
8. Revocation, credential rotation or supersession removes selected content
   from fresh and replayed model contexts and derived drafts, while permitted
   historical provenance stays consistent. Physical deletion remains a separate
   required implementation before production data is allowed.
9. Every API response and recovery state passes through the shared contract in
   both presentations; UI tests exercise no-match, timeout, rate limit,
   permission failure and malformed response without dropping the selection.

An empty returned page says no matching appointments were returned and asks
the person to check the date range. Timeout offers saved-result recovery;
permission failure offers practice-connection review; malformed response preserves the selection and offers an explicit fresh
read. Closed adapter codes map to existing application errors with fixed text;
raw provider messages, names, queries or token responses never enter diagnostics.

## Qualification and deferred capabilities

The owner confirmed that no Elation sandbox exists yet. The
[sandbox access packet](beta/ELATION_SANDBOX_ACCESS_REQUIREMENTS.md) records the
current official request route, minimum read grant, invented test fixtures,
private installation procedure and an unsent vendor request. The implemented
runtime has been tested with invented responses only. Neither the packet nor
those tests provision an account or establish vendor access.

Vendor [onboarding](https://help.elationhealth.com/articles/rest/overview/getting-started)
requires vendor agreements/access steps and practice consent before production.
No such step is authorized or performed here. Before activation, qualify actual
scoped token responses, practice restrictions, cursor preservation, date
boundaries, null/deleted fields, throttling and deployment-wide credential
custody using only a separately authorized synthetic sandbox. Production needs
an explicit reviewed host/consent/credential configuration; it is rejected today.

Clinical notes, referrals, booking and e-prescribing are not implemented.
Documented resource creation does not prove notification, signing, dispensing or
delivery semantics. Future writes must use the existing immutable F-8 action
revision/hash and Operation ledger; read access never confers write authority.

No public Atlas.md practice-write API, OAuth flow or reusable official SDK was
verified. Its [documented calendar subscription support](https://atlas.md/help/view/working-with-the-calendar-on-a-tablet/)
can inform a later staff-supplied calendar-file slice. That slice must preserve
`origin=staff_supplied_file`, declared Atlas source, file hash, import time,
`is_live=false` and unverified patient identity. It must never claim live EHR
sync or interpret an event UID/title as a patient ID. Fetching live subscription
URLs and adapting undocumented CSV headers remain outside this milestone.

### Optional reviewed problem-list source

`system/problems.read` is an additional clinical permission, independent from
`system/patients.read`. The existing appointment scope string, binding digest,
status reply, appointment item hash and source text remain unchanged. The new
managed installation flag `problems_enabled` defaults false; when true its
installation commitment includes that scope. The host additionally requires
`WORKSPACE_ELATION_PROBLEMS_ENABLED`. A changed scope profile requires a new
credential generation and explicit installation review. Tests can install the
same separate capability on `SyntheticElationReads` through a callback; it still
requires the exact mock transport and invented records.

An opt-in status request `{action: "status", include_problems: true}` adds the
closed `problems` capability (`available`, `not_enabled`, `not_configured`).
Legacy status commands receive their original shape. The new `problems` action
uses the existing read endpoint and exact command fields of appointment verify,
but references a `verified_visit` observation. Patient identifiers come only
from its immutable private snapshot. The runtime rechecks the same appointment
and full retained patient identity before the problem GET. No arbitrary patient
search, pagination, prescription or clinical-write endpoint is introduced.

The new `verified_problems` observation retains the appointment context and adds
an exact parent commitment and `item.problems`. The list contains up to 25 rows,
optional provider total count and separate `end_of_results`, `more_rows_available`
or `unknown` problem coverage. Fields are description (1–200 characters), status
(Active/Controlled/Resolved), ISO start date, optional resolved date and the exact
provider verification enum, blank or null. Non-Resolved rows cannot carry a
resolved date. Blank/missing verification is not promoted to confirmation.
Provider IDs stay private. Diagnosis codes and synopsis are deliberately outside
the displayed summary and this limit is stated in the saved source. No text is
silently shortened; a source exceeding the existing 5,000-character budget is
refused as `ehr_read_response_too_large`.

Item commitments use `ehr_verified_problems_item.v1` over the complete public
item without its hash. The receipt binds its parent observation ID, source hash
and item hash. Review continues through `ehr_read_source`; source text begins
`Elation problem list (synthetic frozen observation)` and the label is
`Elation: reviewed problem list`. The source hash and review request hash domains
remain unchanged. The database migration `r57d3f6b1098` extends immutable custody
through the verified parent to the original window; new windows, expiry, account
or credential changes and clinical capability withdrawal withhold old content.
Exact resolve/inspect perform no provider reads. A failed read stays reserved;
transport errors never authorize an automatic repeat.

The current public [scope catalog](https://help.elationhealth.com/articles/rest/overview/scopes.md)
and [patient profile schema](https://help.elationhealth.com/openapi/patient-profile-api.yaml)
were captured October 25, 2026. Production and live vendor qualification remain
unavailable. Local tests use only synthetic transport and signed local database
fixtures; external access gates are recorded in the sandbox access packet.
