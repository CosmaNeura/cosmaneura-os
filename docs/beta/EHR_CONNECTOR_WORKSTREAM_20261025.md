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

- **Athena:** Chief and Connections share one account-owned visit task. An
  explicit review links the selected Athena appointment to an existing Core
  patient/visit. Exact link/removal request metadata survives reload and native
  backgrounding; recovery checks status without repeating the mutation. The
  fresh result must match the reviewed patient, visit, connection and account
  before opening a notebook. Unfinished work still blocks opening. The current
  slice is qualified with invented Core responses; live access remains untested.
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

## Tebra appointment workflow

The shared **Review an appointment** task now offers Elation and Tebra. Each
keeps its own encrypted recovery journal. Tebra first shows the returned
appointment window, then requires a last name and birth date for the selected
appointment. The patient identifier already attached to that appointment must
match the demographic result, and a fresh appointment read must still match
before review. The four confirmations save one source and **Prepare Chief
draft** retains Chief's existing directions. A window with too many rows asks
for a smaller date range after checking the original request's saved result.

This Tebra path uses an explicitly installed mock transport and invented
records. It does not install real Tebra credentials or imply a live connection.
Elation's existing request, response and source hashes remain compatible, and
rotating Elation sandbox access preserves Tebra's separately scoped sources.

At code commit `4f1c12d`, the signed Tebra and Elation app-to-database journeys
both pass. The Mac Studio passes 199 focused web tests, 98 Python tests
(including the calendar parser), TypeScript and both renderer builds. Browser
checks cover four layouts, including a short phone viewport and enlarged text.
A rebuilt iOS simulator client passes two app-hosted checks for the real Done
control, Tebra patient review, preserved Chief text and recovery after a lost
source-save response. The native run produced zero attachments. Its input is
programmatic UIKit/DOM with invented services; live vendor, physical touch and
native file-picker acceptance are not established.

Receipts are in the connector workstream's `CHECKPOINT-TEBRA.json`,
`evidence/tebra-joined-ui-final/results.json`,
`evidence/mac-studio/tebra-final-02-20261025/receipt.json`, and
`native/tebra-native-review.json`. The first Mac attempt's missing capture-client
dependencies were repaired in the test copy; the passing rerun used the same
source hashes. The original mobile checkout and phone Preview24 are unchanged.

## Calendar import and current-source checkpoint

From Chief's Details or Saved sources, **Import calendar file** accepts a bounded
`.ics` export with an explicit source, week and timezone. The user reviews one
event, confirms its summary, saves it and prepares a Chief draft without losing
existing directions. **View saved imports** reopens older imports for review or
withdrawal. Reviewed events cannot create duplicate summaries. **Stop using this
import** retains visit history while withholding the source from future work.

The raw calendar file, filename, feed URL and event UID are not kept. Atlas.md is
a source reported by the user; this flow does not connect to Atlas.md or verify
patient identity, availability or a booking. The parser distinguishes all-day
dates and timed events, checks daylight-saving transitions and rejects event
recurrence and unsupported ambiguous time definitions. Compatibility with an
actual Atlas-produced synthetic export remains unverified.

At code commit `45a4981`, the signed calendar, Elation and Tebra UI-to-database
journeys pass. The calendar journey recovers lost upload/save replies, revisits
the first of two imports and withdraws its sole reviewed source. Its server
records contain no raw file or omitted private calendar fields. Frozen backend
checks include 35 API and 44 database custody cases. The Mac Studio passes 409
web tests, 185 Python tests, TypeScript and both renderer builds with all 2,887
source hashes unchanged.

Review also fixed delayed-response races: older editor reads cannot replace a
fresh workspace, and preparing Chief checks the exact source again after the
last authorization. Calendar and EHR mutation receipts no longer republish an
older workspace after a fresh authorization. The affected fax recovery branch
now obtains its callback workspace after persistence. Withdrawn, deleted or
changed sources preserve the existing Chief draft.

A newly compiled iOS simulator client passes three app-hosted checks: real Done
keyboard behavior, Tebra review/recovery, and calendar lost-reply recovery with
Chief directions intact. The native run produces zero attachments. Four browser
layouts passed 270 text/geometry checks; those layout checks preceded the final
publication fixes, which are included in the final Mac/native runs. Native input
is programmatic UIKit/DOM; physical file-picker, touch, live sign-in and vendor
account acceptance are not established. Phone Preview24 and the original mobile
checkout remain unchanged.

Receipts are in `CHECKPOINT-CALENDAR.json`,
`evidence/calendar-final-joined-ui-02/results.json`,
`evidence/mac-studio/calendar-final-02-20261025/receipt.json`, and
`native/calendar-native-review.json` in the connector workstream. Earlier
snapshots and preflight results are retained separately.

## Athena shared task and native checkpoint

