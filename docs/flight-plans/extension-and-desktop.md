# Extension and desktop: V0 flight plan

Status: proposed r5; docs only; draft PR #401; implementation requires John's approval of this plan and its prerequisites.
#400 merged 19 Nov 2026 at b18af3b128e8b1db6fbd03abc07d836944efafc1.
Evidence baseline: `5d8e2f53` on `main`, inspected November 17, 2026; prerequisite citations re-checked at the #400 merge below.
Decision evidence: `DL-20261117-01` and its confirmation resolution
`DL-20261117-02` are recorded in [owner-decision PR #400](https://github.com/CosmaNeura/cosmaneura-os/pull/400),
[decision log at the merge](https://github.com/CosmaNeura/cosmaneura-os/blob/b18af3b128e8b1db6fbd03abc07d836944efafc1/docs/DECISION_LOG.md#L436).
**OPEN (citation changed at merge):** the decision-log status/notes and AGENTS/browser-automation wording differ from the previously cited `d965d3595a20bbbcc7fd2479ccc581324489253b` text. Rows 1 and 3 record the changed citations for review; no new decision is inferred here.
Until rows 1 and 3 are reviewed and closed, nothing here permits agent or builder browser work and no V0 build PR starts.
This PR does not copy or modify the three decision documents.
Nothing here activates an external capability, installs software, changes
credentials, or authorizes a merge. All development and qualification data is
invented. This plan remains on the existing draft PR #401, pending review.
Merge ≠ promote ≠ production publish ≠ store submission; the human still
clicks deploy. Existing live users keep access and their current sign-in: no
new agreement, practice, onboarding, billing, re-join or re-acceptance step.

## 1. Outcome and bounds

V0 lets an authorized practice member ask about an explicitly registered
computer and receive a dated answer from its permitted EHR page observations.
A packaged browser extension reads a small set of supported pages; the desktop
app supplies device identity, credential custody, status and the cloud link.
An extension-only installation can read supported pages without a desktop app,
with narrower availability and security guarantees. Both retain the Box, ports and work-surface boundaries; F-8 availability is
runtime-dependent and requires the section 9 prerequisites. Neither is a general remote desktop.

Start with one synthetic system and one screen (appointment list), then a
patient-context screen. Read only what is already loaded. V0 does not click,
type, navigate, log in, dismiss prompts, prescribe, sign, submit, or prevent
an EMR from logging out. A screen pack cannot introduce those abilities.
Native EMR windows, canvas-only applications, inaccessible frames and remote
desktop pixels are unsupported by a DOM reader. Report that limit rather than
adding OCR or OS accessibility control implicitly.

**OPEN-JOHN Thursday, November 19, 2026: recording inside OS versus the still-deferred
“Rebuilding the existing Scribe inside OS.”** Is V0-8 a new OS recording path,
or does it conflict with that deferral? No default or implementation resolution
is assigned here. BLOCKED: no V0-8 PR, including fake-only, until John answers the recording/Scribe boundary.
Independent recording-to-note is a separate gated proposal.
DL-20261117-02 clarifies (relayed via CoS, 17 Nov, time not recorded): “Yes, maybe for initial beta we rely on legacy but
going forward we need independent recording and notes.” Record that beta
exception honestly; do not label a Core-backed note independent. Scribe stays
a separate product sharing the recorder, and new Scribe sign-ups use CosmaBot
identity per DL-20261117-01 (#400 merged; see row 1 citation check); not implemented; current Scribe sign-up unchanged in V0.
Plan the shared recorder interface here; no live identity change.
Do not make page reading depend on transcription or silently send audio to
Track A. Platform-specific device/credential/capture code stays behind interfaces
from the first Mac slice. Windows work (V0-W) starts no earlier than week three and only after John's Windows-scope answer; no Windows PR before it.

### John's answers: November 17, 2:23pm ET via CoS

(a) (relayed via CoS, 17 Nov 2:23pm ET) "A doctor should be able to see what is on his employees emr screen if it's a different login. We get user auth issues with larger groups in different departments but for small practices that isn't an issue, especially for V0, 1 and 2."

John's decisions (relayed via CoS):

These quotes were relayed via CoS and are not verified or recorded in a decision log. Every status that rests on them is provisional until they are.

- viewing roles — John, relayed via CoS, 19 Nov 9:28am ET: "Doctor or practice owner".
- practice-size bound — **OPEN-JOHN** — John, relayed via CoS, 19 Nov 9:28am ET: "Practices with 5 or fewer clinicians".

### John's 7:27pm answers (relayed via CoS)

John's literal words (in-app chat, 19 Nov 2026 7:27pm ET, relayed via CoS): "Run R1, run 995 r12, run 401 r5, A A yes yes"
CoS's mapping of "A A yes yes" to its 6:38pm card (CoS relay, not John's wording):

#### CoS card, 6:38pm ET (as shown to John)

Source: CoS relay, in-app chat to John, 19 Nov 2026 6:38pm ET (23:38Z). (Fable called it the 6:37pm card; record it as 6:38pm ET.)
"**Your yeses, one line:** \"run 995 r12, run 401 r5, A A yes yes\" plus a yes or no on Q5.
- **401 r5** is a docs-only Codex run that fixes Fable's last notes on the CosmaBot screen-viewing plan.
- **Q1:** at 10:51 you said \"doctor or owner only,\" and at 1:43 you picked B, where staff can start a session after a doctor or owner turns viewing on. Should the plan follow **A)** your 1:43 answer (my pick) or **B)** doctor or owner only?
- **Q2:** who can renew a session? **A)** the same people who can start one (my pick), or **B)** doctor or owner only. **Q3:** \"turning viewing on\" happens per computer in settings, it starts nothing by itself, and turning it off ends any session. Yes? **Q4:** until you define practice size, viewing someone else's screen stays off except for computers you name. Yes? **Q5:** can a practice owner who isn't a doctor view an employee's screen? Your call."
John's reply, verbatim, 7:27pm ET: "Run R1, run 995 r12, run 401 r5, A A yes yes". Q5 reply, 7:04pm ET: "Q5 yes".
Note to record with it: Q1's "A" here means "follow the 1:43 answer", which was option B on the 1:43pm card.

