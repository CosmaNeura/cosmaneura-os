import {admitWorkspaceProtocol,workspaceFetch,workspaceProtocolGeneration} from './workspace-protocol';
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CapturePanel } from "./CapturePanel";
import { prepareCapture } from "./capture-api";
import type { CaptureRuntime } from "./capture-runtime";
import type { CaptureFlowSnapshot } from "../../clients/capture/src/flow/controller";
import golden from "../../tests/fixtures/capture_working.json";
import sourceGolden from "../../tests/fixtures/capture_source.json";
import type { CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";
import { readWorking, correctWorking, type WorkingReceipt } from "./capture-working-api";
import { captureDraft, captureNoteTemplates, type CaptureDraft } from "./capture-notes-api";
import { desktopMeetingCaptureAvailable } from "./desktop-capture-runtime";

vi.mock("./capture-api", () => ({ prepareCapture: vi.fn(), CAPTURE_RECOVERY_BUILD: false }));
vi.mock("./capture-runtime", () => ({ openCaptureRuntime: vi.fn() }));
vi.mock("./desktop-capture-runtime", () => ({desktopMeetingCaptureAvailable: vi.fn(() => false)}));
vi.mock("./capture-working-api", async original => ({...await original<object>(),readWorking:vi.fn(),correctWorking:vi.fn()}));
vi.mock("./capture-notes-api", () => ({captureDraft:vi.fn(),captureNoteTemplates:vi.fn(),saveCaptureDraft:vi.fn()}));
const workspace = "00000000-0000-4000-8000-000000000002";
const session = "00000000-0000-4000-8000-000000000003";
const prepared = { status: "prepared" as const, workspace_id: workspace, session_id: session,
  consent_record_id: "00000000-0000-4000-8000-000000000004" };
const identity = { mode: "clerk_jwt" as const, getToken: vi.fn() };
let root: Root, container: HTMLDivElement, runtime: CaptureRuntime;
let snapshot: CaptureRuntime['controller']['snapshot'];
let listener: ((value: CaptureFlowSnapshot) => void) | undefined;
const factory = vi.fn<() => Promise<CaptureRuntime>>();

const nativeState = () => ({phase:"ready",busy:false,input:"built_in" as const,signal:{version:2,signal:null}});

beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  vi.mocked(desktopMeetingCaptureAvailable).mockReturnValue(false);
  snapshot = { state: "ready", statusCode: "ready", sessionId: session, recordedChunks: 0,
    queuedChunks: 90, elapsedSeconds: 0, remainingBudgetSeconds: 900, remainingAuthoritySeconds: 900,
    transcriptionStatus: null, transcript: null };
  listener = undefined;
  runtime = { sourceKind: "synthetic", close: vi.fn().mockResolvedValue(undefined), controller: {
    get snapshot() { return snapshot; },
    subscribe: vi.fn(callback => { listener = callback; callback(snapshot); return () => { listener = undefined; }; }),
    startRecording: vi.fn(async () => { snapshot = { ...snapshot, state: "recording" }; listener?.(snapshot); }),
    stopRecording: vi.fn(async () => { snapshot = { ...snapshot, state: "processing", recordedChunks: 1, elapsedSeconds: 10 }; listener?.(snapshot); }),
    resumePendingWork: vi.fn().mockResolvedValue(undefined),
    acknowledgeGap: vi.fn(async () => { snapshot = { ...snapshot, statusCode: "capture_resume_authority_required" }; listener?.(snapshot); }),
    finishInterruptedCapture: vi.fn().mockResolvedValue(undefined),
    refreshTranscriptionStatus: vi.fn().mockResolvedValue(undefined),
  } };
  factory.mockResolvedValue(runtime);
  vi.mocked(prepareCapture).mockResolvedValue(prepared);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); localStorage.clear(); });
