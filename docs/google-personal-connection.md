# Personal Google / Gmail connection

The shared Connections screen supports a separate personal Gmail grant. Existing
Scheduling Google/Calendar credentials are not reused. Delegated consent requests
openid, email and gmail.metadata with PKCE, offline refresh and explicit account
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
disconnect and mail only. Core/Athena behavior remains unchanged and read-only.
Native composers require the same exact public Google client/callback, via
--google-connection-client-id and --google-connection-callback-uri. The complete
shared beta feature profile now includes the Gmail screen on all clients.

Reuse: Activepieces community Gmail at
5885f009ad3061fb7ecf78597667d794b27be7fc, MIT attribution in
third-party/activepieces-LICENSE.txt. Only OAuth/read/profile patterns are adapted;
its broad send/compose/modify scopes, raw-MIME attachment expansion, service-account
impersonation and arbitrary API action are not enabled. Official Google contract
sources are hash-recorded in W59/research. Actual Google consent verification,
real-account operation and physical-device/native-sign-in acceptance remain open.
Normal API/worker readiness now expects e5917a2c64bd. No actual provider account,
credential, recording, native installation or deployment was used during development.
