# Personal Google Workspace connection

## Reviewed calendar work

The separate, default-off `WORKSPACE_GOOGLE_CALENDAR_ENABLED` service and matching
`VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED` client flag enable calendar summaries for
encounter work. Calendar permission remains independent from full-email consent.
The operational beta profile classifies both flags; the first-owner staging profile
keeps them off. Configure and install a matching release before rollout.

**Work with calendar** explicitly loads one snapshot of up to 25 primary-calendar
events overlapping the next seven days. The clinician selects one event, confirms
the current visit and reviews its exact title, dates and cancellation status. DOB
is optional. Saving adds a distinct `google_calendar` source and preserves the
clinical note and existing email evidence. **Ask Chief** prepares an editable
question; the clinician submits it before Chief or a specialist starts work.

The summary includes only event IDs, titles, start/end dates or times and
cancellation status. Date-only events retain their calendar dates and exclusive
end date. A result not marked cancelled does not establish that an appointment
is confirmed. Partial results are labelled; there is no pagination, event-detail
read, other-calendar traversal, attendee/description/location access, calendar
mutation or booking. These summaries do not establish current availability.

The server reserves the exact request before the single provider read and binds
its frozen window, immutable payload, account and semantic grant. A reviewed
source stops authorizing new work at the earlier of the event's exclusive end or
the window's end. For all-day events without a timezone, authority ends
conservatively before the earliest possible exclusive end; this assigns no
timezone to the event. A newer observation, even an unconfirmed one, supersedes
older calendar sources. Reconnection, revoked permission and expiry withhold
source contents and every derived draft or quoted revision feedback.

The encrypted device journal retains exact unresolved reads and reviews before
dispatch. Checking a saved read result does not repeat the Google request.
A lost source-review reply can be confirmed using the same request after access
changes, with contents withheld. That historical receipt does not authorize
another agent action or import into a clinical note. Calendar-derived Scribe
drafts remain outside the clinical-note import workflow.

The protocol uses `POST /connections/google/calendar-summaries` and
`POST /workspaces/{id}/google-calendar/review`, with
`X-Cosmas-Google-Calendar: 1`, bounded bodies/responses and no-store replies.
The server owns the account and seven-day range; clients cannot supply provider
URLs, different calendars or a replacement summary. Current schema is
`g42b8d3f6a10`; the workspace compatibility contract adds `google_calendar:1`.
Synthetic tests and injected upstreams qualify local contracts and workflows,
not installed native behavior or live Google/model performance.

The prepared database runtime retains its seven pure-validator execution grants.
Ten scoped validation triggers run with the migration owner's privileges and a
fixed `pg_catalog` search path so their nested private checks work under that
restricted role. Direct execution of those triggers and state-reading helpers
remains denied. The inherited Gmail read trigger remains an invoker. Restricted
credential tests cover ordinary agent admission, calendar/email coexistence,
handoff revision and acceptance, revoked access and forged ownership.

## Reviewed email work

The separate, default-off `WORKSPACE_GOOGLE_MESSAGE_ENABLED` service enables
explicit full-message consent and reviewed email work. Its matching renderer flag
is `VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED`; the operational beta feature profile
includes that flag, while the limited first-owner profile leaves it off. Existing
metadata-only accounts remain usable and must deliberately add full-message access
before this workflow can read message bodies. Sign-in alone does not qualify it.

**Work with email** lists bounded Inbox headers, reads one server-observed message,
and asks the clinician to confirm the current patient/visit and exact untrusted
source. DOB remains optional. Saving creates a separate `google_message` source;
it does not overwrite the clinical note. **Ask Chief** prepares an editable request
referencing that saved source. Chief and its specialists use the same verified
source and human review/revision loop as other permitted encounter evidence.

Supported bodies are complete, bounded plain text, including an explicitly paired
plain alternative to HTML. Independent HTML parts, attachments, ambiguous MIME,
invalid encoding or content exceeding 5,000 characters require human attention;
they are never silently shortened into a complete source. There is no attachment
fetch, HTML rendering, sending, label mutation or automatic model ingestion.

Snapshots bind the exact observed message, account, semantic OAuth grant and read
ordinal. Revocation, changed consent or a later read of that message withholds old
source and derived draft contents at admission, tool reads, settlement and workspace
projection. Token refresh alone preserves a semantically unchanged grant. The
ordinary clinical note remains independent; a Google-derived Scribe draft cannot
be imported into the clinical-note workflow without a future qualified lineage
contract.