CoS mapping (relay, not John's wording):

- Q1 = A: follow his 1:43pm H1 B: a doctor or owner turns viewing on, then staff can start it.
- Q2 = A: renew = same as start.
- Q3 = yes: the proposed "turns viewing on" default, as written.
- Q4 = yes: the proposed interim size rule, as written.
- Q5 was "yes" at 7:04pm ET (viewing roles, step 6).

Card (CoS, in-app, as shown to John): "In the screen-viewing plan, who starts a session when the computer belongs to a staff member, like a nurse or the front desk? A) The doctor or owner starts it in person, at the staff member's computer. B) The staff member starts it on their own computer, but only after a doctor or owner has switched it on for them. C) For now, only a doctor's or owner's own computer can be watched, with no staff computers. Until you pick, only a doctor or owner can start a session."
John's literal reply: "B" (relayed via CoS, in-app chat, 19 Nov 2026 1:43pm ET).
The earlier one-line summary "'B' = staff can start..." is the CoS relay, not the card's wording.

For V0, V1 and V2 only, the 17 Nov doctor rule in (a) permits a granted doctor to view an employee's loaded EMR screen under a different EMR login. That quote stands (relayed via CoS, 17 Nov 2:23pm ET). **DECIDED (viewing roles, provisional):** a practice owner who is not a doctor may view an employee's different-login screen, under the same grants and session bounds. Question (CoS, in-app): "can a practice owner who isn't a doctor view an employee's different-login screen?"; John's literal reply: "Q5 yes" (relayed via CoS, in-app chat, 19 Nov 2026 7:04pm ET). This decision is limited to that question. This does not transfer the employee's identity or private grants, grant agent impersonation, or permit EMR control. Larger practices and multi-department groups are out of scope and later.

**OPEN-JOHN (practice size):** "Practices with 5 or fewer clinicians" (relayed via CoS, 19 Nov 9:28am ET). "Clinician" and the source of the count are not yet defined by John. The count is never derived from seat count, plan, pricing tier or member roles. **DECIDED interim (John Q4 "yes", relayed via CoS 7:27pm ET; plan's wording):** until John defines both, different-login viewing is off for every Box except Boxes John names individually; own-session viewing is unaffected. Nobody has different-login viewing today, so this limits no existing user.

Require a visible **“being observed”** indicator on the observed computer,
a staff notice the practice gives employees, explicit human session enablement,
and a bounded session with visible expiry and stop control. **Proposed V0 default
to qualify: 15 minutes**, then stop until a human explicitly renews; this is not
a locked measurement. Stop on revocation, sign-out, lock, expiry or nobody-present
state. Cannot establish human presence/lock state? Refuse new reads; the
extension-only mode needs an explicit foreground/presence check before admission.

A session is started and renewed only at the observed computer by the person signed into it; whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. Remote start is not proposed. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it.
**"Turns viewing on", V0 (DECIDED: John Q3 "yes", relayed via CoS 7:27pm ET; plan's wording):** per observed computer, by a doctor or practice owner in existing settings; it starts no session and reads nothing; either role can turn it off, which ends any running session.

Notice wording and employee-monitoring law sufficiency are unreviewed by counsel.

**Proposed V0 human-present signal to qualify:** OS input idle time no greater
than 60 seconds, OS unlocked and the observed EMR tab foreground/visible, checked
before every read. This indicates recent input, not proof of who is present;
collect only current idle duration/state, never keys or an activity history.
Crossing the proposed threshold ends the viewing session until a human returns
and explicitly starts/renews it. The 60 seconds is unmeasured, not locked.
For extension-only, qualify browser idle/lock status plus recent trusted human
input and foreground visibility; absent/unsupported/unknown status refuses
admission. Page-script events and heartbeats cannot establish presence.
This proposal supplies refusal criteria, not permission for unattended reading.

**OPEN-JOHN Thursday, November 19, 2026: locked or unattended / nobody-present reads.** Answer (a)
did not decide these. Default off until he answers; `background_page_reads_enabled`
/ V0-7 remains off. Idle-logout measurement does not require enabling these reads.

(b) (relayed via CoS, 17 Nov 2:23pm ET) "We could use the existing Athena sandbox to test, maybe? I'm sure there are others out there we'll find."

Week 2 targets the athenahealth sandbox with invented patients only. Confirmation
is still needed that it offers a browser login with an idle timeout, along with
access and terms before running that test. This answer is a
suggested target, not proof of access or permission. Other vendor sandboxes come
later. If unavailable, report those cells **unrun**; no fabricated results or real
patient charts.

(c) (relayed via CoS, 17 Nov 2:23pm ET) "One login per user should sync across the 3 major features of phone app, desktop app and browser plugin."

Answer (c) retains shared CosmaBot identity and separate product/Box authority;
the r2 reading of a separate sign-in on each device is replaced by answer (1).

### John's answers: November 17, 3:07pm ET via CoS

(1) (relayed via CoS, 17 Nov 3:07pm ET) "One login means you sign in once and all three apps unlock automatically."

The user signs in once and the phone app, desktop app and browser extension all
unlock automatically: sign-in-once single sign-on (SSO), not three sign-ins to
one account. This is the required outcome, **not implemented or verified today**.
Section 4 separates the existing native contract from the missing SSO work.
V0-5 and all shared-identity/SSO work are BLOCKED on John's yes to the exact Clerk settings list that section 4's discovery step will produce (no such list exists yet). Changes must be additive; existing users
keep signing in the same way until that yes. Codex changes no live or staging Clerk setting and creates no secrets.

(2) (relayed via CoS, 17 Nov 3:07pm ET) "Every practice member probably has their own EMR login. We don't obviously control that but that user access control is outside the realm of HIPAA for our purposes. So a medical coder who has an EMR login can start or renew a viewing session." Answer (2)'s start line is replaced by H1 B (John Q1 "A", 7:27pm via CoS); who may renew is the same as who may start (Q2 "A"). The rest of answer (2) is unchanged.

N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule. The observed person is the CosmaBot user who
starts that own session. The 17 Nov V0–V2 rule permits a granted doctor, and the 19 Nov Q5 answer (7:04pm ET, relayed via CoS; section 1) permits a granted practice owner
to view an employee's different-login screen for small practices under the **OPEN-JOHN** practice-size rule above; different-login viewing is off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). Starting/renewing remains explicit human action at the observed
computer, with current practice authority, the visible “being observed” indicator,
the practice's staff notice, stop control and bounded expiry. The 15-minute bound
above remains a **proposed V0 default to qualify**. Agents never start, renew or
widen a session themselves.

John's stated product decision (relayed via CoS, 17 Nov 3:07pm ET): "We don't obviously control that but that user access control is outside the realm of HIPAA for our purposes."
This statement has not been checked against the BAA or by counsel. It is not a
compliance, legal or HIPAA-coverage finding; BAA 2.3 coverage of EMR page
observations remains **unverified**. No BAA change or new acceptance step follows.

N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET)** (provisional per section 11). Question (CoS, in-app): "But your 9:28 card this morning said only a doctor or practice owner can start one. Which should the plan say? Reply 'any member with an EMR login' or 'doctor or owner only'." John's answer: "Doctor or owner only for now". Label: relayed via CoS, 19 Nov 10:51am ET. See the Q1–Q2 resolution and source block in section 1. This record does not decide different-login viewing.

## 2. Existing implementation to reuse

Paths below are existing source at the evidence baseline. Reuse means retain
the boundary or extend it in a later reviewed slice; it does not imply the
new device/extension protocol already exists. Historical Scribe filenames
alone do not demonstrate a runtime dependency on the legacy service.

| Area | Existing files and concrete evidence | Reuse and limits |
| --- | --- | --- |
| Desktop shell | `clients/desktop/main-authenticated.mjs`, `clients/desktop/auth-preload.cjs`, `clients/desktop/scribe-security.mjs`, `clients/desktop/capture-content-security.mjs`; `scripts/prepare-desktop-synthetic.py`, `scripts/package-desktop-release.mjs` | Electron main/preload boundary, isolated app origin, packaged renderer, permission restrictions and release composition. Add a narrow native-messaging host; do not expose Electron IPC or open a general loopback API to pages. |
| Desktop transport and practice selection | `clients/desktop/workspace-auth-proxy.mjs`, `clients/desktop/hosted-auth-http.mjs`, `clients/desktop/practice-session.mjs`, `clients/desktop/practice-ipc.mjs`, `clients/desktop/practice-infos-config.mjs`, `clients/desktop/practice-https-wire.mjs` | Current session/practice fences and explicit origin selection. The practice HTTPS wire is enrollment transport, not an existing computer-command channel. |
| Native Mac audio | `clients/desktop/native-audio/Package.swift`, `clients/desktop/native-audio/Sources/ScribeDesktopAudio/MacMeetingAudio.swift`, `clients/desktop/native-audio/Sources/ScribeDesktopAudio/NativeCaptureProcessFence.swift`, `clients/desktop/native-audio/Sources/ScribeDesktopAudioHelper/Main.swift`; `clients/desktop/recorder/provider-recorder.ts`, `clients/desktop/recorder/provider-recorder-ipc.ts`, `clients/desktop/recorder/durable-record-store.ts` | Mac audio/process isolation, explicit human start/window selection, consent/lease and durable recording recovery. The Swift package targets macOS 14.2; this is not a Windows audio implementation or a background page reader. |
| Phone/native encrypted recording | `clients/apple/native-auth/Bridge/NativeProviderRecordingService.swift`, `clients/apple/native-auth/Bridge/NativeProviderRecordingRuntime.swift`; `clients/capture/native-recording-pcm/Sources/CosmaneuraNativeRecordingPCM/NativeEncryptedPCMRecorder.swift`, `clients/capture/native-recording/Sources/CosmaneuraNativeRecording/NativeRecordingEncryption.swift`, `clients/capture/native-configured/secure-queue/ios/Sources/CosmaneuraSecureQueue/NativeRecordingQueueStore.swift` | Existing native PCM and encrypted local custody. Device capture transport buffers are not a new user-facing work queue. |
| Local private recording | `web/src/private-recording-runtime.ts`, `web/src/private-recording-desktop.ts`, `web/src/private-recording-ledger.ts`; `src/cosmas_os/api/private_recording_routes.py`, `src/cosmas_os/application/private_recording.py`, `src/cosmas_os/private_recording_models.py` | Record locally, attach metadata, finish and bind a saved recording. Server metadata explicitly reports no upstream admission, audio upload or transcription. |
| Sign-in | `clients/desktop/auth-session.mjs`, `clients/desktop/auth-helper-client.mjs`, `clients/desktop/spawn-auth-helper.mjs`, `clients/desktop/auth-ipc.mjs`; `clients/apple/native-auth/Desktop/main.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/KeychainAccessBlock.swift`; `src/cosmas_os/api/auth.py` | Shared identity, separate product authority. Desktop auth helper throws unless `darwin`; release packaging accepts only `OSX`. Windows sign-in and packaging are new work. Tokens stay out of desktop preload/renderer; session revisions fence requests. Keychain background access must fail without summoning authentication UI. Do not change shipped identity or Keychain names. |
| Queue and operation ledger | `src/cosmas_os/models.py` (`Ticket`, `ActionRevision`, `Decision`, `Operation`); `src/cosmas_os/application/services.py` (`decide`, `edit_revision`, `execute_operation`, `reconcile_unknown`, `list_queue`); `src/cosmas_os/worker/tasks.py` | F-8 immutable revisions, exact approval and unique operation per revision; Postgres intent and retry/reconciliation. Existing chase creation is domain-specific: add the appropriate read-review work producer, not a call that pretends a page read is an insurance chase. |
| EHR observations and custody | `src/cosmas_os/ports/ehr_reads.py`, `src/cosmas_os/ports/tebra_fhir_ehr.py`, `src/cosmas_os/ports/athena_allergy_ehr.py`, `src/cosmas_os/ports/athena_medication_ehr.py`, `src/cosmas_os/ports/elation_lab_ehr.py`; `src/cosmas_os/application/ehr_reads.py`, `src/cosmas_os/ehr_read_models.py`, `src/cosmas_os/ehr_read_audit.py`, `src/cosmas_os/api/ehr_read_routes.py` | Bounded observations, private/public projections, hashes, current authorization and explicit reviewed-source selection. Existing closed shapes identify particular providers/protocols and synthetic modes; a browser observation needs an additive, accurately named shape. |
| EHR adapters | `src/cosmas_os/adapters/ehr_read_runtime.py`, `src/cosmas_os/adapters/elation_read_runtime.py`, `src/cosmas_os/adapters/tebra_fhir_read_runtime.py`; `src/cosmas_os/plugins/ehr_fhir/client.py`; `src/cosmas_os/ports/athena_fhir_ehr.py`, `src/cosmas_os/ports/elation_fhir_ehr.py` | Explicit runtime dispatch and read-only FHIR client. Preview adapter exports are not proof that a supported browser adapter or production route is already wired. Prefer authorized APIs for data absent from an open page. |
| Connections | `src/cosmas_os/api/connection_catalog.py`, `src/cosmas_os/api/core_connection_routes.py`, `src/cosmas_os/application/core_connection.py`, `src/cosmas_os/ports/vendor_connectors.py`; `clients/desktop/connector-api-routes.mjs`; `web/src/SettingsHub.tsx`, `web/src/connection-setup-flow.tsx`, `web/src/connection-operation-health.ts` | Existing connection inventory/readiness UX and authority bindings. A registered computer is an endpoint inside its Box, not a new Org, identity provider or broad portal connection. |
| Shared phone/desktop work | `web/src/session/recording.ts`, `web/src/session/presentation.ts`, `web/src/MessagesPresentation.tsx`, `web/src/WorkspaceShell.tsx`; `src/cosmas_os/application/model_work.py`, `src/cosmas_os/application/handoffs.py`, `src/cosmas_os/application/scribe_source.py` | Shared session/action/conversation projections and reviewed source context. Reuse presentations; do not add a second chat/task surface or assume private notebook sources become practice-wide. |

Useful existing regression evidence includes
`clients/desktop/auth-session.test.mjs`,
`clients/desktop/connector-api-routes.ehr-read.test.mjs`,
`tests/unit/test_desktop_owned_boundary.py`,
`tests/unit/test_native_recording_service.py`,
`tests/integration/test_private_recordings.py`,
`tests/integration/test_saved_recording_transcription.py`,
`tests/integration/test_ehr_read_custody.py`,
`tests/integration/test_ehr_read_lifecycle.py`, and
`tests/integration/test_model_worker_process_recovery.py`.
These are source evidence, not test runs performed for this planning PR.

## 3. Does independent recording-to-note already exist?

**No complete, implemented recording-to-note path independent of the legacy
platform was found.** Independent local recording and manual note work exist;
that is not evidence of independent audio transcription and note generation.

Evidence chain:

1. `web/src/private-recording-desktop.ts` wraps a local microphone source with
   a main-process permit and explicit consent. It does not transcribe audio.
2. `src/cosmas_os/application/private_recording.py:view` returns
   `custody: local_device_metadata`, `upstream_capture_admitted: false`,
   `audio_uploaded: false`, and `transcription_started: false`.
3. `web/src/saved-recording-runtime.ts` handles later admission/upload and
   transcription status through the existing capture API. Metadata attachment
   and finish are distinct from that later transfer.
4. `src/cosmas_os/config.py` declares `workspace_capture_backend` as
   `Literal["disabled", "core"]`, default `disabled`.
   `src/cosmas_os/api/app.py:_capture_connection` builds a
   `HttpCoreCaptureAdmission` with `core_capture_origin` and workload identity
   when capture is available.
5. `src/cosmas_os/adapters/core_capture_connection.py:PATH_LIMITS` includes
   `/service/v1/agent/scribe/capture-bindings/resolve`, `capture-admissions`,
   `capture-operations`, and `capture-notes`.
   `src/cosmas_os/adapters/core_capture_admission.py` obtains transcript and
   draft receipts from this first-party Core facade.
6. `src/cosmas_os/application/scribe_source.py` accepts an explicitly reviewed
   transcript snapshot for team context; it is not an audio-to-text engine.
   `tests/unit/test_cosmabot_recording_vendor_isolation.py` excludes
   AssemblyAI/Recall wiring from the OS path; vendor exclusion does not prove
   that independent STT exists.

The smallest independent path reuses local capture/custody, defines an
OS-owned transcription port with a local fake first, persists an immutable
transcript, then produces a reviewed draft through existing work/notes
boundaries. Clinical note drafting and reasoning stay in the cloud. Model/provider
selection and external audio processing activation are separate prerequisites.
No Track A source import, database, account mount or deployment change belongs
in the independent slice. Existing Core paths remain explicit and unchanged;
a failed independent path cannot fall back to them.

## 4. Pairing and extension-only fallback

### Preferred: extension paired to the desktop app

Use packaged Chromium/Edge extension code and an OS native-messaging host
shipped with the desktop app but **registered only when
`desktop_extension_pairing_enabled` is on**, never at every desktop install.
Disabling pairing removes/refuses host registration without changing app sign-in. Allow only the exact signed/released extension
IDs once qualified; store approval and signed extension IDs are unverified,
not identifiers already obtained. Keep the host a bounded relay to the owned main process, with strict
message schemas and no shell, filesystem, arbitrary URL or generic IPC access.
Native-messaging availability across browsers is a qualification item.

An authorized human initiates pairing in the app and extension. The backend
issues a single-use, short-lived challenge bound to Box, human, installation,
extension ID, browser profile and device public key. Display the same short
verification code at both ends; finish only with explicit confirmation on the
desktop. Pin the paired profile/connection and a pairing generation. A short
display code is not the authentication secret. Reject replay, wrong profiles,
expired challenges and cross-Box substitutions.

Desktop credentials remain in native custody. Give the extension only a narrow
read capability, never the human's Clerk bearer, refresh token, EMR cookie or
cloud model key. Revalidate Box grants, installation and pairing generation on
every accepted observation and requested read. Sign out, membership removal,
connection disable, unpair, profile change and replacement revoke the binding.
Already observed history follows the proposed section 6 retention rule and current access checks; it does
not disappear merely because the endpoint is removed.

Security trade-off: native custody and device status reduce browser-held cloud
authority, but installing a native host adds a privileged local boundary and
packaging surface. A compromised permitted page can still falsify observed
content. The extension is not attestation that the EHR record is correct. Use
exact host permissions, an isolated content script and authenticated extension
messages; reject page-origin requests to pair or invoke the host. Treat all
page text as untrusted evidence, including apparent instructions to an agent.

### Fallback: extension without the desktop app

An explicit installation mode, not an automatic downgrade after pairing fails.
Use the same Clerk identity through the sign-in-once SSO slice below; a separate
extension sign-in does not satisfy (1). A supported extension session-establishment
flow (authorization code/PKCE only where supported) is still unverified; backend grants remain separate
from identity membership. Enroll a browser-profile endpoint under the Box with
an extension-only capability. Use short-lived read-scoped access tokens held
outside the page/content script; persist no long-lived human bearer or EMR
credentials. Require reauthentication when renewal cannot be done safely.
Validate extension ID, exact cloud origin, profile binding and current grants.

The extension sends minimized observations directly to the OS backend over
HTTPS. There is no local daemon, raw desktop status, native audio, wake control,
or assurance that it stays available after the browser exits. Service-worker
suspension and browser tab discard may delay reads. It has no native lock signal. Until a browser idle/lock API is qualified per section 1 it reports `unknown`, and unknown refuses reads; extension-only reads are therefore off until that qualification passes.

Security trade-off: fewer native components and easier installation, but cloud
read authority exists in a browser profile with weaker custody than native
Keychain/Windows credential storage. Profile theft and malicious extension
updates matter more. Constrain permissions, token lifetime, observation scope
and storage; clear session credentials on sign-out. A compromised browser can
forge page observations in either mode. Neither mode uploads cookies or
credential-store contents. No automatic mode change transfers permissions.

### Additive sign-in-once SSO / Clerk approval checklist (BLOCKED)

Read evidence: `docs/NATIVE_SIGNIN_ACCOUNT_CONTRACT.md`,
`clients/desktop/auth-session.mjs`, `clients/desktop/auth-helper-client.mjs`,
`clients/desktop/spawn-auth-helper.mjs`, `clients/apple/native-auth/Desktop/main.swift`,
`clients/apple/native-auth/Bridge/CosmasWorkspaceAuthPlugin.swift`,
`clients/apple/native-auth/Sources/CosmasNativeAuth/NativeWorkspaceAuth.swift`,
`clients/apple/native-auth/Sources/CosmasNativeAuth/NativeTokenPolicy.swift`,
`clients/apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift`,
`clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift`,
and `src/cosmas_os/api/auth.py`. Phone and Mac use Clerk SDK hosted auth with
an ephemeral browser, `sharedSessionSync == nil`, native credential custody and
fresh session tokens. They do not currently unlock each other automatically.

**Existing session contract.** Both clients call `startHostedAuth` with
`prefersEphemeralWebBrowserSession: true`. Fixed-workspace sign-in checks
membership and calls `setActive(sessionId:organizationId:)` before workspace
access; account-before-practice sign-in first establishes account identity, then
uses the contract's checked Org activation/profile handoff for workspace access.
`NativeWorkspaceAuth` persists an access block before sign-in/sign-out, checks
identity and session revision before and after token fetch, and retains the block
on failed or interrupted logout. Desktop adds its main-process `logout_pending`
then `needs_login` fence; the iOS plugin uses the same native coordinator.
`freshToken` uses `getToken(skipCache: true)`; a restored SDK credential alone
cannot undo a durable logout block. `clearAccountCredentials` signs out then
clears native Clerk credentials after account deletion. None of this supplies
cross-device session establishment or all-app logout today.

For enrolled practices, retain `/enrollment/v1/native/config`, `status`, optional
practice selection and nonce-bound `workspace-profile`, followed by checked Org
activation and explicit Chief opening. The profile contains **no bearer token**;
it cannot unlock a second app. Native enrollment calls use exact `Origin`
`capacitor://localhost` (phone) / `app://cosmas` (desktop) against the pinned
account API, production `https://enrollment-api.cosmas.ai`. Practice APIs/web
origins come from the qualified profile, not a page or extension message.
Native Clerk frontend SDK calls themselves do not add that browser `Origin`
header (`prepareFrontendRequest` rejects the conflict); these are different hops.

Production enrollment requires exact pinned `iss`, live `sid`, required times,
non-empty exact scalar configured `aud`, and native `azp` absent or equal to its
native request origin. Browser sessions require an approved exact `azp`; an
extension cannot borrow the native omission exception. Development shared-staging
with empty audience requires absent `aud`. `NativeTokenPolicy` checks the native
binding locally (its general workspace audience check also accepts an array
containing the configured value); that does not relax server enrollment's scalar
rule, signature checks or current Box/human authority. Enrollment verifies active
Clerk session and verified email; workspace admission checks current local identity
and human/Box grants. Existing beta entry without enrollment remains intact.

**Discovery step before the exact-list yes (H2), not performed today.** Use
read-only Clerk research plus a staging-realm-only trial on synthetic accounts;
the only output is the exact supported Clerk settings list for sign-in-once.
Any staging Clerk setting changes for that trial need their own John's yes
before the trial. Codex changes no live or staging Clerk setting and creates no secrets; the founder/operator makes any approved staging or live change. Do not invent settings. Then present that exact list for John's yes:
sign-in-once, V0-5 and every shared-identity slice remain BLOCKED on that yes,
additive and not implemented today. Existing users keep signing in the same way
until that yes; staging qualification is not approval for live changes.

**Required SSO additions, unverified until built.** Keep per-device sessions and
native custody beneath one CosmaBot identity, but establish them without a second
credential sign-in on already registered devices after the user's first sign-in.
Adding a new device to the sign-in-once binding requires a full credential
sign-in; a stolen signed-in phone cannot unlock a new device. A Clerk-supported, authenticated
device/session handoff must be qualified for phone, Mac and extension, bound to
the user, realm, device/browser profile, single-use challenge, expiry and callback
state. No such cross-device exchange is defined by this contract/source; neither
changing ephemeral-browser preferences nor enabling an SDK option proves it.
Exact Clerk API/flow and configuration are unresolved prerequisites, not an
invented working flow. If Clerk cannot supply it within these fences, bring the
missing supported flow back for approval before building; do not substitute
three logins. Already registered devices may unlock automatically only after
that authenticated binding, current membership checks and session establishment.
Paired extensions receive a narrow device-read capability from the authenticated
desktop relay, not its Clerk bearer. Extension-only needs a separately qualified
SSO-established browser session/capability; no phone-held bearer is copied to it.
SSO unlock is app access, not permission to start/renew EMR viewing or bypass
device lock, private grants, practice selection or the explicit Chief-open step.

**All-app sign-out and revocation, required additions.**
All-app sign-out, linked-session invalidation and local-observation clearing apply only to sessions created through sign-in-once. Existing non-SSO sessions keep today's per-device sign-out. Membership removal, admin disable and password reset continue to revoke every session as today.

A sign-out on any app
must immediately fence that app, end its observation session and revoke its
capabilities, then invalidate the linked phone/desktop/extension sessions and
SSO binding through an authenticated server-side session/device registry.
Deliver invalidation to connected clients; re-check on token refresh, admission,
dispatch, reply and reconnect, clear local observations and invoke native logout
with durable failure/retry fences. This registry/fan-out is missing today;
current SDK `signOut()` is not evidence of all-app propagation. Offline devices
cannot receive an immediate event: short-lived authority must expire, local
access must lock when current authority cannot be established, and reconnect
must reconcile revocation before unlock. This new offline lock applies only to
sessions created through sign-in-once, not existing non-SSO sessions.
Propagation latency is unmeasured.

Membership removal denies the affected practice on **all three apps** and ends
viewing there without dropping unrelated valid memberships. Session revocation,
password/reset and admin disable must invalidate every linked app's affected
authority, suppress in-flight replies and prevent silent SSO re-unlock. Qualify
Clerk's actual event/session behavior for each case and add server reconciliation
where needed; password reset must not be assumed to revoke every session by
itself. A lost device needs authenticated remote sign-out/revoke from another
trusted device or an authorized admin, device-key/capability revocation and
session invalidation; this control is proposed, not shipped. A shared computer
must not leave an unlocked session for the next person: explicit sign-out,
durable local block, cleared local observations and lock/presence expiry apply;
SSO must not resurrect the previous user's access. Qualify crash, offline logout,
late callback and next-user recovery without changing existing users' sign-in.

The following list is verified against the contract/source requirements, **not
against a live Clerk dashboard**. Source SDK options and backend settings are
identified separately from Clerk console configuration. Unknown literals or
unsupported flows stay unqualified; no complete approved live change list exists.

| Setting / contract | Exact existing requirement and proposed approval scope |
| --- | --- |
| Clerk realm / application | Keep each environment's issuer and publishable-key realm. Production-review is `operational-production-v1` / `https://clerk.beta.cosmas.ai`; `clerk.cosmas.ai` / `operational-beta-v1` remains the live profile and is reserved for the later per-practice enrollment design; staging keeps its pinned development realm. Pairings: [native sign-in contract](../NATIVE_SIGNIN_ACCOUNT_CONTRACT.md#L32), lines 32–37. John must approve which existing realm gets the additive extension client, or any new application credentials. No second IdP or user migration. |
| Hosted-auth redirect URIs | Native callback is `bundleIdentifier + "://callback"`; existing operational callbacks are `com.cosmasos.beta.ios://callback` and `com.cosmasos.beta.desktop.auth://callback`. Preserve them and synthetic bundle-specific callbacks. Add only the exact extension login callback for each qualified browser/released extension ID. IDs and resulting redirect strings are not yet known: approval must name the actual strings before change, never a wildcard or fabricated ID. |
| Allowed origins / authorized parties | Existing native request origins are `capacitor://localhost` and `app://cosmas`; preserve existing web origins. Backend `allowed_origins` and `authorized_parties` are process settings, not automatically Clerk dashboard fields. Browser JWTs require `azp` in exact approved parties; native `azp` may be absent, but when present equals its native origin. Approval must list exact extension origin (Chromium `chrome-extension://<released-id>` if supported), callback origin and resulting browser `azp`, corresponding Clerk origin configuration and backend entries. Clerk acceptance is unqualified; do not bypass it with native-origin rules. |
| PKCE / flow | Native code uses `startHostedAuth`, not an implemented extension OAuth/PKCE flow. Propose authorization-code PKCE/state binding only if Clerk supports the selected extension flow; qualify client/redirect registration and PKCE enforcement and show John the exact settings. No invented Clerk PKCE toggle or client secret in a public extension. |
| Session JWT claims / audience configuration | Preserve configured production `aud`; enrollment requires an exact scalar, with pinned `iss`, `sub`, live `sid`, `exp`/`iat`/`nbf`, and the native/browser `azp` rules above. Development `shared_staging` with empty configured audience requires absent `aud`. The contract supplies no literal production audience; fixture `cosmas-os-beta-api` is not evidence of the selected live value. Driver calls `getToken(skipCache: true)` without a named template: do not invent a required JWT-template name. Any Clerk session-claim/template change must specify actual configured audience and claims for John's yes; no widening/removal of issuer/session/Org checks. |
| SSO/session synchronization and revocation configuration | Existing SDK options are `sharedSessionSync: nil`, `watchConnectivityEnabled: false`, and hosted auth `prefersEphemeralWebBrowserSession: true`; these are client options, not verified Clerk console toggles. The supported cross-device SSO exchange, any Clerk application/session policy, event subscription and reset/disable revocation settings must be identified with exact supported names and values before John's yes. No source-defined SSO console switch or verified logout-all setting exists to list as ready. Preserve current session policy/expiry until that approval; qualify global logout, remote device revoke and offline reconciliation on synthetic accounts. |

V0-5 and any shared-identity slice remain BLOCKED until unresolved literal
extension IDs, redirects, origins, parties, realm, audience/flow and SSO/revocation
settings above are the exact list produced by the discovery step and John says
yes to that list. The slice stays additive and not implemented today. Codex changes no live or staging Clerk setting and creates no secrets; the founder/operator makes any approved staging or live change. Answer (1) replaces the r2
sign-in reading but does not approve those exact live settings.
Qualify on synthetic accounts; keep native callbacks, Keychain service names,
membership/access paths and shipped sessions intact. No new sign-in/enrollment wall.

### Optional on-device model boundary

DL-20261117-01 item 4 permits a small desktop model for perception (screen,
patient and change recognition), protection (PHI minimization, mismatch warnings
and later pre-fill checks), and short on-screen staff help (missing/changed
fields, call notes, answers about visible content). V0 works with deterministic
selectors first; **OPEN-JOHN Thursday, November 19, 2026: speech-to-text and drafting providers,
and optional on-device model choice/explicit yes, with no default selection.**
STT and drafting stay fake-only until John names providers; application LLM
remains dark. Do not change the model. A model is optional and separately default off under proposed
`desktop_local_perception_enabled`. Consequential output must be verified by
code against typed fields/context or escalated; low confidence never binds a
patient or creates authority. Test incorrect/missing/contradictory outputs,
model absence, resource exhaustion and deterministic fallback. Model text is
untrusted, not a command or a clinical fact.

No on-device clinical note drafting, coding decisions or clinical judgment.
Cloud remains the reasoning layer. No model weights of Chinese origin,
including derivatives; a later model PR must document weight lineage and
qualification. Model weights ship through a reviewed package/artifact process,
not screen packs. Preserve the prohibition on runtime dependence on Cursor's
GPT-5.6 SOL endpoint (as named in `AGENTS.md:117` and
`docs/CANONICAL_ARCHITECTURE_CONTRACT.md:474`). Device compliance checks remain V2; this model is not a
security-monitoring feature.

## 5. Screen packs are versioned data, never remote code

The observed person is the CosmaBot user who starts that session under their own EMR login. A session is started and renewed only at the observed computer by the person signed into it; whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. Remote start is not proposed. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it.

Backend serves immutable JSON screen packs over authenticated HTTPS. Proposed
contract: `cosmas.screen-pack.v1`. A manifest names pack ID, semantic version,
content hash, compatible interpreter versions, system ID, exact allowed
origins, publication/expiry times and activation scope. The pack describes:

- Screen IDs and labels; bounded URL path patterns and required page markers.
- Fixed CSS selectors and field mappings with types, maximum lengths and
  cardinality; allowlisted literal conversions such as whitespace trimming
  and date parsing implemented in the packaged interpreter.
- Patient/visit context markers, expected identity consistency and confidence
  requirements; partial-list coverage and freshness rules.
- Login/timeout/loading/error markers and explicit unsupported-layout results.
- Minimized observation fields and excluded regions (passwords, tokens, other
  charts, unrelated messages). No full DOM, screenshot or HTML upload by default.

The interpreter ships in the extension store/package and changes only through
a normal reviewed release. Packs contain no JavaScript, WASM, expressions,
event handlers, HTML templates, executable URLs, arbitrary fetches, click
sequences or navigation scripts. Bound selector counts, evaluation time,
message/body sizes and pattern complexity. Reject unknown fields/opcodes,
unsupported versions and wrong content hashes. Serve with JSON content type;
do not evaluate or inject downloaded data into a page.

Pin pack ID/version/hash to each observation and work revision. Pack activation
is explicit by Box/system; origin permissions cannot be broadened by a pack.
Stage a new version on synthetic fixtures, then a small allowlisted synthetic cohort; no live practice until a separately approved real-data rung.
Revocation stops new reads; rollback selects a prior still-approved immutable
pack. An offline cache may use an unexpired approved pack, but cannot bypass
revocation checks to accept cloud work. Layout drift produces a visible
unsupported/partial result and diagnostic codes, not guessed field values.

## 6. Page read to observation to existing F-8 work

1. An already granted endpoint reads a supported loaded page in the observed
   human's EMR browser session. A granted doctor or practice owner (Q5, section 1) may view an
   employee's different login in V0–V2 for small practices under the **OPEN-JOHN** practice-size rule in section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm).
   N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule.
   A session is started and renewed only at the observed computer by the person signed into it; whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. Remote start is not proposed. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it.
   The observed person is the CosmaBot user who starts that session under their
   own EMR login, with staff notice and visible indicator. Agents never start,
   renew or widen it themselves;
   passive page changes are admitted only while unlocked, human-present and
   within that session, current grants and expiry. Phone requests stage a fresh-read request against this
   existing read scope, never create a new EMR login or unattended task runner.
   No autonomous browsing, navigation or simulated user activity is allowed.
2. The paired relay or fallback HTTPS ingress validates the endpoint capability,
   exact origin/profile/connection, Box, session generation, payload bounds and
   request key. The backend derives authority from its own records; a client
   `box_id` or patient label is not proof of authorization.
3. A new browser adapter sits behind the existing EHR read boundary and emits
   a bounded browser observation: endpoint and connection references, source
   time and server receipt time, pack/version/hash, screen kind, patient/visit
   binding if verified, coverage, freshness, source/payload hashes and provenance
   `browser_page`. Unknown or contradictory identity refuses clinical attachment.
4. Gate new observation kinds by negotiated protocol/contract revision before
   sending or accepting them (`docs/workspace-compatibility.md`). Existing
   `src/cosmas_os/ports/ehr_reads.py` uses `extra="forbid"`; do not add fields to
   older closed shapes or send unknown kinds to older installed clients. Introduce
   a separately versioned browser shape, update validators/dispatch and compatibility
   advertisement together, and refuse unsupported versions before body dispatch.
   Qualify old/new client-server matrices and rollback; preserve existing-user
   access on the compatible old path. Extend contracts additively. Do not
   disguise browser evidence as `protocol: fhir`, a vendor API receipt,
   `transport: mock`, or `mode: synthetic` in a real runtime. Reuse the existing
   private snapshot/public projection and current-authority checks in
   `application/ehr_reads.py`; update all schema/validator copies together.
5. Persist the observation and its custody under Box scope. Idempotent replay
   with the same key/hash returns the same receipt; changed content under that
   key conflicts. Partial data never proves absence from the whole EHR. A
   server-validated patient link is necessary before patient-specific work.
6. An application producer creates or updates a deduplicated **existing F-8
   Ticket**, with an immutable ActionRevision binding the selected observation
   hashes and requested outcome. Queue UX offers the read result/review or the
   reason a fresh read is unavailable. Source text cannot grant tools/authority.
   Existing reviewed-source selection stays explicit; a background read does
   not automatically share a private notebook or attach a chart to a visit.
7. Reads/observations need no new human approval merely to occur (D-008)
   inside a human-started, unexpired viewing session; D-008 removes per-read approval, not session start/renewal.
   Any later side effect follows deterministic authority and the existing
   exact-revision approval/Operation path. Changed evidence or payload creates
   a new revision and invalidates prior approval. V0 exposes no EMR write tool.

Observation storage, device status, request correlation and bounded encrypted
transport retry are records/transport, not a second work queue. The extension
has no approve/complete buttons, task scheduling authority or independent
business ledger. Cloud retry dispatch refers to the same Postgres intent;
timeouts are unconfirmed, not successful completion. Bound retries and retain
the same request identity through disconnect/restart. Never replay mutations
because the remote outcome is unknown.

### Proposed observation retention and safety prerequisites (before V0-4)

Store per page-change observation only: opaque Box/endpoint/connection references,
observed human/caller principal references and session generation; screen kind,
pack/protocol version/hash; source and receipt times; verified patient/visit binding
when needed; bounded allowlisted typed fields, coverage, source/payload hashes and
receipt/deduplication key. Device status contains only the section 7 last-seen snapshot fields. No full DOM, HTML, screenshots, audio, cookies, credentials, unrelated
charts or staff activity timeline. Retain latest minimized device status only;
replace on update and expire after 24 hours without a heartbeat.

**Proposed retention rule for approval, not implemented:** page-change payloads
and patient/context bindings expire 24 hours after receipt, including superseded
snapshots and retry buffers. A purge job deletes chart content, patient bindings
and clinical projections from hot storage/cache; clients expire local buffers on
the same bound and clear them on sign-out. Purge receipts keep opaque receipt ID,
rule, deletion time and outcome, without patient labels or bytes.

Answers rendered into a conversation are clinical projections: they are redacted to a content-free "expired" stub on the same 24-hour bound unless a separately approved retention rule covers them.

**Lasting content-free access record (N3):** after chart-content purge, keep who
viewed whose screen (opaque viewer and observed-human principal references plus
Box/endpoint/session references), and the start, each renew and end times, under
a six-year access-record retention rule measured from session end, separate from the proposed 24-hour
observation expiry. Include
the actor for each turn-on/turn-off/start/renew/end where different from viewer. No chart content,
patient labels/bindings or observation payloads; no general staff activity history.
John, relayed via CoS, 19 Nov 9:28am ET: "Keep access records 6 years".
The six years run from session end; the action at six years is not decided. This is John's product decision, not a compliance finding.
V0-4 is no longer blocked on this duration; the implementation prerequisites remain.

Keep F-8's immutable hash binding intact: an expired revision retains its exact
content-free action payload/hash, selected evidence hashes/opaque references,
approval/decision and Operation/audit linkage. Never delete or rewrite a hash
that an immutable revision still binds. Unbound observation hashes can be purged;
bound hashes survive under existing revision/audit retention without source bytes
or patient labels. Proposed browser revisions must reference expiring content,
not embed it in their immutable payload. Record evidence expiry separately;
refuse execution dependent on expired evidence and require a fresh observation
and new revision/approval. Existing approval does not authorize fresh evidence.
No silent copying of page payload into indefinite ticket history. A separately
reviewed human-saved artifact needs its own approved retention rule, not an implicit
exception. A 24-hour maximum for observation backup copies is **unproven**;
before V0-4, prove backup deletion/restore expiry enforcement meets that maximum
or fall back to purge-on-restore before restored observations become accessible. Test
clock-driven expiry, crash/retry, failed purge reconciliation, cross-Box isolation
and restoration that cannot resurrect expired data, preservation of bound hashes
and post-purge access-record retrieval without chart content. Purge failure blocks
**new observation admission only** for the affected Box until reconciled; expiry
still refuses expired content. Report a safe failure code and retry/reconcile.
It must not block sign-in, practice access, notes or other existing normal access.

`docs/RETENTION.md` currently covers insurance artifacts only. Do not edit it in
this PR; a later approved update is needed for observation expiry, the lasting
access record and bound-hash exception before implementation.
BAA version 2.3 (as named in `docs/STAGING_ONBOARDING_DELIVERY.md:11`) coverage for EMR page observations and device status is **unverified**;
no coverage claim or BAA change here, and no new acceptance wall for live users.

Every proposed switch in section 9 must use existing `src/cosmas_os/config.py`
refusals: `cosmas_ehr_real_data_enabled` defaults off, must not be set in
hosted/production, and also requires a recorded practice-BAA flag on the connection.
Respect `workspace_hosted_enabled` and existing EHR availability's hosted refusal;
`real_patient_recording_enabled` must stay false in process configuration.
No new observation/read switch or Box allowlist (for the new capability only) overrides these gates. This plan
admits synthetic data only. Test forbidden real-data/hosted/BAA/recording combinations
fail closed on admission, dispatch and response, not just in UI.

## 7. Phone to cloud to desktop and back

The practice owner designates one registered endpoint as the **anchor computer**:
the default machine for practice-level questions. It belongs to the existing
Box; multiple physical computers do not create multiple Boxes. Selection is an
explicit, audited owner change. Do not switch anchors automatically to whichever
employee is active. A remote Mac mini can be the first test anchor, but is not
evidence that every Mac stays awake or signed into an EMR.

**Proposed, not a proven complete path; requires section 9 runtime services.**
Phone request -> existing signed cloud session -> current Box/role/device grants
-> existing F-8 staged read work and correlation -> desktop's outbound
authenticated poll/stream -> paired extension read within the enabled human
browser-session scope -> cloud observation -> authorized answer
in the same phone conversation. Phone-originated actions stage work at the
desktop and never send. A read result is a scoped observation response, not permission to send messages or
execute EMR actions. Any future prescription preparation is for the prescriber
to sign in the EMR; CosmaBot never signs or transmits a prescription. No
phone-to-LAN inbound port, RDP tunnel, consumer messenger or phone-held EMR
password. On reconnect the app claims the same bounded request; if it expired, report unavailable rather than silently
running old work against a newly opened chart.

Store a last-seen snapshot with endpoint ID, safe computer label, pairing
generation, anchor designation, OS-state confidence, browser availability,
connection/EMR status, `observed_at`, server `received_at`, last successful
page-read time, pack hash and coverage. Keep heartbeat time separate from
clinical source time. Display, for example, “Front desk Mac: last seen 10:42 AM;
appointment list read 10:39 AM; screen locked.” This is a dated observation,
not a live screen mirror. Proposed V0 freshness: heartbeat every 30 seconds
while connected; after 90 seconds mark connectivity unknown; fresh page
answers require a source no older than 60 seconds unless an explicitly labeled
historical answer is requested. Clock skew outside tolerance refuses freshness.
These numbers are proposed defaults to qualify, not existing guarantees.
Status is operational availability only. Device compliance checks are deferred
to V2 and called compliance checks; V0 adds no security monitoring, device
posture scans, keylogging or staff-surveillance history.

| Caller | Which computer and information may be requested |
| --- | --- |
| Owner or explicitly granted practice administrator | Register/revoke endpoints and select the anchor; see permitted practice device health. Device administration alone does not grant access to every clinician's private content. |
| Provider/staff with explicit device-read and clinical-context grants | Ask about the anchor or a named granted endpoint within their Box and allowed patient/work context. The observed person is the CosmaBot user who starts the session at that computer under their own EMR login, with notice, indicator and bounded session. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it. Viewing an employee's different EMR login remains permitted under (a). N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule. For V0–V2, a granted doctor or practice owner may observe an employee's different EMR login under (a) and Q5 in section 1. Practice size is **OPEN-JOHN** under section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). No impersonation or unrelated private-source access. |
| Agent principal | Read only for an authorized task under its installed capability and existing human-enabled/context scope; never start, renew or widen a viewing session, impersonate, expand grants or self-approve, and never wider than the requesting human's current viewing permission. |
| Other Box, removed member, ungranted member or support/coding agent | Deny endpoint discovery, status and clinical answers; owning a phone or knowing a device ID supplies no authority. |

Answers rendered into a conversation are clinical projections: they are redacted to a content-free "expired" stub on the same 24-hour bound unless a separately approved retention rule covers them.

The phone receives a minimized authorized answer, source time/coverage,
safe endpoint label, availability and an existing work/review card if needed.
Patient-specific details reach it only after current patient/workspace grants
are checked again at response time. Do not send raw DOM, desktop screenshots,
ungranted charts outside the bounded employee-screen scope, local paths, cookies, tokens, audio or an unrestricted
device history. No PHI in notification previews; V0 can use the existing open
app response flow because push notifications remain deferred. Revocation
during a read suppresses the reply and leaves a safe unavailable result.

## 8. Behavior by computer state

The observed person is the CosmaBot user who starts that session under their own EMR login. A session is started and renewed only at the observed computer by the person signed into it; whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. Remote start is not proposed. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it.

Lock, nobody-present state, sleep, EMR timeout and app/browser availability are
separate facts. Missing heartbeats cannot distinguish them. Locked-screen
continuity is unmeasured; John has not authorized locked or nobody-present reads.
V0 defaults both off, including V0-7 / `background_page_reads_enabled`.

| State | Paired desktop path | Extension-only path | Phone result and limits |
| --- | --- | --- | --- |
| In use, unlocked, human present; EMR session active | Read supported loaded pages only within the bounded human-enabled session, indicator and current grants. Recording has separate consent/lease gates. | No reads until the section 1 browser idle/lock API and foreground/presence qualification passes; unknown refuses reads. | Fresh permitted answer; chart change invalidates binding; no navigation. |
| Locked, awake | No new page reads. Safe transport/status only if credentials allow noninteractive access; no hidden prompt/unlock. | Cannot assert OS lock state; unknown lock/presence refuses new reads rather than assuming unlocked. | Dated last-known evidence, “fresh read unavailable.” Heartbeat/cache does not prove a fresh read. |
| Unattended / nobody present (even unlocked) | No new reads; end session until explicit human restart with presence confirmed. | Same default-off rule; service-worker availability does not establish human presence. | Dated history only under current grants. OPEN-JOHN Thursday, November 19, 2026; no authorization inferred from (a). |
| EMR idle logout / timeout | Stop clinical reads; detect marker only in permitted foreground session, or after human unlock/return. Cloud link may remain. | Same; stale DOM is not current session evidence. | Human sign-in on observed computer is recovery. No credentials/keepalives. Separately authorized APIs have separate status/gates. |
| Sleep, hibernation, app/browser exit or network loss | No new reads or promised recording continuity. Revalidate session, pairing, pack, expiry and chart after return. | No read if execution unavailable. | Pending request expires visibly; dated history only. No wake/unlock/relogin tool. |

Locked or nobody-present activation requires John's Thursday answer followed by
separately approved qualification. Even then, cached evidence cannot prove
continuity: require post-lock changing-fixture source revision/hash and source
and receipt times before any future claim. OS/browser/native-messaging/store
behavior remains unmeasured. Do not weaken lock or timeout to qualify it.

## 9. Small, separately releasable V0 pull requests

Each implementation PR is a later approval-dependent change. Proposed switches
below do not exist yet; all default false on server and relevant client, with
an explicit Box allowlist for the new capability only. Today switches are process settings in
`src/cosmas_os/config.py`; there is **no existing Box-level allowlist mechanism**.
Propose a Postgres Box-capability record keyed by permanent Box ID, capability,
revision, owner authorization and expiry,
checked on admission/dispatch/reply for the new capability only; revoking the record invalidates only that capability's grants and caches. A Box with no record keeps all existing access. Unknown/omitted switch values refuse activation of that capability only.
This must be built and tested first, not assumed present.
Disabling a switch stops new admission/dispatch, retains history and lets an
already accepted receipt reconcile without starting new work. No switch grants
EMR writes, real-data processing or production activation by itself.
The slices are dependency order, not a promise to finish them in two weeks:
Windows work (V0-W) starts no earlier than week three and only after John's Windows-scope answer; no Windows PR before it.
BLOCKED: no V0-8 PR, including fake-only, until John answers the recording/Scribe boundary.

### Runtime prerequisite R0 (before service-bearing slices)

Evidence: `docs/flight-plans/2026-10-27-standalone-practice.md`,
`src/cosmas_os/config.py`, `src/cosmas_os/api/app.py:lifespan` and its queue
refusal. `standalone_synthetic` and `standalone_clerk_synthetic` do not start
queue, handoff/routine or new observation connector lifespans/background workers;
queue dispatch fail-closes. AI Send and member management remain unavailable.
Unlisted true `*_enabled` settings refuse standalone startup. Current app source
has explicitly configured Google/Microsoft personal-service lifespan hooks; this
is a narrow existing exception, not availability of F-8 or browser connectors.
Use neither those hooks nor the standalone Core-capture exception as a hidden
implementation path. New flags cannot simply be flipped in either profile.

Target **S** is a future reviewed `standalone_clerk_synthetic` backend with
`standalone-practice-v1` web/Mac/iPhone clients, synthetic data and fake processing
only. S is **not currently ready**. Before V0-2 service work and V0-4/V0-6/V0-8
queue work: build additive endpoint/grant/Box-allowlist and retention schemas;
explicit synthetic ingress/dispatch routes and configuration admission; F-8
read-work producer and immutable revisions/Operation ledger; bounded authenticated
endpoint poll/receipt transport; worker lifecycle and retry/reconciliation/purge
service with sandboxed egress; Messages/action/response authorization and protocol
compatibility. Test startup refusals, expiry, revocation and restart recovery.
Any standalone admission/worker changes require a separately reviewed prerequisite
PR now that #400 has merged; no weakening of existing guards. Until R0 is built, those
slices **cannot run in standalone**; local port tests are not an end-to-end runtime.
No hosted/production promotion, provider activation, live users or Core fallback.
The live instance's configuration is untouched.

Target **L** is isolated local fake ports/fixtures (no backend service startup),
with `standalone_synthetic` / `standalone-practice-v1` used only for already
admitted setup/notebook UI. New service flags remain false there. **M** is the
Mac Electron packaged synthetic client / Swift native helper (macOS 14.2 audio
minimum); **W** is a future Windows Electron synthetic profile, not an existing
OSX release profile. Proposed Windows client profile: `windows-standalone-synthetic-v0`
(to build/qualify, not shipped); it must preserve `standalone-practice-v1` contracts.
M uses `standalone-practice-v1` with existing synthetic identity configuration;
S sign-in qualification uses `operational-staging-v1`, never a live-user realm;
sequence section 4's exact-list discovery step first, with its separate John's
yes before any staging-setting changes for the trial. Codex changes no live or staging Clerk setting and creates no secrets. **E** is a development Chromium/Edge synthetic extension;
store approval, signed IDs and cross-browser native messaging remain unqualified.
A full S/M/E or S/W/E path needs R0 plus explicit platform and identity approvals.

| Slice / independent release | Deliverable | Tests required in that PR | Default-off switch / rollback | Runtime / environment / profile |
| --- | --- | --- | --- | --- |
| R0: synthetic runtime prerequisite | Additive endpoint/grant/Box-allowlist and retention schemas, admitted synthetic routes, F-8 read producer/revisions/Operation, endpoint transport, worker/purge lifecycle and Messages authorization/compatibility; no live instance configuration change | Startup refuses unknown flags and forbidden hosted/real-data combinations; cross-Box/expired/revoked admission denied; crash/retry/response-loss reconciles same intent; purge failure preserves normal sign-in/practice/notes, expires content and retains content-free access records/bound hashes; old/new protocol rollback | Proposed `extension_desktop_runtime_enabled`; false by default with Box allowlist for the new capability only; stop new observation admission/dispatch, reconcile accepted receipts and purge expiry, preserve normal access/history. Existing standalone guards remain until explicit reviewed admission. | L schema/port fakes, then S only after #400 and approval; live configuration untouched |
| V0-1: data contracts and fake observation | Screen-pack schema, bounded packaged-interpreter contract and synthetic page fixtures behind EHR read ports; no browser installation | Unsupported version/opcode, oversized pack, hash/origin mismatch, ambiguous layout, partial lists, malicious page instructions and patient mismatch all refuse correctly. Golden allowed fixtures and negative mutations. | `screen_pack_reads_enabled`; disable pack selection, retain pinned evidence. | L; isolated fake interpreter, no service activation |
| V0-2: endpoint registration/status | Additive Box-scoped endpoint records, device key binding, last-seen timestamps and anchor selection in existing settings | Allowed/denied Box/member/device matrix; stale/skewed times, duplicate enrollment, revoked key, anchor replacement and concurrent owner edits; restart retains same endpoint. | `desktop_endpoint_presence_enabled`; stop presence writes and new enrollment without deleting history. | S + M; BLOCKED on R0 endpoint/allowlist/config admission |
| V0-3: paired relay | Native-messaging host, strict packaged-extension allowlist, explicit pairing and revocation, one synthetic read round trip | Rogue page/extension/profile, challenge replay/expiry, malformed/oversized messages, sign-out in flight, relay crash/restart and lost receipt retry; existing desktop sandbox/auth tests. Mac install/signing verification outside Linux CI. | `desktop_extension_pairing_enabled`; unpair/refuse new relay traffic, preserve app sign-in and recording. | L + M + E for fake relay; S pairing service BLOCKED on R0 and credential/ID approval |
| V0-4: observation custody and F-8 | Backend ingress/browser adapter, accurate additive provenance, minimized projections and deduplicated read-review Ticket/ActionRevision | Cross-Box/patient refusals, revocation before/after I/O, altered hash/key conflict, duplicate ingress after response loss, worker crash, no duplicate ticket/operation, edited revision invalidates approval, source text cannot invoke tools. | `browser_page_observations_enabled`; block ingress/new producer work; existing queue and historical receipts remain. | S + M + E; cannot run until R0 F-8/workers/retention/protocol built |
| V0-5: sign-in-once SSO and extension-only fallback | **BLOCKED on John's yes to the exact Clerk settings list produced by section 4's discovery step; not implemented today. Codex changes no live or staging Clerk setting and creates no secrets; the founder/operator makes any approved staging or live change.** One sign-in is to unlock phone/desktop/extension automatically under qualified device/session binding; additive shared identity, browser endpoint enrollment and direct HTTPS observation flow; existing users keep signing in the same way until that yes | Supported SSO handoff/callback/state and audience/azp matrix; all-app sign-out, membership removal, session revoke, password/reset/admin disable, lost/shared device, offline/reconnect and late callback refusal; existing-user sign-in unchanged. PKCE only if supported; token expiry, malicious page messages, worker suspension/tab discard and idempotent reconnect; no native/cloud bearer to page code. | Proposed `shared_identity_sso_enabled` and `extension_only_reads_enabled`; both false; disable new SSO establishment/fallback, invalidate new bindings while preserving existing sign-in; no automatic downgrade. | Synthetic phone + M + S + E; section 4 discovery step, R0, supported SSO flow and John's yes to that exact list; live changes remain blocked |
| V0-6: phone round trip | Named/anchor target in existing Messages/Workspace action flow, status and dated answers; no new navigation surface | Full caller matrix, active-user versus caller grants, stale snapshot, anchor changed mid-request, lost desktop connection, expiry on wake, membership revoked before reply and private-source non-disclosure; phone/desktop UX parity. | `phone_computer_reads_enabled`; remove new read action and stop its dispatch; normal conversations remain. | S + M + E + synthetic iPhone standalone-practice-v1; R0 F-8/Messages/dispatch required |
| V0-7: lock/unattended refusal and later qualification | Default-off reads under lock/nobody present; **OPEN-JOHN Thursday, November 19, 2026** for any activation | Prove new reads refused on lock/unknown presence, no hidden credential UI, expiry on wake and stale DOM not fresh. Post-lock fresh changing-fixture reads only after John's answer and separate approval; idle-logout test needs none. | `background_page_reads_enabled`; stays false, preserve dated evidence. | L/M/E refusal fixtures; S after R0; locked/unattended reads OFF pending John |
| V0-8a: independent audio transcription | **OPEN-JOHN Thursday, November 19, 2026 recording/Scribe boundary; fake-only until STT provider named.** BLOCKED: no V0-8 PR, including fake-only, until John answers the recording/Scribe boundary. OS-owned port and immutable transcript custody using local fake, existing encrypted recordings and same operation identity; no legacy calls | Corrupt/truncated audio, consent/lease expiry, duplicate upload/receipt loss, processor crash/recovery, revocation, model outage, no hidden Core/legacy egress; fake output visibly synthetic. | `independent_recording_transcription_enabled`; refuse new transfer, retain recoverable encrypted audio. External processor stays separately dark. | L + M / synthetic iPhone capture fakes; S persistence/workers require R0 and recording decision |
| V0-8b: independent note draft | **Same recording boundary; drafting fake-only until provider named; application LLM dark.** BLOCKED: no V0-8 PR, including fake-only, until John answers the recording/Scribe boundary. Exact transcript-to-draft linkage and human review in existing work/notes flow; fake first | Changed transcript invalidates draft approval; partial/gapped transcript, wrong patient, duplicated retry, unauthorized reviewer, no auto-sign/submit and no legacy fallback. | `independent_recording_note_draft_enabled`; retain transcript/draft history, stop new drafting. | L fake draft port; S Messages/review/F-8 requires R0 and recording decision |
| V0-W: Windows desktop sign-in and packaging (before V0-9) | Windows work (V0-W) starts no earlier than week three and only after John's Windows-scope answer; no Windows PR before it. New native auth-helper/credential custody and process fence, Windows release profile/installer and code signing; currently helper is `darwin`-only, packager `OSX`-only, Swift audio macOS 14.2 | Sign-in/out, token refresh, denied credential interaction, profile/session revision fence, upgrade/uninstall/rollback, signing verification and preservation of Mac/phone sign-in; no audio equivalence claim | `windows_extension_desktop_enabled`; refuse Windows enrollment/reads, preserve existing clients. | L + W future synthetic profile; S integration requires R0, Windows scope and exact identity yes |
| V0-9: Windows qualification | **OPEN-JOHN Thursday, November 19, 2026 Windows scope.** Depends on V0-W sign-in and packaging; substantial native host/credential/install qualification, not a minimal adapter; no Mac Swift audio reuse | Chrome/Edge native host identity/registry/install validation, Windows credential failure, lock/logoff/RDP disconnect/tab discard/sleep, remote VM reconnect and same request recovery. Existing browser contracts must remain identical. | `windows_extension_desktop_enabled`; Windows capability remains unsupported until the platform matrix passes. Windows native audio extent has no default; John's Thursday, November 19, 2026 scope decides. | S + W + E, physical PC then synthetic Azure VM; all prerequisites and founder approvals |
| V0-optional: local perception/help | Off critical path, only after explicit John yes; small approved-lineage on-device model behind the permitted desktop interface; no clinical drafting | Wrong patient/change detection, unverified consequential output, unsupported weight lineage, absent model and memory/CPU exhaustion; deterministic verification or escalation, never clinical judgment | `desktop_local_perception_enabled`; use deterministic selectors and fake-only response processing; application LLM stays dark, retain existing observations. | L/M separately approved synthetic model harness; no application LLM activation |

For every new fence test both sides and remove/invert the guard to demonstrate
that its proving test fails. Name actual collected CI jobs in each later PR;
use existing backend suite wrappers, web tests and desktop Node tests. Native
Mac/Windows device tests need attached synthetic run logs; Linux CI alone is
not proof. Follow `docs/review-policy.md` for implementation plan review and
required final-head review. Fable reviews the final head of this draft plan PR.

### New credential and endpoint approvals (no creation in this planning PR)

Each item needs **John's yes** before creation/acquisition. Proposed custody is
not an assertion that a secret/account already exists. Codex creates none,
commits none and puts no values in the plan, logs or PR. Publisher/code-signing
approvals do not authorize publication or store submission.

| Secret / account | Proposed custody | Who creates / acquires it after John's yes |
| --- | --- | --- |
| athenahealth sandbox browser login | Founder-controlled sandbox account/credential custody; invented charts only, no values in evidence | Founder/operator supplies approved access after John's yes; browser login and idle timeout still need confirmation. Without them week-2 timeout cells remain unrun; Codex creates no secrets. |
| Extension signing key; browser store publisher account | Founder-controlled signing vault/hardware-backed custody; founder store account, no private key in extension | Founder/operator obtains account and signing material; exact released IDs qualified later |
| Windows code-signing certificate/private key | Founder-controlled signing service/HSM; CI access only through separately approved signing identity | Founder/operator acquires certificate and restricted signing access |
| Azure VM admin and RDP credentials | Founder-managed secret vault; restricted human RDP access, never sent to phone or clients | Founder creates synthetic VM account/credentials during approved apply |
| Speech-to-text provider key | Approved backend secret manager only; no browser/desktop key | Founder creates only after naming provider and approving external processing; fake-only meanwhile |
| Backend endpoint-capability token-signing key | Backend secret manager / managed signing service; public verification material only to clients | Founder/operator creates under separately approved signing/rotation/revocation plan |
| Any new Clerk application/client credentials | Founder Clerk console and backend secret manager if confidential material is actually needed; public extension has no client secret | Founder approves exact section 4 settings and creates only required application credentials |
| Endpoint device private key (additional prerequisite) | OS native credential custody; extension-only uses separately qualified bounded browser custody | Approved product enrollment on synthetic device after John's yes; no Codex creation in this planning PR |

Azure Windows VM is a synthetic test endpoint only, not a second cloud. Week 3
requires **John's yes, founder-only Terraform/apply click, and approved cost**.
No Terraform, plan/apply/prepare/promote, workflow dispatch or infrastructure change
in this planning PR. No repo cost quote found: budgetary estimate for a small Windows
2-vCPU/8-GiB test VM is tens of dollars for intermittent testing, potentially
low hundreds of USD/month if left running, plus disk/network/IP charges. This is
an estimated cost class, not an obtained quote. Founder must confirm region/SKU,
hours and actual pricing before apply; deallocate after tests and remove resources
when complete (disk charges can remain). No admin/RDP values in evidence.

## 10. Three-week qualification plan

Weeks count from plan approval, #400 on main and applicable prerequisites, not
a three-week delivery promise. Use only invented people, appointments and screens.
Report unrun cells when access, terms, credential approval or physical hardware is
missing. No test results have been collected by this PR.

### Week 1: local Mac and remote Mac mini

L/M/E fixture tests first; S integration only after R0. Inventory synthetic
OS/browser/app versions and session/power policy without real device/tenant IDs.
Qualify explicit pairing, notice/indicator, proposed 15-minute expiry/stop/renewal,
a doctor or practice owner turning viewing on and staff then starting at the observed staff computer under H1 B. Qualify this rule: N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule.
Retain the V0–V2 different-login viewing exception for a granted doctor (17 Nov) or practice owner (19 Nov Q5, 7:04pm ET, relayed via CoS; section 1). Practice size is **OPEN-JOHN** under section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). Qualify the proposed OS-idle/foreground presence
signal and unknown-state refusal, wrong-profile denial, caller/context grants,
pack rollback and stale/partial labels. Qualify
extension-only only after exact Clerk approval and lock/presence admission proof.
A phone round trip is a proposed later integration target, not already complete.

