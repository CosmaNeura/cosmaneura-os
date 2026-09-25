# Workspace compatibility and controlled updates

The operational web, Mac and iPhone clients check the signed
`GET /practice-access/compatibility` response before mounting onboarding or the
private workspace. Invited accounts can check compatibility before owner approval;
this read grants no practice or service access. It returns only implemented wire
contracts, never identities, accounts, secrets or service health.

The client requires protocol 1 and the 23 compiled workspace contract revisions.
Unknown optional numeric contracts are allowed; missing or changed required
contracts, malformed data and a legacy server's missing endpoint stop admission.
The existing practice-access transport supplies fresh credentials, session fences,
closed JSON parsing, a 4 KiB handshake response cap and a 15-second deadline.

Hosted deployments with WORKSPACE_DRAFT_RECOVERY_REQUIRED=true require exactly
one X-Cosmas-Workspace-Protocol: 1 header on all workspace API families. This is
already selected by the current operational deployment template. The server
rejects absent, repeated or unsupported declarations before reading the body or
entering a handler. Every workspace response identifies its protocol. CORS allows
and exposes that header; the desktop main-process proxy forwards it in both
directions and withholds unidentified successful responses. Health checks,
vendor/payment event receivers and the three exact OAuth callback reads retain
their separate contracts. Local legacy profiles remain unchanged.

All 25 shared workspace API transport modules use the same dispatch guard. A
successful response without the expected protocol, or an HTTP 426, pauses future
requests for that mounted identity. Responses already in flight cannot enter the
workspace after a compatibility failure and recheck. A proxy 5xx is an ordinary
connection failure, not evidence that the service needs an update. Actual 401/403
identity denial retains the existing private-view clearing behavior.

On a compatibility pause, the workspace stays mounted. The user can keep editing
or stop a recording. New recording Start is refused. Existing recording custody,
leases and stop/recovery remain authoritative; previously dispatched requests and
uploads may still finish. Exact unconfirmed writes and edits remain in their
existing recovery systems. A prominent Check connection action performs a fresh
handshake; success permits new requests without replaying previous commands or
reloading the page. Internally a paused ordinary operation is a 503, not an identity
loss: that distinction preserves existing editor and receipt recovery behavior.

Controlled rollout requires the compatible client distribution to be available,
recordings stopped and pending/saved work reconciled before switching an active
cohort. New clients will refuse an older backend; older clients are refused by a
required-protocol backend. Keep the previous compatible client/backend artifacts
for a coordinated rollback. Do not disable the required-protocol gate as a fallback:
current operational clients also require the server to report enforcement active.
No schema change is needed for this increment. Future incompatible wire changes
must update the advertised protocol/contracts and paired admission rules; product
build numbers alone are not compatibility evidence.

Local checks cover the actual signed HTTP stack, pre-dispatch refusal, CORS,
callbacks, current native proxy, live owner-approval recovery UI, editor retention
and recording controls. Real account, installed device, signing and deployment
acceptance remain separate. Athena stays strictly read-only.
