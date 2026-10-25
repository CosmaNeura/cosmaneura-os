# Elation read adapter and the next integrated slice

Verified locally on 2026-10-25. The adapter is implemented; the production
integration and the source-selection user journey are **not complete**. There is
no application route, managed credential installation, persisted read ledger or
Elation UI wired by this adapter pass. No vendor account was created or contacted.

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

The host must implement the authorization callback with fresh actor, Box,
installation and generation checks. Supplying `True` is not authorization.
It is checked before dispatch and after response. Loading configuration or
constructing the adapter performs no I/O. An explicitly enabled, authorized
instance can call the fixed sandbox origin; tests inject `httpx.MockTransport`.

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
must share a credential budget across every process through `permit_request`;
an adapter's in-memory limiter alone cannot enforce a deployment-wide quota.

## Verified synthetic checks

From the integration checkout:

```text
.venv/bin/python -m pytest tests/unit/test_elation_read.py -q
76 passed in 0.16s
.venv/bin/ruff check src/cosmas_os/adapters/elation_read.py tests/unit/test_elation_read.py
All checks passed!
```

The two DST regressions first failed against the prior implementation, then
passed after UTC normalization. The full suite also verifies disabled/no-auth
zero-I/O behavior, exact OAuth requests, token reuse/rotation, revoked authority,
practice/record isolation, duplicate patient choices, cursor filtering,
malformed/oversized responses, closed HTTP failures, no retries, no redirect or
cookie authority, and protected provenance. These are mocked endpoint contracts,
not proof of a successful vendor sandbox or production qualification.

## Milestone 3: one usable selected-source journey

Deliver this as a distinct migration/lifecycle slice. Keep F-8 as the existing
work/approval owner. Do not extend the delivery-vendor SQL enum, impersonate a
Google account, turn a static catalog into a connected status, or route through
the Core/Scribe Athena adapter.

1. **Choose the installed practice.** Existing connection UI lists only the
   current Box's server-installed Elation practice. It shows setup pending until
   an independently enabled read binding is current. Credentials never enter the
   renderer. Owner selection freezes the exact connection/generation and practice.
2. **Load the chosen date window.** Staff selects a practice-local range of up
   to seven elapsed days and an optional active physician. Persist the immutable
   request before OAuth/provider I/O. Show the returned page and explicit
   “Load more”; do not merge pages from different scopes or requests.
3. **Review the appointment and patient.** Staff selects a server-issued opaque
   appointment handle. Fetch that exact appointment, require unchanged patient
   identity, then fetch its patient in the same practice. For an independent
   patient search require complete first/last name and DOB; show every matching
   choice without auto-selecting. Null/deleted/changed identity cannot proceed.
4. **Save to the intended existing visit.** Display minimal patient identity,
   practice/provider, appointment time/status and observation time together.
   Staff confirms this patient and existing workspace. Save one immutable,
   reviewed `ehr_read_source` with expected workspace revision and receipt hash.
   This confirmation does not itself create a cross-system `PatientLink`.
5. **Use the shared conversation.** A shared session action rereads the workspace,
   validates the exact source entry/revision/hash/current authority, preserves
   existing unsent directions, selects Chief and focuses editable directions.
   The staff member uses the existing Send action. No automatic model call,
   clinical write, second task queue or second approval owner is introduced.

### Required custody and schema changes

Use additive models/migration patterned after `google_calendar_models.py` and
`application/google_calendar.py`, with four distinct records:

* `EhrReadBinding`: immutable Box/owner/connection/generation/practice/environment
  identity and commitment; active/revoked state; no raw credential fields.
  Composite owner foreign keys must prevent cross-Box substitution. New
  credentials or practice selection create a new version rather than rewrite it.
* `EhrReadRequest`: owner-bound idempotency key, exact operation/query hash,
  binding commitment, ordinal and request timestamp. Commit reservation before
  network I/O. One key plus changed payload is a conflict. Store only bounded
  opaque selection/cursor references in client commands; never accept provider
  URLs or free-form remote record IDs from the renderer.