Lock normally, disconnect the remote viewer, and request at 1, 5 and 15 minutes:
with `background_page_reads_enabled=false` prove **no new page read** and a dated
unavailable result, no hidden auth UI, no focus/login/keepalive/mutation. Repeat
for nobody present, unknown presence, minimized/background tabs, discard and sleep.
A future continuity experiment requires John's Thursday answer and separate
approval, then a changing synthetic fixture's new source revision/hash and source
and receipt times; heartbeats or cached snapshots never prove continuity.

### Week 2: Mac failure/recovery and athenahealth idle logout

Target **athenahealth sandbox, invented patients only**, subject to confirmed
sandbox browser login, idle timeout, access and terms before running. Confirmation
is still needed; John's (b) suggests the target, not a measured result. Other
vendor sandboxes later. No browser login or idle timeout? Week-2 timeout cells
stay **unrun**. Access unavailable? Mark cells **unrun**;
never substitute real charts or fabricate a timeout value.

Test network/relay restart, response loss, duplicate receipts and same F-8 intent
(after R0), token refresh refusal, membership revocation, EMR logout/stale DOM,
sleep/wake expiry and no auto-replay against a changed chart. Synthetic audio
consent/stop/recovery is separate and contingent on recording-boundary approval;
lock continuity for audio is unmeasured, not implied by DOM tests.

