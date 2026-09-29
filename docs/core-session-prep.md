# Core Session Prep brief reader

`HttpCoreSessionPrep` implements the existing
`POST /service/v1/agent/tools/invoke` contract for
`session-prep.context.read` version `1.0.0`, `detail=brief`. The reference is the
Core service contract at commit `9f09bafa87bfb468a627f01d27ff31791c07c9f5`:
`app/routes/agent.py`, `app/services/session_prep.py`, and the provider artifact
implementation in `app/services/session_prep_runtime.py`.

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
identity. Core deliberately restricts its tool caller separately from capture
callers; a working Scribe capture connection does not establish this permission.
No fallback to capture or Sovereign credentials is implemented.

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
This view does not yet supply the brief to subsequent AI chat turns.

Activation requires `WORKSPACE_SESSION_PREP_ENABLED=true`, a dedicated
`CORE_SESSION_PREP_MANAGED_IDENTITY_CLIENT_ID`, and `CORE_SESSION_PREP_SCOPE`, in
addition to the existing authenticated Core preparation configuration. The
capability advertises `core.session-prep.brief.v1` only when these inputs are
present; otherwise the UI continues to offer the existing source reader. No
staging manifest enables this feature. The owning Core deployment must separately
authorize the dedicated caller; copying capture or Sovereign credentials is not
an activation procedure. Local checks do not establish real-service acceptance.
