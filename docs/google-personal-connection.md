# Personal Google Workspace connection

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
Normal API/worker readiness now expects e5917a2c64bd. No actual provider account,
credential, recording, native installation or deployment was used during development.