Measure idle logout with at least three trials per supported configuration:
unlocked human-present idle control; locked-awake idle; nobody-present idle; and
remote-session disconnect, distinguishing lock from sleep. Set `t0` at last
human EMR interaction. Keep new locked/unattended reads OFF; human return/unlock
checks or permitted sandbox session evidence bound the logout interval. Record
interval uncertainty, browser/EMR policy/version, trial range/median and refusal
at the next permitted read. A proposed 30-second sample interval applies only
where permitted; otherwise report coarser bounds. Measuring idle logout needs no
background page reads. Bounded foreground observations may be compared with the
idle control only while present/unlocked. No keepalives or timeout-policy change.
If markers are unreliable, mark freshness unverified until permitted human
reauthentication or a separately authorized API confirms it.

### Week 3 onward: Windows sign-in, packaging, then PCs / Azure VM

**OPEN-JOHN Thursday, November 19, 2026: how far V0 Windows goes; no default.** Windows work (V0-W) starts no earlier than week three and only after John's Windows-scope answer; no Windows PR before it. Start V0-W before
V0-9: native sign-in/helper, Windows credentials, process fences, release profile,
installer, signing and upgrade/rollback. Current `spawn-auth-helper.mjs` throws
unless `darwin`; `package-desktop-release.mjs` accepts only `OSX`;
`native-audio/Package.swift` targets macOS 14.2. This is substantial new platform
work, not a minimal adapter; week three is a start, not a completed Windows claim.
Windows audio scope also depends on John's choice, not Mac code reuse.

