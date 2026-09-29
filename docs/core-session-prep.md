# Core Session Prep brief reader

`HttpCoreSessionPrep` uses the dedicated
`POST /service/v1/companion/session-prep/brief` receiver for
`session-prep.context.read` version `1.0.0`, `detail=brief`. The receiver is
merged in Core PR #539, commit `7da82a1a23b59827cf8fe65d88fbeaf3fe33949b`:
`app/routes/companion_session_prep.py` reuses the existing provider brief and
receipt lifecycle in `app/services/session_prep_runtime.py`. Core deployment
remains separate; a merged receiver is not proof of live availability.
The bounded client transport rejects `/service/v1/agent/tools/invoke`.

The client consumes Core's prepared artifact and provenance. It does not
generate a second summary or treat the existing capture/prep endpoint's prior
generated drafts as clinician-finalized Session Prep sources. Only the bounded
brief contract is accepted; supporting/raw context requires a separate explicit
contract. Pending and unavailable tool receipts are not ready clinical briefs.

Before calling this port, the application must verify current owner, workspace,
encounter, bot source permissions and Core account access. It must use the
provider-record mount-context exchange, resolve the current interaction and its
Session Prep context reference, and obtain Core's accepted canonical
`provider_ui_action` turn for `session-prep.open`. Neither the context reference
nor source turn may come from an arbitrary client-supplied value. The caller
passes that server-owned selection and the same immutable idempotency key.
Reading the tool can queue Core's existing preparation build when no current
artifact exists; it therefore follows the human's accepted action.

The token callback must supply the specifically approved Session Prep workload
identity. Core requires an additional, default-off `COMPANION_SESSION_PREP_ENABLED`
permission for its existing `AGENT_API_COMPANION_CLIENT_ID`. CosmaBot can
explicitly configure that same CosmaBot identity for Session Prep; a working
capture connection alone does not establish this permission. No implicit
fallback to capture credentials or use of Scribe/Sovereign identities is implemented.

The transport bounds the response, verifies its client-turn header, rejects
redirects and duplicate fields, and checks receipt state, chronology, versions,
source classes and every citation. It does not log clinical content, persist
tokens, retry automatically or follow links. Errors are fixed codes. A retry
reuses the same immutable selection; Core can replay a pending receipt even
after generation completes, so a later refresh requires the owning application's
new, authorized UI-action lifecycle, not a changed payload under an old key.

The application exposes this flow through the existing native transport route,
`POST /workspaces/{id}/capture/prep`, with `view: "brief"` and a current bot
selection. Existing requests default to `view: "sources"` and retain the saved
intake/prior-draft reader. The request's small, closed body cannot select a Core
actor, patient, service identity, context reference or source turn.

Each explicit open checks current workspace ownership, encounter visibility,
active external identity/Core account, team revision and saved-source permission
before every remote phase and before disclosure. It exchanges the user JWT for
encounter context, records the accepted provider action, reads the brief, closes
the action with fixed status text, then replays the same receipt to recheck Core's
current source authorization. Clinical text and credentials are not written to
the conversation or audit log. Revocation or an unconfirmed phase withholds the
brief. The existing owned request deadline also bounds service identity and HTTP
work; the transport profile does not permit capture admission.

The UI displays cited statements, finalized-note versus patient-reported sources,
partial coverage and stale/refreshing status. Pending results offer an explicit
check for the completed brief. Each check starts a new authorized UI action;
it does not mutate an immutable pending receipt or automatically repeat remote
actions. Encounter, identity, bot and permission changes discard old UI results.
An API retransmission keeps a stable Core client-turn ID derived from its
workspace, external identity and idempotency key. Core rejects a changed mount
under that turn, so a lost-response retry cannot silently open another action.
Recovering across exchanged mounts requires a new explicit UI check; this flow
does not persist private mount credentials to promise transparent recovery.
After reviewing a displayed brief, the human can choose **Include in chat**.
The existing composer shows one removable selection. Opening alone does not
include the brief, and changing the encounter, account, bot, team permissions or
explicitly refreshing clears the choice. Sending a question requires no new
setup form. The brief stays separate from the current recording and SOAP review.

The negotiated conversation command carries only `session_prep_analysis` version
1: explicit `consented: true`, opaque brief ID, brief version and SHA-256 of the
exact canonical public display, including freshness and coverage. The server
re-reads and matches that brief before admission and after successful inference.
Those reads use the existing authorized Core lifecycle with distinct stable keys
for each phase, outside model SQL locks. The model receives the whole bounded
brief with its provenance and permitted local notebook/evidence. Oversized
selected context is refused rather than silently dropped. Citations identify
Session Prep sections, without claiming they are the underlying signed notes.

Saved model requests retain the exact selection for retries, resolve and reopen.
An existing admission is returned before new Core or model work. A source or
permission change after inference withholds the answer and retains usage; an
uncertain dispatch remains uncertain and is never automatically resent. Removing
or changing a selected brief also excludes earlier answers based on it from
model history, including answers that omitted citations. Starting a new attempt
requires reviewing the current brief again.

The complete conversation dependency graph has a finite 120-second server
owner. Selected-brief submissions have a 90-second shared web/native client
window; read-only recovery keeps its existing 30-second window. Cancellation
fences further work and leaves the original durable admission available to
resolve. No new database schema or Core capability is introduced by chat use.

Activation requires `WORKSPACE_SESSION_PREP_ENABLED=true`, an explicit
`CORE_SESSION_PREP_MANAGED_IDENTITY_CLIENT_ID`, and `CORE_SESSION_PREP_SCOPE`, in
addition to the existing authenticated Core preparation configuration. The
capability advertises `core.session-prep.brief.v1` only when these inputs are
present; otherwise the UI continues to offer the existing source reader. No
staging manifest enables this feature. The owning Core deployment must separately
enable the narrow companion receiver permission for the explicitly selected
CosmaBot identity. Do not broaden the generic provider-tool allowlist or copy
Scribe/Sovereign credentials. Local checks do not establish real-service acceptance.

Roll out the matching API, web, Mac and iPhone clients before enabling chat use.
Older clients cannot interpret the new selected-brief recovery metadata; do not
activate this feature for an older native cohort. Staging activation remains off
until the separate Core deployment and current-client acceptance are complete.
