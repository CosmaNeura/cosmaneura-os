# Personal Microsoft email and calendar

Connections now offers a separate Microsoft account grant. After accepting their
CosmasOS invitation, a current member can select Connect Microsoft, approve the
Microsoft consent screen, return to the app and read their recent inbox or next
seven days of calendar events. Scheduling staff login remains a separate grant.
The first beta adapter is for a configured Entra work/school tenant; consumer
Microsoft accounts and cross-tenant onboarding are not included in this profile.

The app requests delegated `offline_access User.Read Mail.Read Calendars.Read`.
Graph operations are limited to GET `/v1.0/me`, GET
`/v1.0/me/mailFolders/inbox/messages`, and GET `/v1.0/me/calendarView`.
Only 25 message headers or event summaries are returned per request. The calendar
view expands recurring instances. Message bodies, attachments, sending, editing,
application-only grants and automatic clinical-record imports are absent.
Athena's independent read-only contract remains unchanged.

The server uses authorization code with S256 PKCE and a single-use state bound
to the current ExternalIdentity, Box, human membership and installed configuration.
The code exchange and refresh are claimed in PostgreSQL before provider I/O.
Refresh tokens and access tokens are AES-GCM encrypted, never returned to the
renderer. A lost exchange/refresh requires explicit reconnection. Current-owner
checks occur before provider work, between token and account requests, and before
disclosing read results. Disconnect erases stored credentials and cancels pending
exchanges. It does not revoke the application's consent in Microsoft; that can be
removed in the user's Microsoft account permissions. Read results stay in the
current screen's memory and clear when identity changes or another action begins.
Audits contain operation metadata only. Unknown outcomes are not auto-replayed.
Failed callbacks now record one fixed failure category in the existing audit,
alongside atomically invalidating the single-use attempt. Provider response bodies,
exception messages, authorization codes and tokens are never included. Google inherits the same
durable failure handling. A timeout in the app distinguishes an unreceived callback
from an unconfirmed connection; it does not imply that sign-in is still running.

Ordinary migration `c48b673e219a` adds the two personal-connection tables after
`b1839fb874da`. The default-off runtime requires authenticated Clerk workspace mode,
`WORKSPACE_MICROSOFT_CONNECTION_ENABLED=true`, and these server settings:

- `MICROSOFT_CONNECTION_TENANT_ID`: exact Entra tenant UUID.
- `MICROSOFT_CONNECTION_CLIENT_ID`: registered confidential web-client UUID.
- `MICROSOFT_CONNECTION_CLIENT_SECRET`: supplied by the deployed secret store.
- `MICROSOFT_CONNECTION_CALLBACK_URI`: exact HTTPS API origin plus
  `/connections/microsoft/callback`, registered in Entra.
- `MICROSOFT_CONNECTION_RETURN_ORIGIN`: exact HTTPS workspace web origin.
- `MICROSOFT_CONNECTION_ENCRYPTION_KEY`: base64url-encoded 32-byte secret.

The shared web feature requires `VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED=true`
plus the existing authenticated-workspace flags. Desktop and Apple preparation
accept `--microsoft-connection-tenant-id`, `--microsoft-connection-client-id`, and
`--microsoft-connection-callback-uri`. Their native navigation policies pin these
public values, require the current native session and a trusted click, and only
open the exact consent URL and read-only scopes. Server secrets never enter
native configuration. Empty values disable the handoff. The callback returns a
fixed status fragment, not a credential; the app then checks server-side status.

## Reused source

Delegated OAuth/Graph mapping patterns are adapted from the MIT community pieces
in [Activepieces](https://github.com/activepieces/activepieces/tree/5885f009ad3061fb7ecf78597667d794b27be7fc/packages/pieces/community),
commit `5885f009ad3061fb7ecf78597667d794b27be7fc`. The retained upstream snapshot is
in the W52 research evidence; its license is included at
`docs/third-party/activepieces-LICENSE.txt`. Enterprise directories, write actions,
custom API dispatch and application-only access were excluded. The token custody,
authority checks, callback and native transport reuse CosmasOS/Scribe foundations.
Calendar recurrence uses Microsoft's documented calendarView endpoint rather than
the upstream list-events endpoint. Reference:
[Microsoft calendarView](https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0)
and [mail-folder messages](https://learn.microsoft.com/en-us/graph/api/mailfolder-list-messages?view=graph-rest-1.0).

Local qualification uses invented identities and injected provider HTTP responses.
Real Microsoft consent, tenant policy/admin consent, deployed callbacks, physical
phone/desktop execution and release acceptance remain outstanding.
