# Extension and desktop: V0 flight plan

Status: proposed; docs only; implementation requires John's approval of this PR.
Evidence baseline: `5d8e2f53` on `main`, inspected November 17, 2026.
Decision evidence: `DL-20261117-01` and its confirmation resolution
`DL-20261117-02` are recorded in [owner-decision PR #400](https://github.com/CosmaNeura/cosmaneura-os/pull/400),
head `d965d3595a20bbbcc7fd2479ccc581324489253b`,
[decision log at that head](https://github.com/CosmaNeura/cosmaneura-os/blob/d965d3595a20bbbcc7fd2479ccc581324489253b/docs/DECISION_LOG.md#L436).
That PR is open and is not yet in the code baseline. The owner's instruction
here to follow DL-20261117-01 governs this plan; the recorded follow-up resolves
its two historical confirmation markers. This PR does not copy or modify the
three decision documents.
Nothing here activates an external capability, installs software, changes
credentials, or authorizes a merge. All development and qualification data is
invented. Stop after opening the planning PR and wait for the owner.

## 1. Outcome and bounds

V0 lets an authorized practice member ask about an explicitly registered
computer and receive a dated answer from its permitted EHR page observations.
A packaged browser extension reads a small set of supported pages; the desktop
app supplies device identity, credential custody, status and the cloud link.
An extension-only installation can read supported pages without a desktop app,
with narrower availability and security guarantees. Both use the existing Box,
ports, work surface and F-8 queue. Neither is a general remote desktop.

Start with one synthetic system and one screen (appointment list), then a
patient-context screen. Read only what is already loaded. V0 does not click,
type, navigate, log in, dismiss prompts, prescribe, sign, submit, or prevent
an EMR from logging out. A screen pack cannot introduce those abilities.
Native EMR windows, canvas-only applications, inaccessible frames and remote
desktop pixels are unsupported by a DOM reader. Report that limit rather than
adding OCR or OS accessibility control implicitly.

An independent recording-to-note capability is a separate, gated V0 slice.
DL-20261117-02 clarifies: “Yes, maybe for initial beta we rely on legacy but
going forward we need independent recording and notes.” Record that beta
exception honestly; do not label a Core-backed note independent. Scribe stays
a separate product sharing the recorder, and new Scribe sign-ups use CosmaBot
identity. Plan the shared recorder interface here; no live identity change.
Do not make page reading depend on transcription or silently send audio to
Track A. Platform-specific device/credential/capture code stays behind interfaces
from the first Mac slice, with Windows work starting in week three.

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
| Sign-in | `clients/desktop/auth-session.mjs`, `clients/desktop/auth-helper-client.mjs`, `clients/desktop/spawn-auth-helper.mjs`, `clients/desktop/auth-ipc.mjs`; `clients/apple/native-auth/Desktop/main.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift`, `clients/apple/native-auth/Sources/CosmasNativeAuth/KeychainAccessBlock.swift`; `src/cosmas_os/api/auth.py` | Shared identity, separate product authority. Tokens stay out of desktop preload/renderer; session revisions fence requests. Keychain background access must fail without summoning authentication UI. Do not change shipped identity or Keychain names. |
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
installed with the desktop app. Allow only the exact signed/released extension
IDs. Keep the host a bounded relay to the owned main process, with strict
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
Already observed history follows existing retention and access policy; it does
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
Authenticate through the same Clerk identity using an approved extension login
flow (authorization code/PKCE where supported); backend grants remain separate
from identity membership. Enroll a browser-profile endpoint under the Box with
an extension-only capability. Use short-lived read-scoped access tokens held
outside the page/content script; persist no long-lived human bearer or EMR
credentials. Require reauthentication when renewal cannot be done safely.
Validate extension ID, exact cloud origin, profile binding and current grants.

The extension sends minimized observations directly to the OS backend over
HTTPS. There is no local daemon, raw desktop status, native audio, wake control,
or assurance that it stays available after the browser exits. Service-worker
suspension and browser tab discard may delay reads. It cannot assert OS lock
state; report `unknown` rather than inventing one.

Security trade-off: fewer native components and easier installation, but cloud
read authority exists in a browser profile with weaker custody than native
Keychain/Windows credential storage. Profile theft and malicious extension
updates matter more. Constrain permissions, token lifetime, observation scope
and storage; clear session credentials on sign-out. A compromised browser can
forge page observations in either mode. Neither mode uploads cookies or
credential-store contents. No automatic mode change transfers permissions.

### Optional on-device model boundary

DL-20261117-01 item 4 permits a small desktop model for perception (screen,
patient and change recognition), protection (PHI minimization, mismatch warnings
and later pre-fill checks), and short on-screen staff help (missing/changed
fields, call notes, answers about visible content). V0 works with deterministic
selectors first; a model is optional and separately default off under proposed
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
GPT-5.6 SOL endpoint. Device compliance checks remain V2; this model is not a
security-monitoring feature.

## 5. Screen packs are versioned data, never remote code

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
Stage a new version on synthetic fixtures, then a small enabled cohort.
Revocation stops new reads; rollback selects a prior still-approved immutable
pack. An offline cache may use an unexpired approved pack, but cannot bypass
revocation checks to accept cloud work. Layout drift produces a visible
unsupported/partial result and diagnostic codes, not guessed field values.

## 6. Page read to observation to existing F-8 work

1. An already granted endpoint reads a supported loaded page in the signed-in
   user's own browser session. A human explicitly enables the read-only
   observation session; passive page-change observation can continue while that
   grant/session is valid. Phone requests stage a fresh-read request against this
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
4. Extend the closed observation contracts and dispatch additively. Do not
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
7. Reads/observations need no new human approval merely to occur (D-008).
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

## 7. Phone to cloud to desktop and back

The practice owner designates one registered endpoint as the **anchor computer**:
the default machine for practice-level questions. It belongs to the existing
Box; multiple physical computers do not create multiple Boxes. Selection is an
explicit, audited owner change. Do not switch anchors automatically to whichever
employee is active. A remote Mac mini can be the first test anchor, but is not
evidence that every Mac stays awake or signed into an EMR.

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
| Provider/staff with explicit device-read and clinical-context grants | Ask about the anchor or a named granted endpoint within their Box and allowed patient/work context. A shared computer's active user's session does not transfer that user's private grants to the caller. |
| Agent principal | Read only for an authorized task under its installed capability and human/context scope; no impersonation, grant expansion or self-approval. |
| Other Box, removed member, ungranted member or support/coding agent | Deny endpoint discovery, status and clinical answers; owning a phone or knowing a device ID supplies no authority. |

The phone receives a minimized authorized answer, source time/coverage,
safe endpoint label, availability and an existing work/review card if needed.
Patient-specific details reach it only after current patient/workspace grants
are checked again at response time. Do not send raw DOM, desktop screenshots,
other users' charts, local paths, cookies, tokens, audio or an unrestricted
device history. No PHI in notification previews; V0 can use the existing open
app response flow because push notifications remain deferred. Revocation
during a read suppresses the reply and leaves a safe unavailable result.

## 8. Behavior by computer state

OS lock, sleep, EMR timeout and app/browser availability are separate facts.
Missing heartbeats cannot distinguish sleep from a broken network or app exit.
No current repository evidence qualifies background page reads on locked Mac
or Windows; the table states proposed behavior to test, not shipped behavior.

| State | Paired desktop path | Extension-only path | Phone result and limits |
| --- | --- | --- | --- |
| In use; browser and EMR session active | Read loaded supported pages without stealing focus; send new observation. Existing native recording may run only after consent/explicit start and its own lease checks. | Read permitted loaded tabs while browser execution is available. | Fresh answer for permitted context. A chart change mid-read invalidates identity binding; no automatic navigation to another chart. |
| Screen locked; computer awake | App cloud transport and noninteractive DOM reads may continue if browser, grants, EMR session and credential access remain valid. Screen-pixel capture is not required. Keychain interaction-required stops authenticated work; do not unlock or prompt behind the lock. | Loaded-page reads may continue while browser runs, but tab throttling/discard and token expiry can stop them. OS lock state is unknown. | New source timestamps prove continuity only if a new read succeeds. Otherwise dated last-seen data and “fresh read unavailable.” Do not claim cached data is a fresh read. New recording cannot start remotely; existing audio lock behavior is separately qualified. |
| EMR idle logout or timeout (locked or unlocked) | Detect supported timeout/login marker and stop clinical reads. App's own cloud link may remain live. | Same detection if browser executes; otherwise last-known status only. | “Sign in on Front desk Mac to refresh,” with prior source time. Old DOM may remain visible after logout: never treat it as current session data. No credential injection or keepalive activity. Authorized backend EHR API reads have separate connection status and may work independently. |
| Asleep/hibernating, app exited or network unavailable | No new local page reads or promised recording continuation. On wake/relaunch, revalidate session, pairing, pack, request expiry and chart identity. | No reads if browser/OS cannot execute; browser exit is sufficient even without sleep. | Cloud work/history and explicitly dated last-seen answer remain accessible under current grants. Pending read expires visibly. V0 does not wake/unlock the computer or revive an EMR session. |

If locking causes browser suspension on a qualified configuration, narrow its
advertised support to “awake and unlocked” and prefer an authorized backend
read API for locked availability. Do not weaken the lock to make the test pass.

## 9. Small, separately releasable V0 pull requests

Each implementation PR is a later approval-dependent change. Proposed switches
below do not exist yet; all default false on server and relevant client, with
an explicit Box allowlist. Unknown/omitted switch values refuse activation.
Disabling a switch stops new admission/dispatch, retains history and lets an
already accepted receipt reconcile without starting new work. No switch grants
EMR writes, real-data processing or production activation by itself.
The slices are dependency order, not a promise to finish them in two weeks:
Windows interface/host work starts in week three even if later Mac slices or
independent recording are still in progress.

| Slice / independent release | Deliverable | Tests required in that PR | Default-off switch / rollback |
| --- | --- | --- | --- |
| V0-1: data contracts and fake observation | Screen-pack schema, bounded packaged-interpreter contract and synthetic page fixtures behind EHR read ports; no browser installation | Unsupported version/opcode, oversized pack, hash/origin mismatch, ambiguous layout, partial lists, malicious page instructions and patient mismatch all refuse correctly. Golden allowed fixtures and negative mutations. | `screen_pack_reads_enabled`; disable pack selection, retain pinned evidence. |
| V0-2: endpoint registration/status | Additive Box-scoped endpoint records, device key binding, last-seen timestamps and anchor selection in existing settings | Allowed/denied Box/member/device matrix; stale/skewed times, duplicate enrollment, revoked key, anchor replacement and concurrent owner edits; restart retains same endpoint. | `desktop_endpoint_presence_enabled`; stop presence writes and new enrollment without deleting history. |
| V0-3: paired relay | Native-messaging host, strict packaged-extension allowlist, explicit pairing and revocation, one synthetic read round trip | Rogue page/extension/profile, challenge replay/expiry, malformed/oversized messages, sign-out in flight, relay crash/restart and lost receipt retry; existing desktop sandbox/auth tests. Mac install/signing verification outside Linux CI. | `desktop_extension_pairing_enabled`; unpair/refuse new relay traffic, preserve app sign-in and recording. |
| V0-4: observation custody and F-8 | Backend ingress/browser adapter, accurate additive provenance, minimized projections and deduplicated read-review Ticket/ActionRevision | Cross-Box/patient refusals, revocation before/after I/O, altered hash/key conflict, duplicate ingress after response loss, worker crash, no duplicate ticket/operation, edited revision invalidates approval, source text cannot invoke tools. | `browser_page_observations_enabled`; block ingress/new producer work; existing queue and historical receipts remain. |
| V0-5: extension-only fallback | Separate browser endpoint enrollment and direct HTTPS observation flow; one supported screen | PKCE/state/session binding, token expiry/sign-out, malicious content-script messages, forbidden origin, worker suspension/tab discard/browser exit and idempotent reconnect. Verify no desktop/cloud human token reaches page code. | `extension_only_reads_enabled`; refuse new fallback sessions; never downgrade paired sessions automatically. |
| V0-6: phone round trip | Named/anchor target in existing Messages/Workspace action flow, status and dated answers; no new navigation surface | Full caller matrix, active-user versus caller grants, stale snapshot, anchor changed mid-request, lost desktop connection, expiry on wake, membership revoked before reply and private-source non-disclosure; phone/desktop UX parity. | `phone_computer_reads_enabled`; remove new read action and stop its dispatch; normal conversations remain. |
| V0-7: locked-session qualification | Noninteractive passive observation and accurate timeout/state results after Mac experiments | Fresh read after OS lock, denied credential interaction without UI, browser throttle/discard, timeout leaves stale DOM, sleep/wake request expiry and no focus/login/keepalive actions; record measured EMR idle logout. | `background_page_reads_enabled`; revert to explicit foreground reads, preserve cached time labels. |
| V0-8a: independent audio transcription | OS-owned port and immutable transcript custody using local fake, existing encrypted recordings and same operation identity; no legacy calls | Corrupt/truncated audio, consent/lease expiry, duplicate upload/receipt loss, processor crash/recovery, revocation, model outage, no hidden Core/legacy egress; fake output visibly synthetic. | `independent_recording_transcription_enabled`; refuse new transfer, retain recoverable encrypted audio. External processor stays separately dark. |
| V0-8b: independent note draft | Exact transcript-to-draft linkage and human review in existing work/notes flow; fake first | Changed transcript invalidates draft approval; partial/gapped transcript, wrong patient, duplicated retry, unauthorized reviewer, no auto-sign/submit and no legacy fallback. | `independent_recording_note_draft_enabled`; retain transcript/draft history, stop new drafting. |
| V0-optional: local perception/help | Small approved-lineage on-device model behind the permitted desktop interface; no clinical drafting | Wrong patient/change detection, unverified consequential output, unsupported weight lineage, absent model and memory/CPU exhaustion; deterministic verification or escalation, never clinical judgment | `desktop_local_perception_enabled`; use deterministic selectors and cloud reasoning, retain existing observations. |
| V0-9: Windows qualification | Minimal Windows native host/credential adapter and installers; no reuse claim for Mac-only Swift audio | Chrome/Edge native host identity/registry/install validation, Windows credential failure, lock/logoff/RDP disconnect/tab discard/sleep, remote VM reconnect and same request recovery. Existing browser contracts must remain identical. | `windows_extension_desktop_enabled`; Windows capability remains unsupported until the platform matrix passes. Windows native audio is a later separate slice. |

For every new fence test both sides and remove/invert the guard to demonstrate
that its proving test fails. Name actual collected CI jobs in each later PR;
use existing backend suite wrappers, web tests and desktop Node tests. Native
Mac/Windows device tests need attached synthetic run logs; Linux CI alone is
not proof. Follow `docs/review-policy.md` for implementation plan review and
required final-head review. Do not route messages to another Codex task.

## 10. Three-week qualification plan

Weeks count from approval, with later capability activation still explicit.
Use synthetic EHR pages/accounts and invented appointments throughout. Human
operators may qualify an authorized EMR's idle behavior without putting real
patient content into coding-agent evidence. If credentials or physical hardware
are unavailable, report the unrun cells; do not fabricate qualification.

### Week 1: local Mac and remote Mac mini

Inventory macOS/browser/extension/app versions, power policy, browser background
policy, permissions and whether the remote session is console, screen sharing
or another session. Record no real device/tenant identifiers in the report.
Use the Mac mini as the synthetic practice anchor, and a local Mac as a second
endpoint. Compare paired mode and extension-only mode. Prove explicit pairing,
wrong-profile denial, current grants, one appointment observation, phone reply,
partial coverage and pack rollback. Confirm reads do not move focus or modify
the EMR. Capture baseline request latency and observation age.

Mandatory locked-screen test: start with an authenticated loaded synthetic
appointment page and valid grants; read once; lock the OS through the normal
lock action while keeping it awake; disconnect the remote viewer for the mini.
From the phone request a read at 1, 5 and 15 minutes. An approved synthetic
fixture updates its own visible timestamp/row revision after lock without
extension-driven navigation. Require a new post-lock source hash/revision and
`observed_at`, matching the fixture, plus cloud receipt time. A heartbeat or
cached snapshot alone fails. Verify the OS remains locked, no authentication UI
appears and no key/cookie/screenshots leak. Repeat with tab backgrounded,
minimized window and browser discard. Log successes and unsupported states for
each mode; lock never authorizes a new chart or privileges.

### Week 2: Mac failure/recovery and EMR idle logout

Repeat lock tests on both Macs with token refresh due, noninteractive Keychain
access refused, network loss, desktop/extension restart, EMR timeout and actual
sleep/wake. Remote-viewer disconnect is not sleep or lock; test each independently.
Prove duplicate replies/reconnects yield one observation receipt and F-8 item;
expired requests never run against a different chart after unlock. Exercise
synthetic audio consent/stop/recovery separately from page reading; native audio
continuity under lock is a measured capability, never assumed from DOM success.

Measure EMR idle logout with at least three trials per tested configuration:
unlocked idle, locked-awake idle, locked-awake with bounded read-only DOM
observations, and remote-session-disconnected. Set `t0` at the last human EMR
interaction. Record time until login/timeout marker and time until the next
attempted read is refused, sampling at a known interval (e.g. 30 seconds) and
reporting uncertainty. Include browser/EMR version and policy, trial range and
median. Record whether passive reads changed logout timing compared with the
idle control. Do not send keepalives or weaken EMR timeout. If a page does not
expose logout reliably, classify freshness as unverified until an authorized
API or human reauthentication confirms it. The output is a support matrix and
measured logout interval, not a promise of indefinite unattended access.

### Week 3 onward: Windows PCs and Azure Windows VM

Repeat the same synthetic contract and failure matrix on physical Windows PCs
with Chrome and Edge, then on an Azure Windows VM with an interactive browser
session. Azure supplies test compute, not a second Box/cloud architecture.
Separate workstation lock, user logoff, RDP disconnect, RDP session timeout,
VM stop/deallocation and power sleep. A disconnected RDP session can retain
processes; a logged-off session cannot. Measure rather than equate these states.
Run the post-lock changing-fixture read and EMR idle-logout experiment again.
Test Windows credential custody, native-messaging registration/replacement,
browser profile boundaries, reconnection, session expiry and permissions denied.
Do not relax OS/EMR security settings to obtain continuity. No RDP credentials
or connection details reach the phone.

Before enabling any cell, require zero unauthorized disclosures/EMR mutations,
correct source age and partial-coverage labels, deterministic failure/recovery,
one F-8 item for replayed work, and logged post-lock fresh reads where claimed.
Collect success rate and p50/p95 request latency over at least 30 synthetic
requests per supported cell; report results rather than invent a production SLO.
An unqualified platform/mode stays off. Retest affected cells after browser,
OS, pack/interpreter or credential-custody changes.

## 11. Locked-decision conflicts and smallest compatible alternatives

This table checks both the desired behavior and tempting implementations.
It does not silently override a locked decision. No fatal counterexample to
the existing authority/queue/data rules has been established.

| Decision / rule | Conflict or unresolved tension | Smallest compatible alternative |
| --- | --- | --- |
| `DL-20261117-01` / `DL-20261117-02` | Decision documents are in open PR #400 rather than baseline main; historical confirmation markers must not be treated as unresolved owner intent. | Apply the exact recorded rulings and follow-up, cited above, under this task's direct instruction. Keep this PR to one planning file and let the decision-document PR merge separately. |
| D-001/D-002/D-012; repository boundary | Reusing legacy service capture as an “independent” recording-to-note path or importing Track A source/data would violate independence and Track A ownership. | Reuse this repository's owned capture boundaries; build an OS-owned fake-first transcription/draft slice. Any future Core integration is separately named and versioned, never a hidden fallback. Shared Clerk identity is the accepted exception, not shared app authority. |
| Canonical “Browser automation” deferral and `AGENTS.md` browser-automation prohibition | DL-20261117-01 item 1 supersedes the blanket browser prohibition for a read-only extension in the signed-in user's own session. Unattended automation and agent-held EMR logins remain deferred; a locked-screen claim cannot imply either. | Use explicitly enabled passive loaded-page observation only, default off. No automatic navigation, new login or privilege expansion. If the human session expires or the page is inaccessible, return dated evidence or use a separately authorized EHR read API. |
| Canonical “Rebuilding the existing Scribe inside OS” deferral | A complete new transcription/drafting feature exceeds simple extension reuse and the original ArtifactChase slice. | DL-20261117-01 item 6 and DL-20261117-02 authorize the independent direction and allow possible initial-beta legacy reliance. Keep page V0 separately releasable and recorder shared with separate Scribe; implement independent cloud note processing behind explicit gates, without migrating or replacing Track A. |
| D-003 and D-011; “Second EHR” deferral | General screen packs could silently activate multiple EHRs or expand v1 beyond insurance ArtifactChase. | One synthetic system/screen first; each vendor, real-data port rung and clinical capability separately activated. Preserve existing vendor paths without declaring blanket production browser support. No pricing/payment-recovery changes. |
| D-004 | Calling every physical PC a practice “computer” might create one Box per device. | One logical Box; endpoint IDs and one selected anchor beneath it. Explicit Box scope at cloud/shared boundaries. |
| D-005/D-007 and shared identity `DL-20260927-01` | Remote callers could inherit the active employee's EMR authority, or agents could authenticate/approve as humans. | Separate endpoint, human and agent identities; intersect caller/work/patient/device grants and deny wins. Shared Clerk identity preserves separate OS product permissions. No agent login, signing or self-approval. |
| D-008/D-009 | Extension tasks, phone commands or relay retries could become a second queue or repeat work after lost replies. | Existing F-8 Ticket/revision/Operation and Postgres intent; transport correlation only. Exact hashes, stable retries and explicit unconfirmed outcomes. Reads remain auditable without inventing approval for every observation. |
| D-010/D-011, PHI/credential boundary | A default-on reader/audio processor or broad raw-screen upload would activate external data handling without its gates. | Default-off client/server/Box activation, minimized typed observations, explicit capability prerequisites and no coding-agent access to live content. Credentials stay native/browser-private; all test/report content synthetic. |
| D-013 and `DL-20261023-01` | Device dashboards, extension inboxes or phone remote-control UI could sprawl into a second presentation/action layer. | Existing settings for connection/anchor setup and existing Messages/Workspace work cards with plain availability labels. Preserve shared session/action state and per-device presentation preference. No new push/camera/live-dictation feature. |
| Desktop sandbox and credential controls (implementation evidence) | Reusing capture permission to grant page control, exposing main IPC to page JavaScript, or allowing hidden Keychain prompts would weaken proven boundaries. | Separate bounded native-messaging capability; exact extension allowlist; no generic IPC or prompt behind lock. Failure is unavailable plus recovery after explicit human interaction. |
| DL-20261117-01 item 2 | A “helpful” form-fill extension could expand V0 to editing visible EMR fields. | Form fill is V1 only, provider-triggered by explicit click, visible fields only; never click Save, Submit, Send or Sign. V0 packs/interpreter contain no fill operation. |
| DL-20261117-01 item 3 | Phone-originated prescription/message actions could bypass the desktop and human prescriber. | Stage desktop work only; never send from phone automation. CosmaBot never signs or transmits prescriptions. V0 has no prescription action. |
| DL-20261117-01 item 4; runtime model invariant | A local model might draft clinical notes, select codes, make clinical judgments or use prohibited weights. | Restrict local optional model to the three permitted functions, code-verify or escalate consequential outputs, reject Chinese-origin weights/derivatives and retain cloud reasoning. No Cursor endpoint runtime dependency. |
| DL-20261117-01 items 5, 7 and 8 | Mac-first work could become Mac-only, fold separate Scribe into CosmaBot, change sign-up identity live, or add device posture monitoring. | Mac weeks 1–2, Windows from week 3 with platform interfaces; separate Scribe shares recorder and planned CosmaBot sign-up identity. No live identity changes in this task. Compliance checks remain V2 and are named accordingly. |
| D-009 and architecture style | Persistent unattended access could motivate Kafka, Kubernetes, event sourcing, consumer messengers or another cloud/IdP. | Existing modular monolith/Postgres plus outbound HTTPS relay and current identity. Azure Windows VM is a synthetic test endpoint only. |
| Locked/sleep/timeout expectations | “Read anytime” has fatal technical counterexamples: asleep OS cannot execute, EMR logout removes session authority, inaccessible DOM cannot supply missing pages. These are availability limits, not reasons to override security decisions. | Dated last-seen snapshot, explicit fresh-read refusal and authorized backend API where available. Human unlock/relogin is recovery; V0 does not disable locks/timeouts. |
| `DL-20261030-01` autonomy versus this task and review policy | DL-20261117-01 item 10 supersedes October 30 production/store/live identity autonomy for this workstream. This task also stops at the docs-only PR. | Add this one document, commit/push/open its PR, stop and wait for John. No production deploys, store submissions or live identity changes without explicit task instruction. Later high-risk slices follow plan review and exact-head checks; CI/rulesets remain intact. |

## 12. Evidence and approval boundary

This PR adds only this file. It reports repository inspection and proposes
tests; it does not claim device experiments or runtime tests passed. Validate
Markdown whitespace and every cited file path before pushing, and verify the
PR diff contains exactly this new document. No dependencies, code, CI changes,
live credentials, physical test runs, source imports or deployments belong here.

Owner approval is the next boundary after the planning PR. A reviewed plan does
not by itself qualify a platform, activate real-data capabilities, select an
external STT/model provider, or prove locked-screen continuity. Apply the exact
scope of `DL-20261117-01` and its recorded confirmation resolution; preserve every unqualified cell as default off.