const button = (label: string) => [...container.querySelectorAll("button")].find(value => value.textContent === label)!;
it("shows retained gaps and sends the qualified source to the transcript editor without approving review", async () => {
  const qualifiedSource = sourceGolden.base as CaptureSourceEnvelope;
  snapshot = {...snapshot,state:"complete",sessionId:qualifiedSource.session_id,transcript:qualifiedSource.raw_transcript,qualifiedSource};
  vi.mocked(readWorking).mockResolvedValue(qualifiedSource.working_transcript);
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} correctionsEnabled />));
  await click("Record visit");
  expect(container.querySelector('[aria-label="Capture interruptions"]')?.textContent).toContain("Recording has 1 interruption");
  expect(container.textContent).toContain("Original recording transcript");
  expect(vi.mocked(readWorking).mock.calls.at(-1)?.[5]).toEqual(qualifiedSource);
  expect(runtime.controller.acknowledgeGap).not.toHaveBeenCalled();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});
async function click(label: string) { await act(async () => button(label).click()); }
async function consent() {
  const region = container.querySelector<HTMLInputElement>('input:not([type="checkbox"])')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(region, "US-NY");
    region.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("requires valid regions and a fresh combined consent/start click, then stops explicitly", async () => {
  vi.mocked(prepareCapture).mockRejectedValueOnce({ code: "capture_consent_required" });
  await click("Record visit");
  expect(factory).not.toHaveBeenCalled();
  expect(button("Confirm consent & record").disabled).toBe(true);
  await consent(); await click("Confirm consent & record");
  expect(prepareCapture).toHaveBeenLastCalledWith(workspace, identity, expect.objectContaining({
    all_parties_consented: true, participant_regions: ["US-NY"], method: "verbal_attestation",
  }), expect.any(String), undefined, undefined, undefined);
  expect(container.textContent).toContain("microphone off");
  expect(runtime.controller.startRecording).toHaveBeenCalledTimes(1);
  await click("Stop and upload");
  expect(runtime.controller.stopRecording).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Audio uploaded");
});

it("does not attest on form submission and consumes a double consent click once", async () => {
  vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  await click("Record visit"); await consent();
  await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true})));
  expect(prepareCapture).toHaveBeenCalledTimes(1);
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  const confirm = button("Confirm consent & record");
  await act(async () => { confirm.click(); confirm.click(); });
  expect(prepareCapture).toHaveBeenCalledTimes(2);
  expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
  await act(async () => confirm.click()); // A detached button cannot replay consent.
  expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
});

it("shows and attests virtual modality for selected meeting audio", async () => {
  vi.mocked(desktopMeetingCaptureAvailable).mockReturnValue(true);
  vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  await click("Record visit"); await consent();
  const source = container.querySelector<HTMLSelectElement>('[aria-label="Recording source"]')!;
  await act(async () => { source.value = "desktop_meeting"; source.dispatchEvent(new Event("change", {bubbles: true})); });
  expect(container.querySelector(".capture-defaults")?.textContent).toContain("Online meeting · microphone and meeting audio");
  await click("Confirm consent & record");
  expect(vi.mocked(prepareCapture).mock.calls.at(-1)?.[2]).toMatchObject({modality: "virtual", all_parties_consented: true});
  expect(factory).toHaveBeenLastCalledWith(workspace, session, identity, undefined, "desktop_meeting");
  expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
});

it.each([true, false])("restores the source preference only where meeting capture is available (%s)", async available => {
  const {saveRecordingPreferences} = await import("./recording-preferences");
  const scope = "a".repeat(64);
  saveRecordingPreferences(scope, {regions: "US-NY", language: "en-US", captureMode: "desktop_meeting"});
  vi.mocked(desktopMeetingCaptureAvailable).mockReturnValue(available);
  vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} preferencesScope={scope} />));
  await click("Record visit");
  expect(container.querySelector(".capture-defaults")?.textContent).toContain(available ? "Online meeting" : "In-person visit");
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  await click("Confirm consent & record");
  expect(vi.mocked(prepareCapture).mock.calls.at(-1)?.[2]?.modality).toBe(available ? "virtual" : "in_person");
  expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
});

