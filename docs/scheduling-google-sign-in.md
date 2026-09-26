# Scheduling sign-in from CosmasOS

A staff member opens Settings → Connections → Scheduling & Google sign-in,
checks the selected practice, and chooses Connect with Google. The system browser
completes Google consent. On returning to CosmasOS, the page checks connection
status; Check Scheduling connection remains available if the OS does not emit a
return event. Disconnect clears this app's stored credential and pending login.

This uses an existing reviewed `SchedulingAccount` linked to the person's current
CosmasOS external identity. A matching email never creates that correspondence.
The receiver verifies the Google identity and its current staff membership using
`GET /v1/me/staff`. The actor and practice must match the reviewed account exactly.
This sign-in supplies the existing Scheduling availability/appointment adapter.
Google Calendar access is granted separately in Scheduling. Athena is a separate
Core connection. Invited users still need the reviewed OS/Scheduling correspondence;
automatic cross-product account provisioning is not part of this increment.

## Configuration

Apply ordinary OS migrations through `b1839fb874da` and install the W51 Scheduling
receiver. Configure a Google **web** OAuth client that Scheduling accepts as a
Google staff identity audience. Register exactly:
`https://<OS API host>/connections/scheduling/google/callback`.
Requested scopes are only `openid email`; the flow uses offline access, PKCE S256,
a nonce, one-use state, and encrypted credentials. Google provider acceptance and
consent-screen configuration must be completed for the selected beta environment.

Set `WORKSPACE_SCHEDULING_ENABLED=true`, `WORKSPACE_SCHEDULING_LOGIN_ENABLED=true`,
`SCHEDULING_ORIGIN` to the fixed HTTPS receiver origin, and
`SCHEDULING_GOOGLE_CLIENT_ID`, `SCHEDULING_GOOGLE_CLIENT_SECRET`,
`SCHEDULING_GOOGLE_CALLBACK_URI`, `SCHEDULING_LOGIN_RETURN_ORIGIN` to the fixed
HTTPS frontend origin. `SCHEDULING_LOGIN_ENCRYPTION_KEY` must contain a base64url
encoded 32-byte key. Keep both secrets in the server secret manager. Preserve the
key across process restarts; changing it requires users to sign in again. Do not
install a separate SchedulingServiceProfile alongside this credential provider.

The existing authenticated workspace profile must be valid. Build the shared
client with `VITE_WORKSPACE_SCHEDULING_ENABLED=true` and
`VITE_WORKSPACE_SCHEDULING_LOGIN_ENABLED=true`. These are public flags; do not put
server secrets in any VITE variable. CORS must include the exact frontend/native
origins in the existing deployment configuration.

Both native preparation scripts accept `--scheduling-google-client-id` and
`--scheduling-google-callback-uri`. Supply the same public client ID and callback
URI as the server. The native host pins these values and only dispatches the
specific Google consent URL on a trusted user click under a current native session.
Empty native values disable the handoff. Native app launches and real Google
acceptance remain separate from local source/build checks.

At the reverse proxy, disable query-string logging on the callback path. The ASGI
boundary strips its query before application/access logging, but it cannot redact
an upstream proxy's log. No authorization code, state, token, or refresh credential
belongs in telemetry. The browser return URL contains only a nonsecret result hint;
the app checks authenticated status before displaying the connected state.

## Operation and recovery

The normal app lifespan owns the login service and its Scheduling clients. The
service refreshes expiring credentials before existing Scheduling operations.
The refresh claim is durable before HTTP; an uncertain exchange is not redispatched.
Reconnect after an interrupted refresh. A code exchange that loses its process
remains pending until its ten-minute window expires, then a new sign-in can start.
Retries of a pending start return the same consent URL. Account or membership
revocation prevents fresh access. Disconnect does not globally revoke Google's
grant, because that could also affect a separately connected Calendar.

Local W51 qualification uses invented identities and pinned HTTP transports on
ordinary PostgreSQL migrations. It does not establish real Google, deployment,
physical-device, or native system-browser acceptance.
