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

This component is not yet connected to a runtime setting, HTTP route or UI.
Those require the dedicated Core permission and the complete application-owned
interaction lifecycle, current-source checks, pending recovery and native/web
acceptance. It must not be advertised as enabled or counted as live Session Prep
acceptance. Existing staging manifests, source-reader behavior and Scribe
recording flows are unchanged.
