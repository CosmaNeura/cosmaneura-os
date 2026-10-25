# Small-practice EHR connectors

Owner priority, October 25, 2026: **Atlas.md, Elation, Tebra and athenahealth**.
Other EHR candidates are parked. This work belongs to CosmaBot; no Scribe app,
repository, service, account or simulator is an implementation target.

The outcome is a person opening CosmaBot, choosing the practice's familiar EHR,
finding the right appointment/patient, reviewing useful information with Chief,
and understanding what was read or completed. Account setup and recovery must
be understandable without knowing API, OAuth, transport or infrastructure terms.
An EHR read must not be presented as permission to prescribe, sign a clinical
note, change a chart or book an appointment.

## Market evidence behind the priority

U.S. independent practices with no more than 20 providers are the intended
population. Public evidence does not supply a representative, exact-cutoff EHR
census for DPC, concierge or RRM/NFP. The following denominators stay separate.

| Selected vendor | 2025 DPC survey | RRM/NFP public clinic sample | Broader small-private-practice evidence |
| --- | --- | --- | --- |
| Atlas.md | 83/214 respondents, 38.8% | 2/20 practices, 10% | Not separately identifiable in the CDC public file |
| Elation | 53/214 respondents, 24.8% | 2/20 practices, 10% | Not separately identifiable in the CDC public file |
| Tebra | Not separately reported in the accessible tally | Not identified; nine core EHRs remain unknown | Not separately identifiable in the CDC public file |
| athenahealth | Not separately reported in the accessible tally | 5/20 practices, 25% | 9.8% of physicians in the defined 1–10-physician proxy; 10.7% among EHR users in that proxy |