it.each(["paused", "audio", "resume", "legacy", "transfer", "permission"])(
  "does not turn consent into an automatic start for %s recovery", async recovery => {
    if (recovery === "paused") snapshot = {...snapshot, state: "paused"};
    if (recovery === "audio") snapshot = {...snapshot, recordedChunks: 1};
    if (recovery === "resume") snapshot = {...snapshot, recoveryDecision: "resume_capture"};
    if (recovery === "legacy") runtime.recoveryOnly = true;
    if (recovery === "transfer") runtime.continuePreparation = vi.fn();
    if (recovery === "permission") snapshot = {...snapshot, desktop: {
      phase: "permission_required", coverage: "not_started", trimmedStartMs: 0, trimmedEndMs: null,
    }};
    vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
    await click("Record visit"); await consent(); await click("Confirm consent & record");
    expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  },
);

it("closes a late consent preparation without capture after the account changes", async () => {
  vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  let finish!: (value: CaptureRuntime) => void;
  factory.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await click("Record visit"); await consent(); await click("Confirm consent & record");
  const changedIdentity = {...identity, getToken: vi.fn()};
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={changedIdentity} runtimeFactory={factory} />));
  await act(async () => finish(runtime));
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  expect(runtime.close).toHaveBeenCalledOnce();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("changed");
});

it("offers upload retry after reopening or failure, without interrupting an active automatic upload", async () => {
  snapshot = {...snapshot,state:"uploading",statusCode:"synthetic_preview_uploading",recordedChunks:360};
  await click("Record visit");
  expect(container.textContent).toContain("Uploading audio");
  expect(button("Retry saved work")).toBeUndefined();
  snapshot = {...snapshot,statusCode:"capture_recovered_uploading"};
  await act(async () => listener?.(snapshot));
  expect(button("Retry saved work").disabled).toBe(false);
  vi.mocked(runtime.controller.resumePendingWork).mockImplementation(async () => {
    snapshot = {...snapshot,statusCode:"synthetic_preview_uploading"}; listener?.(snapshot);
  });
  await click("Retry saved work");
  expect(runtime.controller.resumePendingWork).toHaveBeenCalledOnce();
  expect(button("Retry saved work")).toBeUndefined();
  snapshot = {...snapshot,state:"error",statusCode:"synthetic_preview_failed"};
  await act(async () => listener?.(snapshot));
  expect(button("Retry saved work").disabled).toBe(false);
});

