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
  target. After a lost save reply, the mounted panel also compares the recovered
  result with the reviewed patient/visit or removal target before offering to
  open a notebook. A current projection may refresh details for the same IDs.
  A mismatched result remains unresolved without replaying the write. The wire
  contract does not carry the original target; durable target proof after panel
  remount remains a separate gap.
- **Elation:** the documented practice REST client-credentials path now has a
  default-off managed sandbox installation and a complete appointment-to-Chief
  source workflow. Local tests use invented responses; vendor access is not yet
  provisioned or qualified. Patient-access FHIR is a separate read/search path.
  Partner production access is distinct from a practice's developer subscription.
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

## Elation user-journey checkpoint

The second checkpoint connects the Elation adapter to actual signed application
routes, immutable PostgreSQL read/review records, encrypted local recovery and
the shared conversation session. With the build flag enabled, staff can open
**Review Elation appointment** directly from Chief's **Details → Notes and
sources** or the visit's **Sources**. Staff checks practice access, loads a
bounded appointment page, verifies the patient name/date of birth and intended
visit, reviews the details and saves the source. **Prepare Chief draft** keeps
existing Chief directions and the outgoing coworker's draft; it does not send a
message or call a model.

The joined mounted-UI test uses the actual RSA-signed API and PostgreSQL ledger.
It deliberately loses the successful read reply, resolves that exact request,
then verifies/saves the appointment and prepares Chief. It passes with six
synthetic provider requests, zero model admissions, the existing draft retained
and revoked source content withheld. Both 390px and 1280px browser layout checks
pass with 44px main controls and at most one primary next action. No screenshots
or external requests were used by those layout checks.

Independent source review reproduced a postcommit access race in both window
and patient verification responses. The service now reacquires current authority
and revalidates the saved result before disclosure. Read recovery never repeats
provider I/O. An explicitly requested fresh list can supersede an unconfirmed
read while retaining its old command; pending source saves cannot use that path.

This is an integrated **synthetic** workflow; vendor qualification is still
outstanding. The slice supports signed Clerk external identities, one page of
up to 25 appointments, exact appointment/patient verification and one reviewed
source. Patient search and additional-page commands remain outside the workflow.
Date inputs explicitly use the device timezone; returned appointment times show
the practice timezone.

## Managed sandbox setup checkpoint

The backend now loads exact private Elation secret references and a configured
test practice through the existing managed-service configuration. It remains off
unless both `WORKSPACE_EHR_READ_ENABLED` and `WORKSPACE_ELATION_SANDBOX_ENABLED`
are enabled; `VITE_EHR_READ_ENABLED` controls the renderer. Hosted and production
use remain unavailable. The original local-example runtime stays mock-only.

**Check Elation access** presents the configured practice. The intended human
then chooses **Use this practice’s Elation sandbox** to save an immutable local
installation. This step and **Check saved setup result** make no provider calls.
Only an explicit appointment read contacts the configured sandbox. Old setup
receipts cannot imply current access: changed secrets, account authority or
installation make them unavailable. Each read retains its original **Local
example** or **Elation sandbox — invented test data** provenance during recovery.

The managed read path shares a client request budget across processes using the
same database. Database tests cover setup/replay, credential changes, transport
substitution, bounded quota contention and the existing selected-source custody.
The final combined service/lifecycle run passes with unchanged source and clean
owned-database shutdown. An EHR fixture cleanup leak found by the joined tests
was repaired, after which the existing managed-service tests also pass together.
Shared UI tests pass for setup recovery, direct task entry, preserved Chief and
coworker drafts, and revoked-source withholding. These checks use invented
responses; they do not establish a successful vendor connection.

Evidence is retained outside the repository in the connector workstream's
`evidence/elation-sandbox-backend-review.json` and `evidence/ehr-task/freeze.json`.
The [sandbox access packet](ELATION_SANDBOX_ACCESS_REQUIREMENTS.md) gives the
operator's installation sequence and outstanding vendor acceptance checks.

Current repository history is immutable: it has no source/workspace deletion
endpoint, and the existing artifact-retention purge does not erase EHR snapshots.
Access revocation withholds selected content and dependent drafts; that is not
content erasure. An EHR retention/erasure policy and implementation are required
before storing real patient data. The rebuilt simulator client now passes the
native checks below; physical-device acceptance remains outstanding. Atlas.md
and Tebra activation limits above remain unchanged.

## Source drafts and rebuilt native checkpoint

The shared source actions now retain each coworker's own unsent text. Preparing
an email, calendar summary or received-fax passage from Follow-up restores
Chief's draft before adding the selected source; it no longer moves Follow-up's
text into Chief or clears a saved-note task. Source checks retain their existing
account, visit, revision and content commitments. Failed storage, a newer edit
or changed identity withholds the handoff. Gmail calls this **Prepare Chief
draft**. Outgoing fax PDF attachment is also one **Attach PDF** action, with
separate durable preparation/upload receipts and recovery without duplication.

Opening the Elation task preserves the conversation and its mounted recovery
state. Escape, another task choice or leaving the starting page cancels a
delayed opening. Back restores a visible control without opening the keyboard.
The final combined Mac Studio run passes 582 focused web tests, TypeScript and
both production/acceptance renderer builds at code commit `3b3c140`.

A fresh iOS simulator build of that same code passes app-hosted XCTest using
the actual shared components and invented local services. The native keyboard
changes the 390px-wide viewport from 844px to 397px; the 44-point Done control
dismisses it and restores the view. Chief's draft survives Details, appointment
review and a dropped source-save reply. Recovery saves one source, performs no
additional appointment read and sends no conversation. These are programmatic
UIKit/DOM checks, not physical touch or live authentication acceptance. Fax has
separate mounted/browser evidence and is not exercised by this native fixture.

Exact manifests and results are retained in the dedicated connector workstream:
`source-drafts-final-manifest.json`,
`evidence/mac-studio/source-drafts-final-20261025/receipt.json`, and
`native/final-native-review.json`. The native run produced zero attachments.
Routine lab screenshots, video and traces are now disabled; the persona driver
uses accessibility text. The original mobile checkout and phone Preview24 remain
unchanged. Physical iPhone qualification awaits available developer services;
Elation vendor acceptance still awaits the separate sandbox access below.

## Next step: obtain Elation sandbox access

The owner confirmed no sandbox is available and requested access requirements.
The [Elation sandbox access packet](ELATION_SANDBOX_ACCESS_REQUIREMENTS.md) is
prepared, with verified official onboarding links, three minimum read scopes,
test-practice requirements, the implemented private installation procedure and
an unsent request. A legal entity, business contact and authorized signer are
still needed for a submission. No vendor request, account creation or agreement
acceptance has occurred. Actual scoped token/resource responses, the vendor
sandbox-to-Chief journey and physical-device acceptance remain unverified.