The encrypted account editor retains uncertain list/read/source-review commands
before dispatch. Recovery checks the original key rather than automatically
repeating a provider read. Source and handoff review replies carry exact public
command hashes. A saved historical review can be confirmed after email access
changes while its source, derived result and quoted feedback remain withheld.
That receipt confers no current authority to continue work. Handoff revision
commands still require visible verified prior draft/feedback; recovery of a lost
revision reply after access changes remains fail-closed.

Current required schema: `g42b8d3f6a10`. Matching workspace contracts include
`google_messages:1` and `handoff_review:2`. Install a matching native/web release
and deliberately configure the backend before rollout. The new tests use invented
mail and injected upstream model responses; they do not establish live full-body
consent, installed native acceptance or Google/model latency.

## Existing connection and bounded previews

The shared Connections screen supports a separate personal Google grant. Existing
Scheduling Google/Calendar credentials are not reused. Delegated consent requests
openid, email, gmail.metadata and calendar.events.readonly with PKCE, offline refresh and explicit account
selection. Stable Google subject identity comes from OpenID userinfo; verified
email is a display field and never grants practice membership.

The Google service reuses the established Microsoft durable OAuth state and
private custody implementation via provider-specific models, encryption context,
audit namespace and wire operations. Microsoft retains its original table names,
encryption context, consent and Graph contract. Google has separate attempt and
credential tables. Single-use attempts are claimed before exchange; lost/unknown
replies are not replayed. Refresh must retain the exact Google subject. Disconnect
clears local sealed credentials and pending grants; a later callback cannot restore
a canceled connection. It does not claim to revoke Google's external account grant.

The inbox view reads at most10 INBOX IDs and selected Subject/From metadata,
internal timestamp and unread label state. No query/pagination, body, attachments,
mail sending, label changes, calendar writes or implicit AI ingestion. All data is
untrusted display text. Current membership and exact sealed credential are checked
before/between/after each read. Whole-operation/request deadlines, response bounds,
strict typed projections and no-store responses apply. Retained audit fields contain
no tokens or email content. Unknown exchange results remain recoverable by status
inspection, cancellation and a new explicit consent attempt.

Configure WORKSPACE_GOOGLE_CONNECTION_ENABLED and GOOGLE_CONNECTION_CLIENT_ID,
CLIENT_SECRET, CALLBACK_URI, RETURN_ORIGIN and ENCRYPTION_KEY in the deployment
configuration system. The callback path is /connections/google/callback; return
origin is exact HTTPS. Secrets remain server-side. The normal app lifespan owns
the default-off service; the protected session POST supports status, start,
disconnect, mail and calendar. Core/Athena behavior remains unchanged and read-only.
Native composers require the same exact public Google client/callback, via
--google-connection-client-id and --google-connection-callback-uri. The complete
shared beta feature profile includes Google email and calendar on all clients.

Calendar reads at most 25 primary-calendar events overlapping the next seven
days, with only IDs, titles, start/end times and status requested. There is one
fixed GET, no page traversal, descriptions, attendees, locations, other calendars
or event writes. Date-only events preserve their original date across time zones.
Malformed, duplicate, oversized or out-of-window events fail closed. Current
membership and exact sealed custody are checked before/after provider I/O and
again before the content-free calendar-read audit and result disclosure.

Existing Gmail-only credentials remain valid without changing their binding.
Updated clients opt into status capability flags derived from the existing sealed
grant, without refreshing tokens or reading provider contents. The connection
directory identifies Gmail-only accounts as partly connected; the detail screen
offers Add calendar access while email remains usable. These flags describe
granted access, not a successful live-read check. Legacy clients receive the
unchanged status contract. New clients fall back once to legacy status on older
servers, within the same request deadline, and label Calendar access as unchecked.
They can still read mail; calendar requests return a specific reconnect instruction
before any Calendar request is sent. An explicit new Google consent grants calendar
access. Exact legacy and expanded scope sets are accepted; broader scope sets are
rejected. Updated native clients accept both exact URL contracts. Install an updated
native build before starting expanded consent from it. The offline connector lab
covers calendar reads, timeout/recovery, throttling, refresh, response bounds and
mid-read revocation; these checks do not assert live Google acceptance.

Reuse: Activepieces community Gmail at
5885f009ad3061fb7ecf78597667d794b27be7fc, MIT attribution in
third-party/activepieces-LICENSE.txt. Only OAuth/read/profile patterns are adapted;
its broad send/compose/modify scopes, raw-MIME attachment expansion, service-account
impersonation and arbitrary API action are not enabled. Official Google contract
sources are hash-recorded in W59/research. Actual Google consent verification,
real-account operation and physical-device/native-sign-in acceptance remain open.
Normal API/worker readiness now expects g42b8d3f6a10. No actual provider account,
credential, recording, native installation or deployment was used during development.