it.each([false, true])("can cancel a pending native start and ignores its later failure (combined consent: %s)", async combined => {
  runtime.sourceKind="microphone";runtime.captureMode="native_microphone";runtime.supportsContinuation=true;
  snapshot={...snapshot,native:nativeState()};
  let rejectStart!:(error:Error)=>void;
  vi.mocked(runtime.controller.startRecording).mockImplementation(async()=>{
    snapshot={...snapshot,native:{...nativeState(),phase:"starting"}};
    listener?.(snapshot);
    return new Promise<void>((_resolve,reject)=>{rejectStart=reject;});
  });
  vi.mocked(runtime.controller.stopRecording).mockImplementation(async()=>{
    snapshot={...snapshot,state:"paused",native:{...nativeState(),phase:"paused"}};
    listener?.(snapshot);
  });
  admitWorkspaceProtocol(identity,workspaceProtocolGeneration(identity));
  if (combined) vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  await click("Record visit");
  if (combined) { await consent(); await click("Confirm consent & record"); }
  else await click("Start recording");
  expect(button("Cancel start").disabled).toBe(false);
  await click("Cancel start");
  await act(async()=>rejectStart(new Error("late start failure")));
  expect(runtime.controller.stopRecording).toHaveBeenCalledOnce();
  expect(container.textContent).toContain("Recording paused");
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

it("selects an iPhone input while paused without starting a recording", async () => {
  runtime.sourceKind="microphone";runtime.captureMode="native_microphone";runtime.supportsContinuation=true;
  runtime.controller.selectMicrophoneInput=vi.fn().mockResolvedValue(undefined);
  snapshot={...snapshot,state:"paused",native:{...nativeState(),phase:"paused"}};
  await click("Record visit");
  const select=container.querySelector<HTMLSelectElement>('[aria-label="Recording microphone"]')!;
  await act(async()=>{select.value="bluetooth";select.dispatchEvent(new Event("change",{bubbles:true}));});
  expect(runtime.controller.selectMicrophoneInput).toHaveBeenCalledWith("bluetooth");
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("lets a native recording retry saving even when its cached audio count is zero", async () => {
  runtime.sourceKind="microphone";runtime.captureMode="native_microphone";runtime.supportsContinuation=true;
  vi.mocked(prepareCapture).mockResolvedValue({...prepared,configured_capture:{schema_version:"1.0",language_mode:"en-US"}});
  snapshot={...snapshot,state:"paused",statusCode:"capture_recovery_pending",recordedChunks:0,
    native:{...nativeState(),phase:"paused"}};
  await click("Record visit");
  expect(container.textContent).toContain("saving could not be confirmed");
  expect(button("Retry saving and upload").disabled).toBe(false);
  await click("Retry saving and upload");
  expect(runtime.controller.finishInterruptedCapture).toHaveBeenCalledOnce();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("opens a specific Scribe task without starting capture and keeps its identity on exact retries", async () => {
  const taskBot = {selection: {address: "00000000-0000-4000-8000-000000000005", team_revision: 2}, name: "Visit partner", enabled: true, includeNotebook: true};
  vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"})
    .mockRejectedValueOnce(new Error("lost reply"));
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} taskBot={taskBot} openRequest={1} />));
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  await consent(); await click("Confirm consent & record");
  const original = vi.mocked(prepareCapture).mock.calls[1];
  expect(original[5]).toEqual(taskBot.selection);
  await click("Retry preparation");
  expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(original);
  expect(container.textContent).toContain("Visit partner");
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  await click("Start synthetic capture");
  expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
});

it("retries the exact consent and key after an unconfirmed preparation", async () => {
  vi.mocked(prepareCapture).mockRejectedValueOnce({ code: "capture_consent_required" })
    .mockRejectedValueOnce(new Error("private upstream error"));
  await click("Record visit"); await consent(); await click("Confirm consent & record");
  const first = vi.mocked(prepareCapture).mock.calls[1];
  expect(container.textContent).not.toContain("private upstream error");
  await click("Retry preparation");
  expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(first);
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("restores a paused recording for review without resuming its source", async () => {
  snapshot = { ...snapshot, state: "paused", statusCode: "capture_gap_ack_required", recordedChunks: 1 };
  await click("Record visit");
  expect(button("Start synthetic capture")).toBeUndefined();
  expect(container.textContent).toContain("Saved audio is retained");
  await click("Acknowledge the interruption");
  expect(runtime.controller.acknowledgeGap).toHaveBeenCalledTimes(1);
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("closes the runtime when leaving the workspace, including a transient close failure", async () => {
  vi.mocked(runtime.close).mockRejectedValueOnce(new Error("synthetic stop failure"));
  await click("Record visit"); await click("Start synthetic capture");
  await act(async () => root.unmount());
  expect(runtime.close).toHaveBeenCalledTimes(2);
});

it.each([false, true])("closes a runtime that finishes preparing after unmount (combined consent: %s)", async combined => {
  let resolve: (value: CaptureRuntime) => void = () => {};
  factory.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
  if (combined) vi.mocked(prepareCapture).mockRejectedValueOnce({code: "capture_consent_required"});
  await click("Record visit");
  if (combined) { await consent(); await click("Confirm consent & record"); }
  await act(async () => root.unmount());
  await act(async () => resolve(runtime));
  expect(runtime.close).toHaveBeenCalledTimes(1);
  expect(runtime.controller.subscribe).not.toHaveBeenCalled();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("checks an uploaded recording and shows source speech as text with speaker/time provenance", async () => {
  snapshot = { ...snapshot, state: "processing", recordedChunks: 1 };
  vi.mocked(runtime.controller.refreshTranscriptionStatus).mockImplementationOnce(async () => {
    snapshot = { ...snapshot, state: "complete", transcript: {
      id: "00000000-0000-4000-8000-000000000005", session_id: session,
      created_at: new Date().toISOString(), language_code: "en", stt_provider: "synthetic",
      segments: [{ content: "Invented visit <script>not executable</script>", start_ms: 62000, end_ms: 65000,
        speaker_id: "speaker-1", speaker_role: "clinician", confidence: null }],
    } };
    listener?.(snapshot);
  });
  await click("Record visit");
  await click("Check transcript");
  expect(container.textContent).toContain("Transcript available");
  expect(container.textContent).toContain("Clinician · 1:02");
  expect(container.textContent).toContain("Invented visit <script>not executable</script>");
  expect(container.querySelector("script")).toBeNull();
  expect(button("Start synthetic capture")).toBeUndefined();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

async function correctedPanel() {
  snapshot={...snapshot,state:"complete",transcript:golden.raw as never};
  vi.mocked(readWorking).mockResolvedValue(golden.base as WorkingReceipt);
  vi.mocked(correctWorking).mockResolvedValue(golden.second as WorkingReceipt);
  vi.mocked(captureNoteTemplates).mockResolvedValue([{schema_ref:"schema",note_type:"Visit",field_names:["Plan"]}]);
  const draft:CaptureDraft={session_id:session,scribe_source_id:golden.raw.id,source_sha256:"a".repeat(64),schema_ref:"schema",
    transcript_ref:"transcript",note_ref:"note-one",status:"draft",note_type:"Visit",fields:{Plan:"Original saved note."},field_order:["Plan"],
    note_sha256:"b".repeat(64),created_at:"2026-09-17T10:00:00Z",review_required:true};
  vi.mocked(captureDraft).mockResolvedValue(draft);
  await act(async()=>root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory}
    notesEnabled correctionsEnabled onReviewDraft={vi.fn()}/>));
  await click("Record visit");return draft;
}
async function textarea(label:string,text:string){await act(async()=>{
  const input=container.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`)!;
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,text);
  input.dispatchEvent(new Event("input",{bubbles:true}));
});}
it("coordinates transcript and note editing without dropping either editor's text",async()=>{
  await correctedPanel();await click("Correct transcript");await textarea("Transcript segment 1","My unsaved transcript correction.");
  expect(button("Edit draft").disabled).toBe(true);expect(button("Use saved draft for review").disabled).toBe(true);
  await click("Discard transcript edits");await click("Edit draft");await textarea("Draft Plan","My unsaved note edit.");
  expect(button("Save transcript corrections").disabled).toBe(true);expect(button("Check current transcript").disabled).toBe(true);
  expect(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Draft Plan"]')!.value).toBe("My unsaved note edit.");
});
it("refreshes the note after a confirmed correction and retains the original transcript",async()=>{
  const draft=await correctedPanel();await click("Correct transcript");
  await textarea("Transcript segment 1",golden.second.working_source.segments[0].content);
  vi.mocked(readWorking).mockResolvedValue(golden.second as WorkingReceipt);
  vi.mocked(captureDraft).mockResolvedValue({...draft,status:"not_prepared",source_sha256:"c".repeat(64),
    note_ref:null,fields:null,field_order:null,note_sha256:null,created_at:null});
  await click("Save transcript corrections");
  expect(button("Prepare draft note").disabled).toBe(false);expect(button("Edit draft")).toBeUndefined();
  expect(container.querySelector('details[aria-label="Source transcript"]')!.textContent).toContain(golden.raw.segments[0].content);
});

it("prepares recovery without starting capture and retains the explicit Start action", async () => {
  snapshot = { ...snapshot, state: "paused", statusCode: "capture_gap_ack_required", recordedChunks: 1 };
  vi.mocked(runtime.controller.acknowledgeGap).mockImplementation(async () => {
    snapshot = { ...snapshot, state: "ready", statusCode: "capture_resume_ready", recoveryDecision: "resume_capture" };
    listener?.(snapshot);
  });
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} recoveryEnabled />));
  await click("Record visit"); await click("Prepare to resume");
  expect(runtime.controller.acknowledgeGap).toHaveBeenCalledTimes(1);
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  expect(container.textContent).toContain("The interruption is saved");
  await click("Start synthetic capture");
  expect(runtime.controller.startRecording).toHaveBeenCalledTimes(1);
});

it("retries an unconfirmed finish decision without changing it to resume", async () => {
  snapshot = { ...snapshot, state: "paused", statusCode: "capture_gap_ack_required", recordedChunks: 1 };
  vi.mocked(runtime.controller.finishInterruptedCapture).mockImplementationOnce(async () => {
    snapshot = { ...snapshot, statusCode: "capture_recovery_unconfirmed", recoveryDecision: "finish_capture" };
    listener?.(snapshot);
    throw new Error("discarded reply");
  });
  await act(async () => root.render(<CapturePanel workspaceId={workspace} identity={identity} runtimeFactory={factory} recoveryEnabled />));
  await click("Record visit"); await click("Finish this recording"); await click("Retry recovery");
  expect(runtime.controller.finishInterruptedCapture).toHaveBeenCalledTimes(2);
  expect(runtime.controller.acknowledgeGap).not.toHaveBeenCalled();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});


it("keeps Stop available and prevents a new recording while workspace compatibility is blocked", async () => {
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');
  try {
    admitWorkspaceProtocol(identity,workspaceProtocolGeneration(identity));
    await click('Record visit');await click('Start synthetic capture');
    vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:426,headers:{'X-Cosmas-Workspace-Protocol':'1'}})));
    await expect(workspaceFetch(identity,'https://api.example.invalid/workspaces',{headers:{'X-Cosmas-Workspace-Protocol':'1'}})).rejects.toMatchObject({status:503});
    await click('Stop and upload');expect(runtime.controller.stopRecording).toHaveBeenCalledOnce();
    snapshot={...snapshot,state:'ready'};await act(async()=>listener?.(snapshot));
    await click('Start synthetic capture');expect(runtime.controller.startRecording).toHaveBeenCalledOnce();
    expect(runtime.close).not.toHaveBeenCalled();
  } finally {vi.unstubAllGlobals();vi.unstubAllEnvs();}
});


it("offers finish-only recovery for an older configured recording", async () => {
  runtime.recoveryOnly = true; runtime.canFinishRecovery = true;
  vi.mocked(prepareCapture).mockResolvedValue({...prepared,configured_capture:{schema_version:"1.0",language_mode:"en-US"}});
  snapshot = {...snapshot,state:"paused",recordedChunks:1};
  await click("Record visit");
  expect(button("Prepare to resume")).toBeUndefined();
  expect(button("Start recording")).toBeUndefined();
  await click("Finish this recording");
  expect(runtime.controller.finishInterruptedCapture).toHaveBeenCalledOnce();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it("keeps an older empty preparation visible without a Start action", async () => {
  runtime.recoveryOnly = true;
  await click("Record visit");
  expect(button("Start synthetic capture")).toBeUndefined();
  expect(container.textContent).toContain("older recording preparation is retained");
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});

it('continues an empty preparation without recording until a separate Start',async()=>{
  const original=runtime;
  const current:CaptureRuntime={...original,recoveryOnly:false};
  original.recoveryOnly=true;original.continuePreparation=vi.fn().mockResolvedValue(current);
  await click('Record visit');
  expect(button('Start synthetic capture')).toBeUndefined();
  await click('Continue preparation');
  expect(original.continuePreparation).toHaveBeenCalledOnce();
  expect(current.controller.startRecording).not.toHaveBeenCalled();
  expect(button('Continue preparation')).toBeUndefined();
  admitWorkspaceProtocol(identity,workspaceProtocolGeneration(identity));
  await click('Start synthetic capture');
  expect(current.controller.startRecording).toHaveBeenCalledOnce();
});

it('keeps a failed preparation transfer retryable',async()=>{
  runtime.recoveryOnly=true;runtime.continuePreparation=vi.fn().mockRejectedValue(Error('interrupted'));
  await click('Record visit');await click('Continue preparation');
  expect(button('Continue preparation')).toBeDefined();
  expect(button('Start synthetic capture')).toBeUndefined();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});


it.each(["paused","ready"] as const)("can finish an older %s recording with an earlier Resume decision",async state=>{
  runtime.recoveryOnly=true;runtime.canFinishRecovery=true;
  snapshot={...snapshot,state,recordedChunks:1,recoveryDecision:"resume_capture"};
  await click("Record visit");
  expect(button("Prepare to resume")).toBeUndefined();
  expect(button("Start synthetic capture")).toBeUndefined();
  await click("Finish this recording");
  expect(runtime.controller.finishInterruptedCapture).toHaveBeenCalledOnce();
  expect(runtime.controller.acknowledgeGap).not.toHaveBeenCalled();
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
});
