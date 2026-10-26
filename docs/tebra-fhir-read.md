# Tebra FHIR medication-history reader

This is an isolated, synthetic-only engineering slice. It reads and projects one
already-authorized FHIR patient's medication records. It is not a connected Tebra
product, a reconciled medication list, or an end-to-end Chief workflow.

`TebraFhirReadAdapter` is disabled by default. Even when enabled it accepts only an
exact `httpx.MockTransport`; a real HTTP transport is refused before any request.
No runtime registration, OAuth acquisition, UI action, source persistence, or
write capability imports or invokes this adapter. Existing Tebra SOAP behavior is
unchanged. A SOAP patient ID must never be substituted for a FHIR patient ID.

## Implemented contract

The caller supplies `TebraFhirScope`, a per-operation `TebraFhirCredential`, and
two server-owned callbacks:

- `authorize_read(scope)` must confirm the current human/Box access, connection,
  credential generation, and exact clinical patient authorization. It is checked
  before and after requests, while consuming response chunks, and before return.
- `verify_patient(scope, patient)` must verify the returned Patient identity
  against the authorized FHIR identity before clinical resource requests begin.

The scope commitment binds Box, owner, connection, credential generation, FHIR
patient ID, fixed resource origin, and an opaque current authorization hash. This
hash is not an OAuth scope string, proof that a token has clinical access, or a
client-provided permission. Future application code must obtain and verify that
authority through a qualified server-owned connection. The credential must match
the exact scope commitment. Neither credential nor access token is persisted in
the returned projection or provider proof hashes.

The fixed resource base is the vendor-documented production base
`https://fhir.prd.cloud.tebra.com/fhir-request`. Using this string with mock
responses does not qualify production behavior or establish a sandbox origin.
Requests are:

1. `GET /Patient/{FHIR-patient-id}` and verify identity.
2. `GET /MedicationRequest?patient={FHIR-patient-id}&intent=order,plan&_include=MedicationRequest:medication&_count=25`.
3. Only if needed, `GET /Medication/{FHIR-medication-id}` on that same base,
   once per distinct referenced ID.

The Patient instance-read form and Medication instance-read form follow FHIR R4
conventions. Tebra's guide describes its Patient search `id` parameter and
Medication access in conjunction with MedicationRequest; these exact instance
requests still need vendor sandbox qualification.

History is requested without a status filter. `order` and `plan` are included
because US Core describes ordered and reported medications through these intents.
Every returned MedicationRequest must have an exact authorized Patient subject.
Medication resources are catalog records resolved through those requests, not a
second source of patient identity.

Supported medication representations are a CodeableConcept, one matching
contained Medication, an included Medication, or an exact same-server Medication
reference. Off-server, version-specific, identifier-only, URN, unresolved, or
ambiguous references are refused. No arbitrary reference is fetched. Bundle
entry `fullUrl` values must match the fixed base/resource type/logical ID, and
duplicate or unrelated included resources are refused.

## Projection and clinical meaning

The immutable private result contains the Patient identity snapshot/hash,
observed time, ordered returned records, page coverage, reported total, warning
codes, provider response commitments, and a scoped source hash under
`tebra-fhir-medication-history.v1`. Records preserve:

- Source record and patient IDs, recorded status and `order`/`plan` intent.
- Authored date/time exactly as recorded, including partial date precision and
  valid timezone-bearing FHIR timestamps; no precision or timezone is invented.
- `doNotPerform` and reported Boolean/reference values, retaining absence.
- The original request-level `medicationCodeableConcept` or `medicationReference`
  choice and its complete raw value, including reference display/type metadata,
  as `request_medication_json`. Conflicting request metadata is retained alongside
  the resolved medication; it does not override the resolved drug label or grant
  authority to fetch a different reference.
- The complete resolved Medication JSON, including coding, form and ingredients.
  A code without an unambiguous recorded label produces no invented drug name.
- Complete `dosageInstruction` JSON, including text whitespace, structured
  timing/dose/route, additional instructions, and patient instructions.
- Available status reason, requester, encounter, category, notes, reasons,
  course of therapy, dispensing request parameters, substitution, prior
  prescription, based-on/group references, insurance, supporting information,
  detected issues and event history as canonical context JSON.

Dispensing request parameters are recorded request details. They do not establish
that medication was prescribed successfully, transmitted, dispensed, taken, or
reconciled. Status and intent are never converted into a new "current" or
"active medication" claim. Missing dosage instructions remain unknown; partial
or empty pages do not establish an empty complete medication history.

The identity snapshot retains supplied names, identifiers, date of birth,
administrative gender, active/deceased values, links and managing organization.
It is available only to the private identity callback/result; the caller must
decide whether it proves the intended patient.

This is a bounded projection, not a complete FHIR validator or display-ready
clinical summary. Known clinical primitives and selected instruction fields are
checked; preserved context JSON is not interpreted. Unknown `modifierExtension`
or unqualified `implicitRules` anywhere in a response causes refusal, since
silently ignoring one can change clinical meaning. Unsupported representations
are refused whole. A future human
review screen and canonical Chief source formatter must explicitly represent the
retained negation, history, instructions, context and unknowns before admission.

## Limits and custody boundaries

