# Scheduling patient correspondence contract

The product currently needs a reviewed Scheduling patient mapping before an
appointment proposal can use the current staff/practice connection. Staff sign-in
alone does not supply that mapping. Recording and Scribe drafts keep DOB optional.

`ports/scheduling_patient_setup.py` and `adapters/scheduling_patient_setup.py`
implement a candidate typed receiver contract and an explicitly disabled HTTP
client. They do not install a receiver endpoint, create a patient mapping, enable
a product route or book an appointment. The default factory is unconnected and
the HTTP client additionally requires a current explicit enable predicate.

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
membership and identity-revision semantics. The product still needs durable
preview/confirmation custody, explicit human comparison with the current visit,
an immutable reviewed mapping writer, and a compact UI with exact-request
recovery. Current source/account access must be checked before and after lookup.
A correspondence receipt is separate from clinical approval and the immutable
F-8 approval for any appointment change. Hosted appointment execution remains
closed.

Synthetic unit tests exercise optional DOB, opaque choice verification,
scope/version/hash/refusal behavior, two fixed API bases, transport bounds,
credential and runtime changes, and no automatic network retry. They provide no
evidence of a deployed receiver, live patient lookup or ordinary-user acceptance.