Then qualify physical Windows Chrome/Edge and, only after founder approvals/click,
the synthetic Azure Windows VM. Distinguish lock, logoff, RDP disconnect/timeout,
VM stop/deallocation and sleep. Disconnected RDP may retain processes; logoff
cannot. None establishes authorized human presence or read permission. Prove
lock/nobody-present default refusal and permitted foreground recovery. Repeat
sandbox idle-logout only with confirmed access/terms. Native messaging across
browsers, registry/install replacement, credential custody and signed IDs remain
qualification items. Do not relax OS/EMR security settings.

For each supported cell require no unauthorized disclosures or EMR mutations,
correct age/coverage, deterministic refusal/recovery and one F-8 item on replay
where that service exists. Proposed collection: at least 30 synthetic requests,
success rate and p50/p95 latency. The 30s heartbeat / 90s unknown / 60s freshness
numbers in section 7 are proposed and unmeasured, not a production SLO. Unqualified
platform/mode stays off. Retest affected cells after OS/browser/pack/custody changes.
No SOC 2 claim, EHR write-back, Zoom-just-works or stranger-checkout claim. V0 has
no EMR write, click, type, navigate, login, submit or sign tool.

## 11. Locked-decision conflicts and smallest compatible alternatives

Every original row is retained below (1–18, M1–M6 and N1–N3), with NL1–NL5 added. **CONFIRMED**
means the invariant still applies, not that a proposed runtime passed tests.
**SCOPED** or **RESOLVED** means this plan supplies the compatible scope/dependency, not build
completion. **OPEN-JOHN** means owner decision still required; no inferred answer.
**OPEN (citation changed at merge)** means cited text changed at the #400 merge; awaiting CTO review; the CTO closes it (CTO owns rows 1 and 3).
#400 merged 19 Nov 2026 at b18af3b128e8b1db6fbd03abc07d836944efafc1. Rows 1 and 3 flag citations changed at merge. **DECIDED** means a relayed John decision is recorded here, provisional until it is in a decision log; it does not mean implementation or qualification is complete.
Legend: H1 = observed person is the CosmaBot user who starts the session under their own EMR login; **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it. whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET); H2 = Clerk exact-list discovery gate; N3 = content-free access record; NL = later-review clarification labels (NL1–NL5).
No fatal counterexample to the authority/queue/data invariants was established.