**Find or connect an Athena visit** is available from Chief and Connections.
Both entry points use one account-owned task and preserve Chief's exact draft
and Back focus. A confirmed link or removal is written to private saved-work
storage before submission. Its record retains bounded command/target metadata,
not patient names, tokens or schedule contents. Reload and native backgrounding
hide clinical details; a fresh exact-key status check verifies the original
patient/visit or removal target. Recovery never automatically repeats a write.

Notebook opening waits for the task's own read lock to clear, then uses the
existing unsaved-work checks. It opens a clean notebook and dismisses the task
even when that notebook was already current. Chief text and unrelated unfinished
work remain protected. An opening failure appears inside the active Athena
task; retrying it repeats only opening, not the visit-link change.

At code commit `1d37b1c`, local tests pass 291 cases; the Mac Studio passes 316
cases across 23 affected and adjacent files, both TypeScript checks and both
renderer builds. Five browser scenarios pass 317 text/geometry checks, including
lost link/removal replies, reload, small phone viewports, enlarged text, long
names and clean notebook opening. All 2,894 frozen source hashes remain stable.
The 970 unchanged Python/dependency inputs match the qualified calendar build;
its backend tests were not repeated for this frontend-only slice.

A fresh native simulator build passes four app-hosted checks. The Athena case
recovers a lost link reply after reload, then a lost removal reply after another
reload, using one mutation per operation and only exact status checks afterward.
Back restores the original Chief draft. Done/keyboard, Tebra review and calendar
import remain covered. The run has zero media attachments. These are programmatic
UIKit/DOM tests with invented services; live sign-in, vendor access, physical
touch, native file picking and physical-phone haptics remain unqualified.

Evidence is recorded in `CHECKPOINT-ATHENA.json`,
`evidence/athena-task/freeze.json`,
`evidence/mac-studio/athena-final-20261025/receipt.json`, and
`native/athena-native-review.json` in the connector workstream. The local UI
rehearsal's address and process are recorded in `LOCAL-REHEARSAL.json`. The phone
was on Preview24 at that checkpoint. No vendor messages, prescriptions, bookings or production
rollout occurred.

## Current phone and delivery limits

On October25 the owner requested a phone update. Preview29 was installed and
launched on the connected iPhone, with the latest qualified EHR/calendar screens
and `4d1de237` Messages draft-presence/pull-to-refresh changes. This was an
in-place update of `com.cosmasos.synthetic.w206`, preserving its signing and
storage identity. See `native/preview29-phone-summary.json` and the physical
Preview29 signing receipts in this workstream. No app data reset occurred.

Preview30 has since been installed in place, and the phone confirms build30.
It includes the `484e5b4` Outlook review-to-Chief workflow. The phone was locked
when CoreDevice attempted to launch it, so that launch was denied by iOS;
installation and version confirmation succeeded. The current browser rehearsal
also serves this build at its existing origin. Neither update reset storage.
See `CHECKPOINT-OUTLOOK.json` and `native/preview30-phone-summary.json`.

Outlook now reads a selected email through the existing delegated Mail.Read
permission, retains exact interrupted requests, and requires a current-visit
review before preparing Chief. The Chief draft survives Back and reopening.
The adapter does not fetch attachments or remote content; unsupported bodies
are explicitly unreviewable. Restored content and derived replies are withheld
when current connection or source access is lost. The final source passed 151
web tests on both Macs, 142 database checks, 44 adapter/custody checks, 18 desktop
proxy tests, 103 browser assertions and one native app-hosted Outlook journey.
The native test had no media attachments. Two final backend-file changes only
removed trailing whitespace; their before/after hashes are recorded alongside
the 142-check receipt. No real Microsoft account was connected.

These deliveries do not establish live vendor connections. Atlas.md currently
has generic calendar-file intake, not synchronization. Elation provides reviewed
patient/appointment context and the problem-list slice described below; Tebra
provides reviewed patient/appointment context. Athena provides the Core visit-link task.
None of the four has passed live vendor acceptance in this workstream.
Longitudinal chart history, labs, prescription relay/eRx
and clinical writeback remain missing engineering capabilities. They are not
merely credentials awaiting installation. The phone still uses invented data.
Elation medication-record reading is implemented in the slice below; this does
not provide a reconciled current medication list or medication writeback.

### Elation problem-list implementation

The next implemented slice reads a bounded problem list for the patient in an
already verified Elation appointment. The adapter rechecks both appointment and
patient before the clinical request. It preserves recorded Active, Controlled
or Resolved status and separate verification status, distinguishes empty,
partial and unknown coverage, and refuses oversized content instead of
truncating it. Diagnosis codes and synopsis text are outside this first slice.
The optional `system/problems.read` capability is separate from the existing
three-scope appointment profile and is disabled by default.

The user flow is **Review EHR records → Read problem list → Save reviewed
problem list → Prepare Chief draft**. The reviewed snapshot uses the existing
EHR source custody and encrypted Chief draft. It does not replace the saved
clinical note or send a message. An unresolved EHR request remains recoverable
after Back; active I/O still blocks departure until it settles.

