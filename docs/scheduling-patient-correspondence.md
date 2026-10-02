# Scheduling patient correspondence contract

The product currently needs a reviewed Scheduling patient mapping before an
appointment proposal can use the current staff/practice connection. Staff sign-in
alone does not supply that mapping. Recording and Scribe drafts keep DOB optional.

`ports/scheduling_patient_setup.py` and `adapters/scheduling_patient_setup.py`
implement a candidate typed receiver contract and a gated HTTP client. The
product now has durable preview/confirmation custody, an immutable human-reviewed
mapping writer and a compact patient-selection panel. Neither implementation
installs the receiver endpoint or books an appointment. The default factory is
unconnected and the HTTP client requires a current explicit enable predicate.

The proposed fixed routes are POST
`/v1/companion/patient-correspondence/preview` and `/verify`, with
`X-Cosmaneura-Patient-Correspondence: 1`. POST keeps an explicit name query out of
the URL. The receiver must authenticate the actual Scheduling staff token and
current practice membership on every request. Local Box, owner, patient-link and
workspace IDs are never sent. There is no legacy fallback or automatic retry.

A preview accepts either a server-resolved imported Scheduling appointment
reference or an explicitly submitted bounded name search with nullable DOB.
It returns at most five opaque choices. Each displayed identity commitment covers
the choice, name, nullable DOB and receiver-owned monotonic subject revision.
The revision must advance on every identity mutation, including changed and
restored values; a text hash alone is insufficient. A verify request returns the
patient ID only for the exact original lookup and choice, with the same identity
and subject revision. No name or DOB match grants authority or selects a patient
automatically.

Receipts bind the current practice, staff actor and request nonce. Preview and
verification commitments cover their complete serialized fields with the hash
excluded, using the domain in the port. JSON dates are YYYY-MM-DD; UTC timestamp
serialization is ISO 8601 with Z. Duplicate JSON fields, extra fields, identity
changes, missing no-store/version headers, compressed or excessive responses,
redirects, expired lookup, future DOB and revoked runtime gates are refused.
Unknown responses remain unknown. Credentials and private identity fields are
redacted from exception and model representations.

Before activation, the receiver owner must implement and qualify these lookup,
membership and identity-revision semantics. The product binds every request to
the signed human, current visit, reviewed staff account and sealed semantic grant.
It reserves the exact command before lookup, releases the database transaction
for provider I/O, then checks current source/account access before saving a result.
A choice requires two explicit human acknowledgments of the visit and displayed
identity, including missing DOB. The immutable mapping review is a sidecar; the
existing clinical note is retained. Database constraints protect the request,
snapshot and human review against forged or cross-owner writes.
A correspondence receipt is separate from clinical approval and the immutable
F-8 approval for any appointment change. Hosted appointment execution remains
closed.

The opt-in server flag `WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED` requires
authenticated Scheduling sign-in and appointment proposals; it defaults to false.
The matching `VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED` flag is forced false
in release profiles pending receiver qualification. A synthetic lab may opt in
explicitly. The signed product route is POST
`/workspaces/{workspace_id}/scheduling-patient/setup`, with
`X-Cosmas-Scheduling-Patient: 1`. Status, inspection and exact-key resolution do
not create a provider client. No lookup is submitted on mount or recovery.
Before sending a lookup or confirmation, the UI saves its exact command and key
to encrypted private recovery storage. A lost reply requires inspection of that
original key; retry needs a confirmed absence and an explicit user action.
Source or account changes withhold names and DOB while preserving saved history.
Replacing a saved mapping or reattesting it after reconnect requires a separate
practice review path, which is not implemented here. A new search for a visit
that already has an active mapping is refused before reservation or provider
I/O, so it cannot supersede and strand the saved connection. The UI keeps exact
receipt inspection available and directs corrections to the practice administrator.

Synthetic tests exercise optional DOB, opaque choice verification,
scope/version/hash/refusal behavior, two fixed API bases, transport bounds,
credential and runtime changes, and no automatic network retry. They provide no
evidence of a deployed receiver, live patient lookup or ordinary-user acceptance.