| Row / decision or rule | Status / conflict or tension | Smallest compatible alternative / resolution |
| --- | --- | --- |
| 1. `DL-20261117-01` / `DL-20261117-02` | #400 merged 19 Nov 2026 at b18af3b128e8b1db6fbd03abc07d836944efafc1. **OPEN (citation changed at merge)** — decision-log status/notes now also cite `DL-20261119-01` and the 19 Nov workstream-scope confirmation. | Re-checked `docs/DECISION_LOG.md:436–556` at that SHA against the previously cited head; historical confirmation resolution remains recorded, but the citation text changed. Review the merged text before any build PR; no additional decision is made here. |
| 2. D-001/D-002/D-012; repository boundary | **CONFIRMED** — legacy capture is not an independent path; no Track A import/shared DB. | Owned local custody and fake-first OS port proposal; future Core integration explicitly named/versioned, never hidden fallback. Shared identity does not grant shared product authority. |
| 3. Canonical browser-automation deferral / AGENTS prohibition (gap 3) | #400 merged 19 Nov 2026 at b18af3b128e8b1db6fbd03abc07d836944efafc1. **OPEN (citation changed at merge)** — `AGENTS.md:89–91,208–210` and `CANONICAL_PRODUCT_DECISIONS.md:203–205` now scope the deferral to unattended automation and agent-held EMR logins. | A granted doctor or practice owner may observe employee's loaded screen with grants, notice, indicator and bounded session. Different-login viewing applies to V0–V2 small practices under the **OPEN-JOHN** practice-size rule in section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). Locked/nobody-present reads stay off pending Thursday, November 19, 2026. No browsing/navigation/login/privilege expansion; dated evidence or separately authorized API on expiry. |
| 4. Canonical “Rebuilding the existing Scribe inside OS” deferral | **OPEN-JOHN** — independent direction / possible beta legacy exception does not decide whether V0-8 conflicts with deferred rebuilding. | Thursday, November 19, 2026 decide new OS recording path versus deferral; no default. Keep page reading separate, shared recorder/separate Scribe and independent fake-first proposal; no migration/replacement or covert Core fallback. Independent complete recording-to-note: none found, not every path disproven. |
| 5. D-003/D-011; second-EHR deferral | **CONFIRMED** — generic packs cannot activate vendors or change ArtifactChase/pricing scope. | One synthetic fixture system/screen first, athenahealth sandbox timeout target with confirmed terms/access; each vendor/real-data rung separately approved. No payment recovery or blanket browser support. |
| 6. D-004 | **CONFIRMED** — devices cannot become separate Boxes. | One permanent logical Box, registered endpoints and explicit anchor beneath it. |
| 7. D-005/D-007; shared identity `DL-20260927-01` (gap 7) | **RESOLVED** — employee login observation is permitted by (a), not identity inheritance or agent impersonation; (1) replaces r2's separate-sign-in reading. | V0–V2 observation by a granted doctor or practice owner (Q5, section 1) within caller/device/patient/work grants; deny wins. Practice size is **OPEN-JOHN** under section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). Notice/indicator/session bound; no unrelated private-source access, self-approval/signing or agent login. One sign-in automatically unlocks all three apps, with separate device/product authority; SSO unverified and BLOCKED on John's yes to the exact Clerk settings list that section 4's discovery step will produce (no such list exists yet). |
| 8. D-008/D-009 | **RESOLVED** — extension work/retries cannot create another queue; F-8 is not available in every runtime. | R0 before standalone service work: F-8 producer/revisions/Operation, workers/dispatch/receipts and recovery. Postgres intent, exact hashes/stable retries, unconfirmed outcomes. No invented approval for each passive observation. |
| 9. D-010/D-011; PHI/credential boundary (incomplete row 9) | **SCOPED** — raw uploads/default-on processing lack retention and existing gates. | Section 6 proposed 24-hour chart purge plus a content-free access record kept six years from session end and retained immutable-bound hashes before V0-4; later approved RETENTION update. Purge failure blocks only new observation admission, preserving sign-in/practice/notes/normal access. Every switch respects real-data, hosted, recorded practice-BAA and process-recording refusals. John's HIPAA sentence is an unchecked product statement, not coverage/legal evidence; BAA 2.3 unverified, synthetic only, no BAA change. Section 9 credentials need John's yes. |
| 10. D-013 / `DL-20261023-01` | **CONFIRMED** — no second UI/queue, remote control or automatic private-source sharing. | Existing settings and Messages/Workspace work cards only after runtime support; shared state/per-device presentation. No new push/camera/live dictation. Complete phone path remains proposed. |
| 11. Desktop sandbox / credential controls | **RESOLVED** — capture permission must not grant page control or generic IPC/hidden prompts. | Separate bounded relay and exact qualified IDs; register native host only with pairing switch on. Deny unknown shapes/versions; no prompt behind lock. Human interaction recovers; cross-browser native messaging unmeasured. |
| 12. `DL-20261117-01` item 2 | **CONFIRMED** — helpful fill is outside V0. | V1 only, provider-triggered explicit click and visible fields; never Save/Submit/Send/Sign. V0 has no write/click/type/navigate/login/submit/sign tool. |
| 13. Item 3 | **CONFIRMED** — phone cannot bypass desktop/prescriber. | Stage desktop work only; CosmaBot never signs/transmits prescriptions. V0 has no prescription action. |
| 14. Item 4 / runtime model invariant | **OPEN-JOHN** — permission for optional functions does not choose a model or provider. | Thursday, November 19, 2026 explicit model yes and provider choices; fake-only STT/drafts and dark application LLM until named. If later approved, only permitted local functions, code verification/escalation, no clinical judgment/drafting/coding decisions, no Chinese-origin weights/derivatives or Cursor runtime endpoint. |
| 15. Items 5, 7, 8 (incomplete row 15) | **OPEN-JOHN** — Windows extent is undecided; Mac auth/packaging/audio cannot supply it. | Thursday, November 19, 2026 Windows scope with no default; V0-W sign-in/helper/credentials/release packaging before V0-9. Windows work (V0-W) starts no earlier than week three and only after John's Windows-scope answer; no Windows PR before it. Separate Scribe/shared recorder; additive identity blocked on exact Clerk yes; compliance checks remain V2. |
| 16. D-009 / architecture style | **CONFIRMED** — persistence does not justify new infrastructure architecture. | Modular monolith/Postgres/outbound HTTPS; no Kafka/Kubernetes/event sourcing/consumer messengers/second IdP. Azure VM synthetic endpoint only, founder click, cost and John's yes first. |
| 17. Lock/sleep/timeout expectations | **OPEN-JOHN** — locked/nobody-present permission unanswered; continuity unmeasured; sleep/logout/inaccessible DOM are fatal availability counterexamples. | Thursday, November 19, 2026 decision; reads default off until answer and later qualification. Dated snapshots/refusal, human unlock/relogin or separately authorized API. Idle logout measurement does not require background reads. No security weakening. |
| 18. `DL-20261030-01` autonomy versus planning/review | **RESOLVED** — item 10 and this draft plan retain the narrower live lock. | Draft #401 adds this document versus main; r5 revises it on the existing draft branch. No merge/ready/deploy/store/live settings or secrets. Human clicks deploy. Later slices need scoped approvals and CI/review gates; no weakened Trivy/rulesets. |
| M1. Runtime model/provider decision | **OPEN-JOHN** — no STT/drafting provider selected by these answers. | Thursday, November 19, 2026 names providers; fake-only until then; optional on-device model explicit yes. Application LLM dark; no model change in this planning PR. |
| M2. Standalone runtime restrictions | **RESOLVED** — standalone has no F-8/worker execution for new slices; unlisted enabled flags refuse startup, AI Send/member management unavailable. | Section 9 assigns L/S/M/W/E profiles per slice and R0 built first. Narrow existing personal-service hooks are not new connector lifespans. Cannot run service-bearing slices in standalone until explicit admitted schemas/routes/queue/workers/Messages/retention/compatibility exist. |
| M3. Sign-in-once SSO / live Clerk settings (H2) | **RESOLVED** — discovery step added; (1) does not approve settings. | Section 4 sequences read-only Clerk research plus a staging-realm-only synthetic-account trial whose only output is the exact Clerk settings list; any staging-setting changes need their own John's yes first. V0-5/all shared identity and SSO remain BLOCKED on John's yes to that exact list, additive and not implemented today. Codex changes no live or staging Clerk setting and creates no secrets; the founder/operator makes any approved staging or live change. Existing users keep current sign-in until that yes; unknown settings stay unqualified. Establishment, all-app sign-out/revoke and lost/shared-device recovery still require qualification. |
| M4. Credentials / Azure VM | **RESOLVED** — no implicit authority to create credentials or infrastructure here. | Section 9 lists custody/creator for each secret/account; John's yes for each, Codex creates/commits/exposes none. Founder-only Terraform/apply click plus John's yes and confirmed cost; estimate is not a quote. Synthetic endpoint, not second cloud. |
| M5. Whose EMR session / start and renew (H1) | **SCOPED** — turning viewing on and subsequent staff start follow H1 B (John Q1 "A", relayed via CoS 7:27pm ET); whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET); different-login viewing follows the 17 Nov doctor rule (relayed via CoS, 17 Nov 2:23pm ET) and the limited Q5 viewing-roles answer in section 1. Practice size is **OPEN-JOHN**, with different-login viewing off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm); locked/unattended permission remains open. | N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule. A granted doctor or practice owner may view an employee's different-login screen in V0–V2 small practices under the **OPEN-JOHN** practice-size rule in section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). A session is started and renewed only at the observed computer by the person signed into it; whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. Remote start is not proposed. **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it. Notice, visible observed-computer indicator, stop and proposed 15-minute bound remain; locked/unattended/nobody-present reads stay default off. |
| M6. Stale lower docs | **OPEN-JOHN** — #400 merged 19 Nov 2026 at b18af3b128e8b1db6fbd03abc07d836944efafc1. Lower docs still contain the cited browser-automation prohibitions. | Re-checked `docs/BUILD_AND_DEPLOYMENT_ROADMAP.md:333` and `docs/handoff/CODEX_D3_TO_COMPLETE_BUILD_HANDOFF.md:145–147,373` at that SHA; citations still match. Row 3 flags the changed governing AGENTS/canonical wording. Note only here; edit no other docs or decision files. |
| N1. Who may start (10:51am answer; H1 B relayed later) | **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET)** — provisional per the legend. Question (CoS, in-app): "But your 9:28 card this morning said only a doctor or practice owner can start one. Which should the plan say? Reply 'any member with an EMR login' or 'doctor or owner only'." John's answer: "Doctor or owner only for now". Label: relayed via CoS, 19 Nov 10:51am ET. | N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule. Preserve the V0–V2 different-login exception for a granted doctor or practice owner (Q5, section 1) in small practices under the **OPEN-JOHN** practice-size rule in section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). No remote start or renewal. |
| N2. Session initiator and renewal | **SCOPED** — follow H1 B (John Q1 "A", relayed via CoS 7:27pm ET); whoever may start may renew (John Q2 "A", relayed via CoS 7:27pm ET). Practice size is **OPEN-JOHN**; different-login viewing is off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm). **DECIDED (H1 B; John Q1 "A", relayed via CoS 7:27pm ET):** a doctor or practice owner turns viewing on; after that, staff can start a viewing session on a staff computer. See the full 1:43pm card and reply and the 7:27pm source block in section 1. Start happens only at the observed computer by the person signed into it. | N1 (relayed via CoS, 19 Nov 10:51am ET) answered a question about who can start a session: "Doctor or owner only for now". H1 B (relayed via CoS, 19 Nov 1:43pm ET) is later: "'B' = staff can start a viewing session on a staff computer after a doctor or practice owner turns it on." Reading N1 as "who turns viewing on" is this plan's interpretation, not John's wording. John's 7:27pm Q1 "A" (relayed via CoS) resolves it: the plan follows H1 B (a doctor or owner turns viewing on, then staff can start it on their own computer). The question's premise does not match the 9:28am card as recorded above, which is labelled viewing roles. Agents and ungranted members get nothing from this rule. The observed person is the CosmaBot user who starts that session under their own EMR login. An owner/doctor cannot remotely start, renew or extend a session on an employee's computer; a granted doctor or practice owner may only read a session that employee started. A granted doctor or practice owner may view an employee's different-login screen in V0–V2 small practices under the **OPEN-JOHN** practice-size rule in section 1(a); off except for Boxes John names until he defines "clinician" and the count source (interim, John Q4 yes 7:27pm); never remotely start/renew/extend it. Proposed 15-minute bound, visible indicator/staff notice and human-presence gate remain. HIPAA sentence remains unchecked against BAA/counsel, no compliance/coverage claim. |
| N3. Access record after chart purge | **SCOPED** — 24-hour content expiry must not erase access accountability or immutable hash bindings. | Section 6 keeps content-free who-viewed-whose-screen and start/renew/end times; its access-record retention is 6 years from session end per John (NL1); the action at six years is undecided, and this is a product decision, not a compliance finding. No chart/patient/payload data. Expired revisions retain exact content-free payload/hash, bound evidence hashes, decisions/Operation/audit linkage; expiry blocks dependent execution and requires fresh evidence/new revision. Later approved RETENTION update required; purge-failure recovery preserves normal access. |
| NL1. Content-free access-record duration | **DECIDED** — John, relayed via CoS, 19 Nov 9:28am ET: "Keep access records 6 years". | Access records are kept 6 years from session end; the action at six years is not decided. This is John's product decision, not a compliance finding. V0-4 is no longer blocked on this duration. Later approved RETENTION documentation and implementation proofs remain required. |
| NL2. Observation backup expiry | **RESOLVED** — proposed 24-hour backup-copy maximum is unproven. | Before V0-4 prove backup deletion/restore expiry enforcement meets that maximum, or use purge-on-restore before restored observations become accessible. No claim it works today. |
| NL3. Offline SSO lock scope | **RESOLVED** — new offline authority lock is scoped to sign-in-once sessions. | It does not apply to existing non-SSO sessions; existing users retain their current sign-in/access path. |
| NL4. New-device binding | **RESOLVED** — adding a device requires full credential sign-in. | A stolen signed-in phone cannot unlock a new device; automatic unlock is for already registered, qualified bindings. |
| NL5. Clerk realm wording | **RESOLVED** — section 4 uses the native sign-in contract wording. | `clerk.cosmas.ai` / `operational-beta-v1` remains the live profile and is reserved for the later per-practice enrollment design. |

