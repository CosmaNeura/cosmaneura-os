# Athena allergy review to Chief

This synthetic workflow takes an independently authorized clinical patient
through allergy review, saved-source recovery and preparation of an existing
Chief draft. The runtime is default-off and accepts only an exact
`httpx.MockTransport`. Existing schedule/visit links do not confer clinical
access. No live credentials or clinical write capability are added.

In Chief, open **Details → Review EHR records → Athena**, check allergy access,
then load authorized patients. Choose the intended patient and chart department,
read allergy records, review the recorded allergy/reaction/severity/criticality,
original notes and dates, then save that exact source and prepare a Chief draft.
An explicit no-known-drug-allergies statement is shown separately from an empty
returned list. Contradictory statements and returned records remain visible.

## Official request contract

Official references were retrieved on October 26, 2026 from the documentation
portal's published content API, with originals and hashes in the workstream
`evidence/athena-clinical-read` directory.

- [Allergy](https://docs.athenahealth.com/api/api-ref/allergy):
  `GET /v1/{practiceid}/chart/{patientid}/allergies`, required `departmentid`,
  `showinactive=true`. No limit, offset, next URL or total is documented for this
  endpoint. The adapter never invents or follows pagination.
- [Patient](https://docs.athenahealth.com/api/api-ref/patient):
  `GET /v1/{practiceid}/patients/{patientid}?departmentid=...`, exactly one
  returned patient record. Department selection matters for enterprise practices
  with copies across financial/provider groups. Returned registration/current
  department IDs are preserved in the private identity proof and are not
  substituted for authorized chart department.
- [Token endpoint](https://docs.athenahealth.com/api/guides/token-endpoint):
  preview origin `https://api.preview.platform.athenahealth.com`; production
  origin `https://api.platform.athenahealth.com`; `/oauth2/v1/token`. The official
  service example uses `client_credentials` and
  `athena/service/Athenanet.MDP.*`. These are documentation facts, not a live
  connection implemented or permission granted by this slice.

No `PATIENTFACINGCALL`, `THIRDPARTYUSERNAME`, undocumented user-access parameter,
or patient search is sent. The documented `checkuseraccess` Patient option
requires internal-only/session-user context; it cannot establish ordinary app
user authority here. Production authorization must be established separately.

## Fixed application interface

`AthenaAllergyScope` pins UUIDs for Box, human owner, current account, connection,
credential generation, destination workspace and patient link, plus vendor
practice/department/patient IDs, display labels, preview/production origin and a
server-owned authorization digest. All dimensions enter
`athena-allergy-patient-scope.v1`. No field is a renderer grant.

`AthenaAllergyReader(scope, exact_mock_transport,
expected_identity_sha256=server_pin, enabled=host_check,
authorize=current_server_grant_check).read()` returns:

- `scope`, `observed_at` (aware timestamp), `patient` (private canonical identity
  JSON and SHA-256), `records` (record ID, original allergen name, complete
  original record JSON), complete `section_json`, exactly two response hashes;
- `coverage="returned_section_only"`, `includes_inactive=True`, and
  `source_sha256` in the `athena-allergy-observation.v1` domain.

A fresh patient read must equal the server's independently reviewed identity
pin before the allergy request. Authorization and enablement are checked before
and after both reads. The bounded response permits at most 25 allergy records
and 65,536 bytes. Unknown section/record/reaction fields and unsupported/null
values are refused; nothing is silently dropped to imply support.

`prepare_allergy_review(observation, expected_scope=server_scope,
expected_source_sha256=stored_observation_pin,
expected_patient_identity_sha256=server_identity_pin,
authorize_read=current_server_grant_check)` returns
`AthenaAllergyReviewSnapshot(observation, source_content,
source_content_sha256, snapshot_sha256,
completeness="bounded_recorded_allergy_section")`.

The complete canonical allergy JSON is in `source_content`, preserving string
contents, numeric values, absent fields, empty strings, list order and original
qualifiers. It does not claim to preserve JSON formatting from the wire.
Recorded allergy timestamps have no documented fixed precision/timezone here;
they remain original strings. Optional JSON nulls are unsupported by the
published typed schema and are refused rather than guessed. NKDA missing,
false and true remain distinct. Patient vendor IDs remain private.

Source text exceeding 5,000 Unicode codepoints is refused as a whole. Both
scope/hash tampering and access loss during formatting withhold the snapshot.
The application saves this exact text through the existing immutable EHR
human-review custody and lost-response recovery, with three fresh
patient/exact-source/untrusted-source acknowledgments.

## Authorization, recovery and Chief

The shared EHR endpoint requires explicit `provider: athena`, `protocol: core`
and `core_patients` or `core_allergies`. Status, inspection, recovery and review
retain that discriminator. Independent immutable, revocable clinical grants bind
the OS external identity, connection generation, practice, chart department,
patient identity, workspace and current confirmed patient link. No Core account
bridge or schedule authorization is assumed.

Intent is saved before either provider GET, and no SQL transaction crosses
provider I/O. A separate encrypted `ehr-read:athena:core` journal retains an
unconfirmed request across reopening. Checking its saved result reuses the exact
request key and does not repeat the clinical read. Original clinical values stay
readable, including reactions, severity, criticality, dates, notes and exact int64
codes. Complete source text remains available for review.

The saved `ehr_read_source` is labeled **Athena: reviewed allergy records**.
Preparing Chief preserves existing directions and references the exact source
without sending a message. Current grants, patient links, bindings and feature
switches are checked for source release, model admission and settlement. Later
access loss withholds source text and derived replies while retaining history.

The integrated signed API/SQL/interface and model suite passes 35 cases,
including 14 adversarial direct-SQL cases, eight actual model/source cases and a
lost-response/reopening interface journey. The entire source remains unchanged
during that run. The UI passes 91 focused checks and both renderer type
configurations. Mac Studio passes 27 runtime cases and lint/types across 21
Python files. Reader and formatter qualification separately passes 52 cases.

The integrated fixture exposed a legacy formatter's 32-bit integer limit. An
Athena-specific canonicalizer now preserves signed-int64 spelling without
widening legacy behavior. Direct SQL checks also reject noncanonical private
timestamp spellings, malformed proofs and identities, and unsupported clinical
values. Browser/native release and phone installation are separate gates; these
results alone do not establish a delivered phone update.

## Remaining live gates

Live work additionally requires approved service-app/practice activation,
verified clinical endpoint access and patient/department correspondence,
production credential custody through a qualified integration and real vendor acceptance. The OS
must not start receiving Athena credentials because this mock adapter exists.
No external SDK code or dependency was copied or installed.
