# Tebra clinical medication review

This synthetic workflow takes an explicitly authorized clinical patient through
medication-record review, saved-source recovery and preparation of an existing
Chief draft. It does not establish live Tebra access, a reconciled medication
list, prescribing or dispensing.

`TebraFhirReadAdapter` is disabled by default. Even when enabled it accepts only an
exact `httpx.MockTransport`; a real HTTP transport is refused before any request.
`SyntheticTebraFhirReads` explicitly registers this reader behind a separate
clinical connection and the default-off `workspace_tebra_fhir_enabled` switch.
Existing Tebra SOAP appointment behavior is preserved. A SOAP patient ID must
never be substituted for a FHIR patient ID. No OAuth acquisition or clinical
write capability is implemented.

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
client-provided permission. The application verifies an immutable, revocable server-owned grant for the
current account, connection, workspace and patient link; a live installation
still requires separately qualified vendor authorization. The credential must match
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
The authorized selection and review screens show the recorded identity for an
explicit human check. Clinical reads reverify the returned Patient against the
server grant before requesting medication records.

This is a bounded projection, not a complete FHIR validator or display-ready
clinical summary. Known clinical primitives and selected instruction fields are
checked; preserved context JSON is not interpreted. Unknown `modifierExtension`
or unqualified `implicitRules` anywhere in a response causes refusal, since
silently ignoring one can change clinical meaning. Unsupported representations
are refused whole. The review screen presents readable groups of all retained
clinical fields, including structured-only directions and original numeric
spelling. The complete canonical source remains available in a nested expansion.
Neither the display nor the formatter infers missing directions or current use.

## Limits and custody boundaries

The reader permits at most 25 MedicationRequest matches, 25 included medications,
75 total Bundle entries, and 25 distinct same-server medication resolutions. It
caps aggregate uncompressed response bytes at 262,144 and the complete canonical
projection at 65,536 bytes. JSON depth/node/string and instruction counts/lengths
are bounded. A result beyond a limit is refused whole; no field or instruction is
silently truncated. This projection limit is not the existing 5,000-character
saved-source allowance. The formatter, application admission, browser parser and
SQL custody separately enforce the complete-source limit.

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

## Clinical patient to Chief

In Chief, open **Details → Review EHR records**, choose **Tebra**, then choose
**Medication records**. Check clinical access, load the authorized patient list,
select the intended patient and explicitly read medication records. Readable
original details retain partial dates, negation, recorded qualifiers, codes,
structured dosing and unknown values. Three explicit confirmations cover patient
identity, the complete snapshot, and checking outside information before relying
on it. Saving a source and preparing a Chief draft do not send a message.

The clinical connection is independent of the SOAP appointment connection. Its
`protocol: fhir` discriminator is required on actions, status, inspection,
recovery and review. It has no invented numeric practice/customer IDs and does
not require an external appointment. The existing CosmaBot visit still owns the
workspace and confirmed patient link. Server-owned grants pin that exact context,
FHIR identity, authorization hash and connection generation. SQL rejects malformed
or mutable grant proofs and fences concurrent withdrawal.

The existing EHR request, snapshot, review and source tables provide custody.
Intent is persisted before provider I/O, no SQL transaction crosses an HTTP
request, and recovery resolves the original request key without automatically
resending it. A separate encrypted `ehr-read:tebra:fhir` journal prevents clinical
work from replacing SOAP or Elation work. Leaving or reopening the task retains
the Chief draft; active requests block departure.

Reviewed text is saved as `ehr_read_source`. Preparing Chief rereads the current
workspace and verifies the exact entry/revision/content hash. Current grants,
patient links, binding generations and both feature switches are checked when
releasing sources and admitting or settling model work. Withdrawal hides saved
source text and derived replies while preserving their historical records.

## Remaining vendor requirements

The vendor guide does not establish exact sandbox URLs, usable literal clinical
OAuth scopes, complete public-client PKCE/token details, issuer/practice context,
or SOAP-to-FHIR identity correspondence. These are unresolved prerequisites, not
values that this implementation guesses. The guide's Public user-facing app and
authorization-code instructions coexist with a generic client-secret instruction;
its backend instructions offer `client_credentials` and a JWKS selection while
explicitly stating JWKS is unsupported. No token flow has been selected or wired.

Live authentication, vendor-authorized grant provisioning and actual vendor
response qualification remain outstanding. Broader chart/lab coverage, medication
reconciliation, prescriptions and clinical writeback are separate work. No live
clinical API calls or vendor outreach have occurred. Browser/native release
qualification is tracked separately from the synthetic API and database tests;
physical touch, VoiceOver and haptics are not established by programmatic tests.

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
The clinical workflow above now integrates this formatter with patient selection,
human review, saved-source custody, recovery and Chief. Live authentication and
vendor qualification remain outstanding.

Mac Studio independently passes the same 36 focused cases and changed-file
lint/type checks at `f9d70c6`; all 2,953 committed source files remain unchanged.
Its receipts are in `evidence/mac-studio/tebra-fhir-snapshot/` outside the repo.

## Workflow acceptance

The new interface passes 69 focused cases across eight files and both renderer
type configurations. An actual signed API/SQL/mounted interface journey confirms
Unicode and fractional-value fidelity, a lost response recovered after reopening,
the original request key, exact saved content, retained Chief directions and
source withdrawal. The clinical read makes two invented HTTP GETs; recovery,
review and draft preparation make no additional provider calls or model admissions.

At source commit `5106698`, the frozen backend suite passes all 811 cases,
including ten adversarial SQL cases and eight actual model/source checks for
exact text delivery, unmodified reviewed notes, grant withdrawal and feature-switch
withdrawal. All 2,977 source files remain unchanged during qualification.

The rebuilt browser passes 65 checks across three scenarios, including a 320-pixel
native frame with 200% text. One hosted native workflow passes with zero media
attachments, covering review, Chief draft retention, source return, reachable
controls and the visible native Done control. Preview38 is installed in place on
the owner's phone, its reported build is independently verified, and launch
succeeds. Existing signing and storage identities are preserved; no uninstall or
storage reset occurred. See `CHECKPOINT-TEBRA-CLINICAL.json` and
`native/preview38-phone-summary.json` in the adjacent connector workstream.

All tests use invented records. Hosted native checks and successful installation
do not establish physical VoiceOver, tactile haptics, edge gestures, or actual
draft contents retained across the update.