### John's Thursday decisions still open

- OPEN-JOHN: the definition of "clinician" and the count source. Different-login viewing follows the DECIDED interim rule in section 1 (John Q4 "yes", relayed via CoS 7:27pm ET).
- Recording inside OS versus deferred Scribe rebuilding: is V0-8 a new path or a conflict? No default; independent recording-to-note remains “none found.”
- Windows scope: how far V0 Windows goes, including audio. No default.
- Model choice: speech-to-text/drafting providers and explicit optional on-device model yes. No default selection; fake-only processing and dark application LLM until named.
- Locked/unattended/nobody-present reads: no chosen permission; operational default off until John answers, including V0-7.

## 12. Evidence and approval boundary

Versus `main`, draft PR #401 still **adds** this document. r5 is a revision of
that new file on the existing draft branch, not an edit to a file already on
main. Its repository diff is limited to this document. It reports repository
inspection and proposes tests; it does not claim device experiments or runtime
tests passed. Documentation validation covers whitespace and cited source paths;
Fable reviews the final head and CI checks remain intact. No dependencies, code, CI changes,
live credentials, physical test runs, source imports or deployments belong here.

Owner approval is the next boundary after the planning PR. A reviewed plan does
not by itself qualify a platform, activate real-data capabilities, select an
external STT/model provider, or prove locked-screen continuity. Apply the exact
scope of `DL-20261117-01` and its recorded confirmation resolution; preserve every unqualified cell as default off.