* `EhrReadSnapshot`: one immutable request result and commitment, original
  normalized observation plus private provenance. Verify Box/owner/binding,
  request and payload hashes on every read. An explicit page chain is limited
  to 20 pages/500 rows, rejects any repeated cursor or conflicting duplicate ID,
  and records every page request. Reaching the cap remains visibly incomplete.
* `EhrReadSourceReview`: exact snapshot/item commitment, workspace identity and
  revision, confirming human and review time. One review creates/reuses one
  `ehr_read_source`; no unrestricted `evidence` fallback. Add that entry kind
  via migration and use existing retention/deletion conventions for its content.

Binding authorization must refresh the authenticated external identity and human
seat, current Box membership and installed generation before dispatch and before
publishing. Inspection, recovery, selected-source access and model-context access
repeat these checks. Changes withhold prior content and derived drafts while
retaining permitted historical provenance. Deleting the source or workspace
cannot leave a replay endpoint that discloses deleted content.

### Application and UI wiring

* Add typed optional EHR read installation/configuration and a factory in
  `adapters/managed_service_configuration.py` and `adapters/managed_services.py`.
  Use the existing hash-checked `SecretReference` resolver. Configuration load
  validates only. Factory authorization binds current identity to the selected
  immutable scope; all instances share the credential request budget.
* Add `application/ehr_reads.py` with `observe`, `inspect_observation`,
  `resolve_observation`, `select_review`, `validate_selected_source` and
  `historical_source`; retain the existing reservation-before-I/O pattern.
  `resolve_observation` and `inspect_observation` make zero provider calls.
* Add bounded POST command routes under `/connections/ehr/reads` for
  `observe_appointments`, `inspect`, `resolve`, and `/connections/ehr/patients`
  for `search`, `inspect`, `resolve`. Review is
  `/workspaces/{workspace_id}/ehr-read/review` with observation/item commitment,
  expected revision, explicit identity/visit confirmations and idempotency key.
  Use current workspace identity, fresh mutation fence and no-store responses.
* Extend `application/selected_connector_sources.py` with `ehr_read_source` →
  `ehr_source_state`, then workspace projection/schema and source withholding.
  Extend `web/src/session/sources.ts` and `session/conversations.ts` through the
  shared session, so both app presentations have identical recovery/access.
* Add an EHR DraftJournal address/payload validator. Persist the exact pending
  command before dispatch. Reload restores the selected source and command;
  “Check saved result” resolves that command. A fresh read uses a new key only
  after explicit Refresh. Query edits cannot overwrite the old pending command.

### Acceptance tests required for milestone 3

1. Default/off/setup-pending surfaces make zero OAuth/resource calls. Current
   installed practice plus explicit read action executes the documented adapter.
2. Cross-Box, owner, workspace, provider and credential-generation substitutions
   fail before I/O; revocation during I/O withholds the entire response.
3. Lost success response/reload resolves the original receipt with zero extra
   provider calls. A reserved-but-unsaved attempt remains unconfirmed; same-key
   replay cannot redispatch it. Changed command/same key fails as a conflict.
4. Empty search, duplicate matches, changed/deleted appointment patient and
   unknown status cannot silently select a patient or create a local link.
5. Additional pages preserve exact scope/query, reject cycles/duplicates and
   display the 500-row cap as incomplete. Local-day tests cover spring/fall DST
   and shared boundary timestamps without creating duplicate appointments.
6. Review commits only the exact snapshot/item and expected workspace revision;
   a repeated review returns the same receipt. A changed item or revision fails.
7. Saving a source does not call a model. Preparing Chief preserves unsent edits;
   Send uses the existing shared session and existing F-8 work substrate.
8. Disconnect, credential rotation, source/workspace deletion or supersession
   removes selected content from fresh and replayed model contexts and derived
   drafts, while permitted historical provenance stays consistent.
9. Every API response and recovery state passes through the shared contract in
   both presentations; UI tests exercise no-match, timeout, rate limit,
   permission failure and malformed response without dropping the selection.

No-match wording can state “No matching patients in this practice.” Timeout
offers “Check saved result”; permission failure offers practice-connection
review; malformed response preserves the selection and offers an explicit fresh
read. Closed adapter codes map to existing application errors with fixed text;
raw provider messages, names, queries or token responses never enter diagnostics.

## Qualification and deferred capabilities

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
