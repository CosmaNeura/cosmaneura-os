# Native recording context through the CosmaBot API

Scribe's native encrypted recorder needs the admitted Scribe tenant and session
to open its saved key namespace. Core already supplies this information through
`native_recording_context`; CosmaBot's capture operation projection previously
rejected that read.

The existing `/workspaces/{workspace_id}/capture/operations` route now accepts
that operation for an already admitted configured recording. It uses the current
human, workspace, encounter and reviewed Core account mapping. It rechecks local
authority after each external call and validates the Core envelope, nonce,
freshness, workspace, session, receipt shape and recording status before returning
the context. A legacy recording remains on its existing recovery path.

The Scribe tenant UUID comes from Core's admitted recording context. It is not
derived from the Core authority-tenant reference or accepted from a client field.
The read creates no recording, key, capture lease, source grant or microphone
permission. Existing admission and consent checks remain required.

This is the API connection required for the upcoming native host integration.
It does not select Scribe's native host in the shipped app. The Swift connection,
native key and queue custody, host/renderer selection and retained-recording
recovery must still be integrated together before selection. Current clients and
the `visit-60m-v1` capture profile remain unchanged.

Contract references inspected: Core `app/services/scribe_capture_protocol.py`
and `scribe_capture_gateway.py` at `9d6eef52890a59d0a4eeed62414f903050d5682a`,
and Scribe's native connection/host at
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`.

Validation covers the real CosmaBot HTTP adapter against a synthetic Core wire
and signed workspace HTTP requests against isolated local PostgreSQL, including
revocation during the read, legacy sessions and rejected client namespace input.
These checks do not establish deployment or physical device acceptance.