The reader permits at most 25 MedicationRequest matches, 25 included medications,
75 total Bundle entries, and 25 distinct same-server medication resolutions. It
caps aggregate uncompressed response bytes at 262,144 and the complete canonical
projection at 65,536 bytes. JSON depth/node/string and instruction counts/lengths
are bounded. A result beyond a limit is refused whole; no field or instruction is
silently truncated. This projection limit is not the existing 5,000-character
saved-source allowance, which must be separately enforced by future application
admission and SQL custody.

The returned Bundle must be a searchset. Its `self` link must retain exactly the
four requested parameters and values; silently ignored or extra clinical filters
are refused. Match/include/outcome roles, totals and resource identities are
checked. Next links must remain on the fixed server/base and are never followed.
Coverage is `more_rows_available` when next exists, otherwise
`returned_page_only`; neither value claims a complete current chart. The
provider's reported total counts matches, not included medications. Warnings
retain bounded issue codes only, excluding diagnostic prose; error outcomes fail.

No redirects, cookies, environment proxies, retry loops or authentication refresh
are used. Each HTTP call has a 10-second timeout and the whole operation has a
30-second deadline. Responses must be JSON/FHIR JSON without content compression.
Errors use a fixed local code and never include response bodies or token values.
All private record/result/credential dataclasses disable generated value reprs.
No HTTP/logging framework or dependency was added.

## Remaining integration requirements

The vendor guide does not establish exact sandbox URLs, usable literal clinical
OAuth scopes, complete public-client PKCE/token details, issuer/practice context,
or SOAP-to-FHIR identity correspondence. These are unresolved prerequisites, not
values that this implementation guesses. The guide's Public user-facing app and
authorization-code instructions coexist with a generic client-secret instruction;
its backend instructions offer `client_credentials` and a JWKS selection while
explicitly stating JWKS is unsupported. No token flow has been selected or wired.

Next application work needs qualified authorization/custody, exact patient
selection and verification, runtime opt-in, human review, a faithful bounded source
formatter, saved-source parent/proof validation, recovery, Chief admission, and
native UI qualification. None of those gates is claimed by this adapter's unit
tests. There have been no live clinical API calls or vendor outreach.

## Evidence and reusable references

Official sources were retrieved as text on 2026-10-25; PDFs were extracted without
rendering images. The evidence directory adjacent to this repository,
`evidence/tebra-fhir-contract/`, retains source URLs, retrieval times, extracted
text, pinned reference revisions, hashes, and the detailed `contract.json`.

- [Tebra FHIR API User Guide, May 2025](https://www.tebra.com/wp-content/uploads/2025/05/Tebra-FHIR-API-User-Guide.pdf),
  pages 15–18, 23 and 29. SHA-256:
  `d6a8ddf2417607af3fdd7cd779790b1071c420338f260450f7b10b14a6e0d919`.
- [US Core 3.1.1 MedicationRequest](https://hl7.org/fhir/us/core/STU3.1.1/StructureDefinition-us-core-medicationrequest.html),
  [Medication](https://hl7.org/fhir/us/core/STU3.1.1/StructureDefinition-us-core-medication.html)
  and [medication-list guidance](https://hl7.org/fhir/us/core/STU3.1.1/all-meds.html).
- [FHIR R4 HTTP](https://hl7.org/fhir/R4/http.html),
  [search](https://hl7.org/fhir/R4/search.html) and
  [Bundle](https://hl7.org/fhir/R4/bundle.html) contracts.
- Official SMART reference clients: [client-py](https://github.com/smart-on-fhir/client-py)
  at `ee5ea26774d52d5397ebb98a1d64819c279887c4` and
  [client-js](https://github.com/smart-on-fhir/client-js) at
  `c004216e55fb57acbc287806bde4f68404b9de97` (version 3.0.1).
  Their Apache-2.0 licenses permit reuse with required notices. This slice uses
  independently written resource/reference patterns, not copied source or an
  installed SMART client. Their generic authentication, refresh and automatic
  pagination must not be adopted without the separate vendor/custody contract.

Focused synthetic tests cover exact requests/projection, all four medication
representations, patient mismatch and revoked access, invalid clinical values,
date precision, unknown modifiers/implicit rules, original request provenance,
unsafe/ambiguous references, filter changes,
outcomes, aggregate/projection limits, cookies and fixed transport errors.
Verification artifacts are in `evidence/tebra-fhir-reader/` outside the repository.

## Private review snapshot

`application/tebra_fhir_snapshot.py` prepares one immutable review model and
deterministic source string from the reader's exact observation. The caller
must supply current server-owned scope, observation and patient-identity pins;
client-provided hashes do not establish authority. Preparation rechecks current
access before releasing the model and grants neither human approval nor source
admission.

The source retains every projected clinical value, including original and
resolved medication descriptions, structured dose/timing/PRN instructions,
negation, reported state, context and date precision. It distinguishes absent
fields from recorded values without accepting invalid FHIR null primitives.
The entire string must fit the existing 5,000-character EHR source limit.
Oversized histories are refused whole; records or instructions are never
dropped to make them fit. Empty and bounded pages do not establish absence of
medications or a reconciled current list.

The formatter passes 36 focused tests, Ruff and Pyright. Review evidence and
invented examples are in `evidence/tebra-fhir-snapshot/` outside the repository.
The patient-selection screen, human review, saved-source custody, recovery and
Chief integration remain unfinished, as do live authentication and vendor
qualification. This module adds no runtime or connected UI action.