The first complete backend run passed 109 checks, including the problem-list
source, real Chief admission/tool read/settlement, later access withdrawal, and
existing Elation/Tebra behavior. The adapter passed 220 tests, and the local
contract/configuration suite passed 58. The final mounted API/database run
passed six cases, including recovery of a lost problem response, review, Chief
draft preservation and later source withdrawal. It also qualified the final
host-permission status correction. The web suite passed 121 cases, and Chromium
passed 218 checks across phone, enlarged-text and desktop scenarios. Native
qualification and the next phone package are separate acceptance steps, with
receipts recorded in the workstream when completed. No Elation sandbox or live
practice was used; the access packet describes the additional clinical scope
required.

The committed Elation slice is `3a408775`. Its single native app-hosted journey
passes with UIKit Done, Back and the Chief draft preserved, and no image
attachments. Mac Studio independently passes 142 web cases, 220 adapter cases
and both typechecks against all 2,930 unchanged source files. Preview31 is
signed and archived, but CoreDevice lost the paired phone's developer tunnel
before installation; Preview30 remains the last confirmed installed version.
The current local browser rehearsal serves the qualified Elation build. See
`CHECKPOINT-ELATION-PROBLEMS.json` and `native/elation-problems-native-review.json`.

The subsequent `1f950824` mobile slice puts saved EHR sources directly in Chief's
conversation, with a label, saved time and exact-source review action. Back
preserves the draft, focus and reading position. It passes 107 focused web
checks locally and on Mac Studio, 86 narrow-phone/enlarged-text Chromium checks,
both typechecks and one native hosted journey with zero media attachments.
Preview32 is signed, archived and served in the local browser rehearsal.
The paired phone still reports its developer tunnel unavailable; Preview30 is
the last confirmed installed version. See `CHECKPOINT-EHR-MATERIAL.json`.

Preview33 (`1301827`) adds the reviewed Outlook source card and a verified
Research-packet-to-Chief draft continuation. It passes 311 focused Mac cases,
both typechecks, 76 real-browser assertions and two native hosted journeys,
with zero images. The signed package and verified archive are ready, and the
local rehearsal serves this renderer. The phone's developer tunnel is still
unavailable; Preview30 remains the last confirmed installation. The delivery
receipt and the closed-storage draft uncertainty are documented in
`CHECKPOINT-OUTLOOK-RESEARCH.json` and the Chief-first Messages implementation
record. These are new usable data flows, not live vendor acceptance.

### Elation medication-record implementation

From the same verified Elation appointment, staff can choose **Read medication
records**, review the recorded directions, dates and coverage, save the
reviewed source, and prepare Chief without replacing its existing draft. The
saved record appears in Chief's existing EHR source card. Switching between
problems and medications retains the verified appointment but requires a fresh
review of the selected snapshot. Interrupted requests retain their exact
recovery identity rather than issuing another clinical read.

The separate `system/medications.read` scope and host/installation opt-ins are
disabled by default. One page contains at most 25 records, and the entire saved
source must fit 5,000 characters; oversized instructions or packets are refused
without truncation. Historical and unfinished records remain visible as such.
Missing dates, explicit null dates and recorded dates stay distinct, without
inferring current use, reconciliation, dispensing or transmission.

Final joined verification passed 32 medication database cases and the three
actual signed API/database UI journeys (appointment, problems and medications).
Four Chief model/settlement cases passed separately after correcting a test's
assumption about the existing marked-excerpt delivery. The scripted model reads
the exact full saved source before answering; current source access is checked
during that read and settlement. No production change was needed for those test
corrections. Earlier failed receipts remain preserved. Browser, Mac and native
qualification and physical installation are recorded separately when complete.

Commit `4f216d8` subsequently passed all seven browser scenarios, one native
hosted medication journey with 44px Done and zero attachments, and independent
Mac Studio verification (502 Python cases, 331 web cases, lint and both type
configurations). All 2,944 source hashes stayed unchanged. Preview34 is installed
and launched on the phone; CoreDevice independently reports build34. The local
rehearsal serves the same qualified source at its existing origin. The update
used the existing app identity and performed no uninstall or storage reset.
Physical touch, haptics, VoiceOver and draft contents across the update remain
unverified. See `CHECKPOINT-ELATION-MEDICATIONS.json` and
`native/preview34-phone-summary.json` in the connector workstream.

## Elation sandbox access

The owner confirmed no sandbox is available and requested access requirements.
The [Elation sandbox access packet](ELATION_SANDBOX_ACCESS_REQUIREMENTS.md) is
prepared, with verified official onboarding links, three minimum read scopes,
test-practice requirements, the implemented private installation procedure and
an unsent request. A legal entity, business contact and authorized signer are
still needed for a submission. No vendor request, account creation or agreement
acceptance has occurred. Actual scoped token/resource responses, the vendor
sandbox-to-Chief journey and physical-device acceptance remain unverified.