The [My DPC Story 2025 survey](https://fliphtml5.com/fjnqg/cbim/2025_SUMMER_THE_TOOLKIT_MAGAZINE_PUBLISH/)
used a convenience audience, not a probability sample of practices. The five
published vendor cohorts total 196 of 214 participants; the remaining 18 cannot
be allocated to Tebra, athenahealth or another vendor. The strict size cutoff,
one-response-per-practice rule and U.S.-only filter were not all established.

The RRM/NFP figures are a purposive sample of 20 distinct practices, based on
official service pages, medical rosters and public vendor/portal evidence.
They are **sample frequencies, not national market shares**. Unknown EHRs remain
in the denominator. DPC/membership overlaps are retained, not counted as a
separate additive market. Example primary evidence includes
[Homestead's Atlas.md membership link](https://www.cosdoctor.com/),
[MorningStar's Elation portal](https://www.morningstarfhc.com/) and
[Holy Family's athenahealth portal](https://holyfamilyclinic.com/).
Portal identity does not establish the prescribing backend.

The broader estimate is a reproducible analysis of the
[2024 CDC NEHRS public-use data](https://www.cdc.gov/nchs/nehrs/documentation/index.html):
664 respondents with private solo/group setting, physician/group ownership and
1–10 physicians, using MAILWGT. It is physician-weighted, not practice-count
weighted. NPs/PAs are not counted in the size variable, and 11–50 physicians is
one combined band. The survey also excludes some specialties. This is a useful
proxy, not an exact estimate for all practices with 20 or fewer providers.
Its all-physician vendor results reproduce the published
[ONC 2024 totals](https://healthit.gov/data/data-briefs/office-based-physician-electronic-health-record-adoption-2008-2024/).

No defensible concierge-specific EHR percentages were found.
[MDVIP's athenaOne trainer role](https://www.mdvip.com/about-mdvip/careers/r13-ehr-trainer)
confirms use within affiliated practices, but gives no adoption denominator.
Neither that network's size nor hospital EHR market share is a substitute.

The reproducible calculation, complete clinic sample, source dates, exclusions
and survey sensitivity notes are retained outside this repository in the
dedicated CosmaBot connector workstream's `research/` directory. Estimates here
do not imply API availability, licensing or customer consent.

## Implementation and acceptance milestones

1. **Select and verify the vendor path.** Keep a source-linked capability map
   for the four selected EHRs. Distinguish practice API, patient-access FHIR,
   calendar/export import and prescribing. Pass when each offered action has a
   documented contract and an explicit unsupported state.
2. **Make reads reliable.** Use bounded responses, exact practice/account scope,
   current human authority, explicit pagination and useful failures. Preserve
   reviewed appointment identity and reject stale results after account change.
   Pass synthetic success, wrong-practice, expired/revoked access, malformed
   response, timeout, pagination and late-response cases.
3. **Finish the user's task.** Extend existing source selection and review
   ownership to bring a deliberately selected read into Chief. Preserve source
   provenance, cancellation and the same draft on return. No second queue,
   approval owner or automatic clinical write is introduced.
4. **Make setup understandable.** Show the EHR name, connected practice, one
   useful next action, last successful read and a plain recovery step. Keep
   technical configuration out of normal staff screens. A novice must connect
   or identify the specific missing setup, select the intended visit, recover
   from a failed read and return to Chief without losing work.
5. **Qualify a real vendor account.** Use an approved sandbox/test practice and
   invented records. Validate exact requests/responses, account isolation,
   revocation and recovery. Only then describe the integration as connected.
   A passing mocked adapter is not this gate.
6. **Add reviewed mutations separately.** Prescriptions, chart writes, document
   submission and scheduling changes require their own supported provider
   contract, exact human-reviewed payload, operation identity and reconciliation.
   Unknown outcomes must not create duplicate submissions.

## Verified paths and current limits

- **Athena:** the existing CosmaBot client reads a pinned practice schedule and
  reviews an exact visit link. The current repair retains selected dates during
  transient failures and rejects a direct link response for a different reviewed
  target. The status contract does not carry the original target, so independent
  target proof after status reconciliation is still a separate contract gap.
- **Elation:** use the documented practice REST client-credentials path and
  separately provisioned synthetic sandbox. Patient-access FHIR is read/search
  only. Partner production access is distinct from a practice's own developer
  subscription. Public documentation does not itself activate an account.
- **Tebra:** the current
  [SOAP integration guide](https://kareocustomertraining.s3.amazonaws.com/Help%20Center/Guides/Tebra%20API%20Integration%20Technical%20Guide.pdf)
  and public WSDL support practice-management reads. Customer-key access and
  administrator-backed credentials are required. Its
  [FHIR guide](https://www.tebra.com/wp-content/uploads/2025/05/Tebra-FHIR-API-User-Guide.pdf)
  describes a separate approval/activation path. Ambiguous documented security
  result semantics must be qualified before live use. Native eRx features do not
  establish an external prescription submission API.
- **Atlas.md:** public documentation establishes calendar subscriptions and
  exports, but a public practice API/authentication/sandbox contract has not
  been verified. Do not invent endpoints, automate the clinician UI, or label
  an imported calendar as a live EHR connection. Obtain the supported vendor
  integration contract before implementing live synchronization.

## Execution boundary

The mobile candidate remains on its existing branch. Connector work uses a
separate integration branch and a dedicated remote Mac directory. The remote
machine reports ARM64, macOS 27.0.1 and 8 GB memory; concurrency is bounded.
Portable Node/uv/pnpm and locked dependencies are installed only inside that
directory. Source and transferred candidate files have recorded SHA-256 hashes.

Initial changes address Athena visit correctness/date recovery, Microsoft
account-scoped email/calendar recovery and public-research query guidance.
Before/after tests are run against the selected source and then the candidate.
Source review also found a Microsoft late-status race; that repair belongs in
the same account-recovery slice. New EHR transports remain inactive until their
application integration and vendor-account gates pass. No live vendor reads,
messages, prescriptions, bookings, deployment or rollout is part of these tests.

## First implementation checkpoint

The dedicated remote Mac passed 351 focused Python tests (42 Athena, 187 public
research, 76 Elation and 46 Tebra) and 206 focused web tests (50 Athena and 156
Microsoft/research/shared recovery). Python lint, focused new-adapter Pyright,
the TypeScript build, production web build and isolated connector UX build pass.
The new Elation/Tebra test files were corrected to satisfy static type checking
and then both adapters were rechecked remotely: 122 tests passed.

Actual browser checks at 390px and 1280px also pass: independent Microsoft mail
and calendar results, one primary service action, no read just from changing
tabs, and Athena retry with retained dates and stale rows removed. These use
the real panels with explicitly invented service responses. They captured zero
screenshots, attempted no external requests and closed their owned browser/server.

This checkpoint does not complete the new EHR-to-Chief source lifecycle or live
vendor acceptance. Elation remains default-off and sandbox-only; Tebra is
synthetic-transport-only until its ambiguous provider contract is qualified.
The existing mobile candidate is separate: all nine GitHub CI jobs pass for
`1a4ebbf`, and Preview28 physical acceptance remains outstanding.
