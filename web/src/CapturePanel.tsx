import { readRecordingPreferences, recordingRegions, saveRecordingPreferences } from "./recording-preferences";
import { CreatorReviewPanel } from "./CreatorReviewPanel";
import type { CreatorReviewView } from "../../clients/scribe-review/creator-review-api";
import type { CaptureLanguage, PreparedCapture } from "./capture-api";
import {requireWorkspaceProtocol} from './workspace-protocol';
import { useEffect, useRef, useState } from "react";
import type { CaptureFlowSnapshot } from "../../clients/capture/src/flow/controller";
import type { AuthenticatedWorkspaceIdentity, CaptureBotSelection, CaptureTaskBot } from "./workspace-api";
import { CAPTURE_RECOVERY_BUILD, prepareCapture, type CaptureAttestation } from "./capture-api";
import { openCaptureRuntime, type CaptureRuntime, type CaptureRuntimeFactory } from "./capture-runtime";
import "./capture-panel.css";
import { CaptureDraftPanel } from "./CaptureDraftPanel";
import type { CaptureDraft } from "./capture-notes-api";
import { CaptureTranscriptEditor } from "./CaptureTranscriptEditor";
import type { WorkingReceipt } from "./capture-working-api";
import { CaptureGapNotice } from "./CaptureGapNotice";
import { sourceGapReview } from "./capture-gap-review";
import {desktopMeetingCaptureAvailable} from './desktop-capture-runtime';
import {microphoneInputs,type MicrophoneInput} from '../../clients/capture/src/native/microphone-input';
import type { SavedScratchpad } from "./notebook-source";
import { CaptureInputSignal } from "./CaptureInputSignal";

type Preparation = { attestation: CaptureAttestation | null; key: string; bot?: CaptureBotSelection; language?: CaptureLanguage };
const idle: CaptureFlowSnapshot = { state: "idle", statusCode: "idle", sessionId: null,
  recordedChunks: 0, queuedChunks: 0, elapsedSeconds: 0, remainingBudgetSeconds: null,
  remainingAuthoritySeconds: null, transcriptionStatus: null, transcript: null };

export function CapturePanel({ workspaceId, identity, runtimeFactory = openCaptureRuntime, notesEnabled = false, correctionsEnabled = false, recoveryEnabled = CAPTURE_RECOVERY_BUILD, onDraftLock, onNavigationLock, onExpandedChange, onReviewDraft, onCurrentDraft, reviewLocked, scratchpad, notebookDirty = false, onNotebook, taskBot, openRequest = 0, preferencesScope, encounterLabel }: {
  workspaceId: string; identity: AuthenticatedWorkspaceIdentity; runtimeFactory?: CaptureRuntimeFactory; notesEnabled?: boolean;
  onDraftLock?: (locked: boolean) => void;
  onNavigationLock?: (locked: boolean) => void;
  onExpandedChange?: (expanded:boolean)=>void;
  onReviewDraft?: (draft: CaptureDraft) => void; reviewLocked?: boolean;
  onCurrentDraft?: (draft: CaptureDraft) => void;
  correctionsEnabled?: boolean;
  recoveryEnabled?: boolean;
  scratchpad?: SavedScratchpad; notebookDirty?: boolean; onNotebook?: () => void;
  taskBot?: CaptureTaskBot; openRequest?: number; preferencesScope?: string; encounterLabel?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [snapshot, setSnapshot] = useState<CaptureRuntime['controller']['snapshot']>(idle);
  const [captureMode,setCaptureMode]=useState<'microphone'|'desktop_meeting'>(() =>
    desktopMeetingCaptureAvailable(identity) && readRecordingPreferences(preferencesScope).captureMode === 'desktop_meeting'
      ? 'desktop_meeting' : 'microphone');
  const [consentRequired, setConsentRequired] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(() => !readRecordingPreferences(preferencesScope).regions);
  const [regions, setRegions] = useState(() => readRecordingPreferences(preferencesScope).regions);
  const [sourceKind, setSourceKind] = useState<"synthetic" | "microphone">("synthetic");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<Preparation | null>(null);
  const [draftLocked, setDraftLocked] = useState(false);
  const [transcriptLocked, setTranscriptLocked] = useState(false);
  const [language, setLanguage] = useState<CaptureLanguage>(() => readRecordingPreferences(preferencesScope).language);
  useEffect(() => {
    const defaults = readRecordingPreferences(preferencesScope);
    setRegions(defaults.regions); setLanguage(defaults.language); setOptionsOpen(!defaults.regions);
    setCaptureMode(desktopMeetingCaptureAvailable(identity) && defaults.captureMode === 'desktop_meeting' ? 'desktop_meeting' : 'microphone');
  }, [preferencesScope]);
  const [configured, setConfigured] = useState<PreparedCapture["configured_capture"]>();
  const [reviewed, setReviewed] = useState<CreatorReviewView | null>(null);
  const [showConfiguredNote, setShowConfiguredNote] = useState(false);
  const [working, setWorking] = useState<WorkingReceipt | null>(null);
  useEffect(() => { onDraftLock?.(draftLocked || transcriptLocked); return () => onDraftLock?.(false); }, [draftLocked, transcriptLocked, onDraftLock]);
  useEffect(() => {
    onNavigationLock?.(!!busy || !!pending || ["recording", "uploading", "preparing", "stopping"].includes(snapshot.state));
    return () => onNavigationLock?.(false);
  }, [busy, pending, snapshot.state, onNavigationLock]);
  useEffect(()=>{onExpandedChange?.(expanded);return()=>onExpandedChange?.(false);},[expanded,onExpandedChange]);
  const runtime = useRef<CaptureRuntime | null>(null);
  const preparing = useRef(false);
  const contextKey = JSON.stringify([workspaceId, preferencesScope, taskBot?.selection, taskBot?.enabled]);
  const captureContext = useRef({identity, key: contextKey});
  if (captureContext.current.identity !== identity || captureContext.current.key !== contextKey) {
    captureContext.current = {identity, key: contextKey};
  }
  const actionRevision = useRef(0);
  const lifetime = useRef<{ closed: boolean; unsubscribe?: () => void }>({ closed: false });
  const openedRequest = useRef(0);

  useEffect(() => {
    const current = { closed: false, unsubscribe: undefined as (() => void) | undefined };
    lifetime.current = current;
    return () => {
      current.closed = true;
      current.unsubscribe?.();
      const closing = runtime.current;
      if (closing) void closeRuntime(closing);
    };
  }, []);

  useEffect(() => {
    if (!openRequest || openRequest === openedRequest.current) return;
    openedRequest.current = openRequest;
    if (taskBot && !taskBot.enabled) return;
    setExpanded(true);
    document.querySelector('[aria-label="Scribe recording"]')?.scrollIntoView?.({block: "start"});
    if (!runtime.current && !busy) void prepare(pending ?? {attestation: null, key: crypto.randomUUID(), bot: taskBot?.selection});
  }, [openRequest]);

  async function prepare(request: Preparation, startContext?: typeof captureContext.current) {
    if (busy || preparing.current) return;
    preparing.current = true;
    const current = lifetime.current;
    const revision = ++actionRevision.current;
    setExpanded(true); setBusy("prepare"); setError(""); setPending(request);
    try {
      const admitted = await prepareCapture(workspaceId, identity, request.attestation, request.key, undefined, request.bot, request.language);
      if (current.closed) return;
      const opened = await runtimeFactory(workspaceId, admitted.session_id, identity, admitted.configured_capture,
        captureMode==='desktop_meeting'?'desktop_meeting':undefined);
      if (current.closed) { await closeRuntime(opened); return; }
      if (startContext && startContext !== captureContext.current) {
        await closeRuntime(opened); setPending(null);
        throw Object.assign(new Error("Recording context changed"), {code: "capture_context_changed"});
      }
      runtime.current = opened;
      setConfigured(admitted.configured_capture);
      setSourceKind(opened.sourceKind);
      current.unsubscribe = opened.controller.subscribe(setSnapshot);
      setPending(null); setConsentRequired(false); setOptionsOpen(false);
      if (request.attestation) saveRecordingPreferences(preferencesScope, {
        regions: request.attestation.participant_regions.join(", "), language: request.language ?? language, captureMode,
      });
      const ready = opened.controller.snapshot;
      // Only this fresh consent click can continue into capture. Exact retries,
      // old preparations, recovered audio and permission recovery keep Start.
      if (startContext && request.attestation && !opened.recoveryOnly && !opened.continuePreparation &&
          ready.state === "ready" && ready.recordedChunks === 0 && !ready.recoveryDecision &&
          (!ready.native || ready.native.phase === "ready") && ready.desktop?.phase !== "permission_required") {
        setBusy("start"); requireWorkspaceProtocol(identity);
        await opened.controller.startRecording();
        if (!current.closed && revision === actionRevision.current) setSnapshot(opened.controller.snapshot);
      }
    } catch (cause) {
      if (current.closed || revision !== actionRevision.current) return;
      if (!runtime.current && code(cause) === "capture_consent_required") { setConsentRequired(true); setPending(null); }
      else setError(message(cause));
    } finally {
      preparing.current = false;
      if (!current.closed && revision === actionRevision.current) setBusy("");
    }
  }

  async function act(action: "start" | "pause" | "stop" | "retry" | "gap" | "finish_gap" | "transcript" | "permissions") {
    if (!runtime.current || busy && !(action === "stop" && busy === "start" && snapshot.native)) return;
    const current = lifetime.current;
    const revision = ++actionRevision.current;
    const controller = runtime.current.controller;
    setBusy(action); setError("");
    try {
      if (action === "start") { requireWorkspaceProtocol(identity); await controller.startRecording(); }
      else if (action === "stop") await controller.stopRecording();
      else if (action === "pause") await controller.pauseRecording?.();
      else if (action === "permissions") await controller.refreshPermissions?.();
      else if (action === "gap") await controller.acknowledgeGap();
      else if (action === "finish_gap") await controller.finishInterruptedCapture();
      else if (action === "transcript") await controller.refreshTranscriptionStatus();
      else await controller.resumePendingWork();
    } catch (cause) { if (!current.closed && revision === actionRevision.current) setError(message(cause)); }
    finally { if (!current.closed && revision === actionRevision.current) { setSnapshot(controller.snapshot); setBusy(""); } }
  }

  async function selectMicrophone(input: MicrophoneInput) {
    if (busy || !runtime.current?.controller.selectMicrophoneInput) return;
    const current = lifetime.current;
    setBusy("input"); setError("");
    try { await runtime.current.controller.selectMicrophoneInput(input); }
    catch (cause) { if (!current.closed) setError(message(cause)); }
    finally { if (!current.closed) setBusy(""); }
  }

  async function continuePreparation() {
    if(busy||!runtime.current?.continuePreparation)return;
    const current=lifetime.current;
    setBusy('prepare');setError('');
    try{
      const opened=await runtime.current.continuePreparation();
      if(current.closed){await closeRuntime(opened);return;}
      current.unsubscribe?.();runtime.current=opened;setSourceKind(opened.sourceKind);
      current.unsubscribe=opened.controller.subscribe(setSnapshot);
    }catch(cause){if(!current.closed)setError(message(cause));}
    finally{if(!current.closed)setBusy('');}
  }

  const participantRegions = recordingRegions(regions);
  const validRegions = participantRegions !== null;
  const savingUnconfirmed = !!snapshot.native && snapshot.statusCode === "capture_recovery_pending";
  const status = busy === "prepare" ? "Preparing…" : busy === "start" ? "Starting…" :
    snapshot.state === "recording" ? "Recording" : error || snapshot.state === "error" ? "Needs attention" : snapshot.state === "ready" ? "Ready to start" :
    snapshot.state === "paused" ? "Recording paused" : snapshot.state === "processing" ? "Audio uploaded" :
    snapshot.state === "complete" ? "Transcript available" : snapshot.state === "uploading" ? "Uploading audio" :
    busy === "stop" ? "Saving audio…" :
    taskBot && !taskBot.enabled ? "Scribe paused" : consentRequired ? "Confirm consent" : "Not recording";
  const elapsed = `${Math.floor(snapshot.elapsedSeconds / 60)}:${String(Math.floor(snapshot.elapsedSeconds % 60)).padStart(2, "0")}`;

  return <section className="capture-panel" aria-label="Scribe recording">
    <header>
      <div className="capture-heading"><h2><span aria-hidden="true">🎙️</span> {taskBot?.name ?? "Scribe"} recording</h2>
        {encounterLabel && <p className="capture-encounter">{encounterLabel}</p>}
        <p className="capture-description">{taskBot && !taskBot.enabled ? "Enable Scribe in Team settings to record this visit." : runtime.current
          ? sourceKind === "synthetic" ? "Synthetic audio · microphone off" : runtime.current.captureMode==='desktop_meeting' ? "Meeting audio and microphone" : "Microphone selected"
          : "Record here. Scribe turns the conversation into a draft for you to review."}</p>
        <div className="capture-state"><span className={`capture-indicator ${snapshot.state === "recording" ? "recording" : ""}`} aria-hidden="true" />
          <span role="status">{status}</span>{(snapshot.state === "recording" || snapshot.elapsedSeconds > 0) && <time aria-label={`Recording duration ${elapsed}`}>{elapsed}</time>}</div>
        {snapshot.native && runtime.current?.captureMode === "native_microphone" &&
          <CaptureInputSignal native={snapshot.native} recording={snapshot.state === "recording"} />}
      </div>
      {!expanded && <button className="team-primary capture-record" aria-label="Record visit" disabled={taskBot && !taskBot.enabled} onClick={() => void prepare(pending ?? { attestation: null, key: crypto.randomUUID(), bot: taskBot?.selection })}>Record visit</button>}
      {expanded && !busy && !pending && snapshot.state === "idle" && <button className="team-subtle" onClick={() => setExpanded(false)}>Close setup</button>}
    </header>
    {!expanded && !(taskBot && !taskBot.enabled) && <p className="capture-consent-hint">Consent first. Recording starts when you choose.</p>}
    {expanded && <div className="capture-details">
      {consentRequired && <form onSubmit={event => event.preventDefault()} aria-label="Recording consent">
        <h3>Ready to record this visit?</h3>
        <p>By choosing “Confirm consent &amp; record,” you confirm that everyone agrees to recording and transcription.</p>
        {validRegions && <p className="capture-defaults">{captureMode === "desktop_meeting" ? "Online meeting · microphone and meeting audio" : "In-person visit · microphone"} · {participantRegions.join(", ")} · {language === "en-US" ? "English" : "English and Spanish"}</p>}
        <details className="capture-options" open={optionsOpen} onToggle={event => setOptionsOpen(event.currentTarget.open)}>
          <summary>{validRegions ? "Change location or recording options" : "Set your recording defaults"}</summary>
          <label>Participants’ regions<input value={regions} disabled={!!busy || !!pending} onChange={event => setRegions(event.target.value)} placeholder="For example, US-NY" maxLength={160} /></label>
          <small>Country or state codes, separated by commas. Check every participant’s location for this visit.</small>
          {notesEnabled && <label>Recording language<select value={language} disabled={!!busy || !!pending} onChange={event => setLanguage(event.target.value as CaptureLanguage)}>
            <option value="en-US">English</option><option value="en-US+es-US">English and Spanish</option>
          </select></label>}
          {!runtime.current&&desktopMeetingCaptureAvailable(identity)&&<label>Recording source <select aria-label="Recording source" disabled={!!busy||!!pending}
      value={captureMode} onChange={event=>setCaptureMode(event.target.value as 'microphone'|'desktop_meeting')}>
      <option value="microphone">Microphone</option><option value="desktop_meeting">Online meeting · Zoom or Chrome</option>
    </select></label>}
          {preferencesScope && <small>Your location, language and recording source are remembered on this device for your account. Consent and the meeting window are confirmed for every visit.</small>}
        </details>
        <button type="button" className="team-primary" disabled={!!busy || !!pending || !validRegions || !!taskBot && !taskBot.enabled} onClick={event => {
          if (event.currentTarget.disabled || !event.currentTarget.isConnected || busy || preparing.current || pending || !participantRegions || taskBot && !taskBot.enabled) return;
          void prepare({key: crypto.randomUUID(), bot: taskBot?.selection, ...(notesEnabled ? {language} : {}),
            attestation: {modality: captureMode === "desktop_meeting" ? "virtual" : "in_person", participant_regions: participantRegions, method: "verbal_attestation",
              all_parties_consented: true, granted_at: new Date().toISOString()}}, captureContext.current);
        }}>Confirm consent &amp; record</button>
      </form>}
      {!consentRequired && !runtime.current && <details className="capture-options"><summary>Recording options</summary>{!runtime.current&&desktopMeetingCaptureAvailable(identity)&&<label>Recording source <select aria-label="Recording source" disabled={!!busy||!!pending}
      value={captureMode} onChange={event=>setCaptureMode(event.target.value as 'microphone'|'desktop_meeting')}>
      <option value="microphone">Microphone</option><option value="desktop_meeting">Online meeting · Zoom or Chrome</option>
    </select></label>}</details>}
      {!!snapshot.recordedChunks && <p className="capture-saved">Audio saved on this device · {Math.floor(snapshot.elapsedSeconds / 60)}:{String(Math.floor(snapshot.elapsedSeconds % 60)).padStart(2, "0")}</p>}
      <div className="capture-actions">
        {runtime.current?.continuePreparation&&snapshot.recordedChunks===0&&
          <button className="team-primary" disabled={!!busy} onClick={()=>void continuePreparation()}>Continue preparation</button>}
        {snapshot.state === "ready" && snapshot.native?.phase !== "starting" && !runtime.current?.recoveryOnly && <button className="team-primary" disabled={!!busy||snapshot.desktop?.phase==='permission_required'} onClick={() => void act("start")}>{sourceKind === "synthetic" ? "Start synthetic capture" : "Start recording"}</button>}
        {snapshot.native?.phase === "starting" && <button disabled={!!busy && busy !== "start"} onClick={() => void act("stop")}>Cancel start</button>}
        {snapshot.desktop?.phase==='permission_required'&&<button disabled={!!busy} onClick={()=>void act('permissions')}>Allow recording access</button>}
        {snapshot.state === "recording" && <button className="capture-stop" disabled={!!busy && !(busy === "start" && snapshot.native)} onClick={() => void act("stop")}>Stop and upload</button>}
        {snapshot.state === "recording" && runtime.current?.supportsContinuation && <button disabled={!!busy} onClick={()=>void act("pause")}>Pause recording</button>}
        {(snapshot.state === "error" || snapshot.state === "uploading" &&
          ["capture_recovered_uploading", "capture_upload_pending"].includes(snapshot.statusCode)) &&
          runtime.current && <button disabled={!!busy} onClick={() => void act("retry")}>Retry saved work</button>}
        {!configured && snapshot.state === "processing" && <button disabled={!!busy} onClick={() => void act("transcript")}>Check transcript</button>}
        {runtime.current && onNotebook && <button className="team-subtle" onClick={onNotebook}>Scratch notes</button>}
        {pending && !busy && <button onClick={() => void prepare(pending)}>Retry preparation</button>}
      </div>
      {snapshot.native && ["ready", "paused"].includes(snapshot.state) && runtime.current?.controller.selectMicrophoneInput &&
        <details className="capture-options"><summary>Microphone options</summary><label>Microphone<select aria-label="Recording microphone" value={snapshot.native.input}
          disabled={!!busy || snapshot.native.busy || snapshot.native.phase === "starting"}
          onChange={event => void selectMicrophone(event.target.value as MicrophoneInput)}>
          {microphoneInputs.map(input => <option key={input.value} value={input.value}>{input.label}</option>)}
        </select></label></details>}
      {snapshot.desktop&&<p className="team-fine">Meeting audio and microphone · choose the Zoom or Chrome window when you start.
        {snapshot.desktop.phase==='permission_required'?' Allow microphone and screen/audio recording when asked. If macOS opens Settings, enable access there, then try this action again.':''}
        {snapshot.desktop.coverage==='incomplete'?' Part of this recording was interrupted. Review the transcript before using it for a note.':''}</p>}
      {(snapshot.state === "paused" && !runtime.current?.continuePreparation || snapshot.state === "ready" && runtime.current?.recoveryOnly && snapshot.recordedChunks > 0) && <div className="capture-gap"><p>Recording stopped. Saved audio is retained, and the interruption needs review before this visit can produce a note.</p>
        {runtime.current?.recoveryOnly ? <>
          {runtime.current.canFinishRecovery &&
            <button disabled={!!busy || !snapshot.recordedChunks} onClick={() => void act("finish_gap")}>{snapshot.recoveryDecision === "finish_capture" ? "Retry recovery" : "Finish this recording"}</button>}
          <small>{runtime.current.canFinishRecovery
              ? "This saved recording can be finished with its interruption record. Additional recording is unavailable for this session."
              : "Your saved audio is retained. Finishing this recording requires the recovery connection."}</small>
        </> : (recoveryEnabled && !configured || configured && runtime.current?.supportsContinuation) ? <>
          {snapshot.recoveryDecision ? <button disabled={!!busy} onClick={() => void act(snapshot.recoveryDecision === "finish_capture" ? "finish_gap" : "gap")}>Retry recovery</button> : <>
            <button disabled={!!busy} onClick={() => void act("gap")}>Prepare to resume</button>
            <button disabled={!!busy || !snapshot.recordedChunks && !savingUnconfirmed} onClick={() => void act("finish_gap")}>{savingUnconfirmed ? "Retry saving and upload" : "Finish this recording"}</button>
          </>}
          <small>The interruption stays in the record. Resuming requires a separate press of Start recording.</small>
        </> : <>
          {!configured && snapshot.statusCode !== "capture_resume_authority_required" && <button disabled={!!busy} onClick={() => void act("gap")}>Acknowledge the interruption</button>}
          <small>Recording will not restart automatically. Resuming after a gap is not connected yet.</small>
        </>}</div>}
      {snapshot.state === "ready" && !(runtime.current?.recoveryOnly && snapshot.recordedChunks > 0) && <p className="team-fine">{runtime.current?.recoveryOnly
        ? runtime.current.continuePreparation ? "This preparation has no recorded audio. Continue preparation to use the current recorder, then press Start when you are ready."
          : "This older recording preparation is retained on this device. It cannot start another recording."
        : ["capture_resume_ready", "capture_continuation_ready"].includes(snapshot.statusCode) ? "The interruption is saved. Press Start recording when you are ready to continue." : "The recorder is prepared. Audio capture has not started."}</p>}
      {snapshot.statusCode === "capture_start_unconfirmed" && <p className="team-fine">Recording could not start. Choose Prepare to resume to check the connection, then press Start recording.</p>}
      {snapshot.statusCode === "capture_stop_acknowledgement_pending" && <p className="team-fine">Audio capture has stopped. The connection must confirm this before recording can resume or upload. Choose Prepare to resume or Finish this recording to retry.</p>}
      {snapshot.statusCode === "capture_upload_pending" && <p className="team-fine">Audio is saved on this device. Choose Retry saved work when the connection is available to continue uploading.</p>}
      {savingUnconfirmed && <p className="team-fine">Recording is stopped, but saving could not be confirmed. Retry saving and upload, or choose Prepare to resume to verify the saved audio before recording again.</p>}
      {!configured && snapshot.state === "processing" && <p className="team-fine">{snapshot.statusCode === "capture_gap_review_required" ? "Audio is saved. Interruption review is required before this recording can produce a note." : "Audio is saved. Check here for the transcript while transcription finishes."}</p>}
      {snapshot.statusCode === "capture_transcription_terminal" && <p className="capture-error" role="alert">Transcription could not finish. The saved recording needs attention before a note can be prepared.</p>}
      {snapshot.statusCode === "capture_renewal_unconfirmed" && <p className="team-fine">Recording has stopped and your audio is saved on this device. Choose Retry saved work when the connection is available to finish uploading.</p>}
      {configured && snapshot.state === "processing" && snapshot.sessionId && <>
        <CreatorReviewPanel workspaceId={workspaceId} sessionId={snapshot.sessionId} identity={identity}
          locked={!!reviewLocked || draftLocked} onLock={setTranscriptLocked} onSource={setReviewed}
          onContinue={async () => { await runtime.current?.releaseUploadedCapture?.(); setShowConfiguredNote(true); }} />
        {notesEnabled && showConfiguredNote && reviewed?.status === "transcript_ready" && reviewed.working?.note_ready &&
          <CaptureDraftPanel key={`${snapshot.sessionId}:${reviewed.working.working_transcript_id}:${reviewed.working.working_transcript_version}`}
            workspaceId={workspaceId} sessionId={snapshot.sessionId} sourceId={reviewed.working.working_transcript_id}
            identity={identity} onDraftLock={setDraftLocked} onReviewDraft={onReviewDraft} onCurrentDraft={onCurrentDraft}
            reviewLocked={reviewLocked || transcriptLocked} sourceLocked={transcriptLocked}
            scratchpad={scratchpad} notebookDirty={notebookDirty} onNotebook={onNotebook} taskBot={taskBot} />}
      </>}
      {snapshot.state === "complete" && sourceGapReview(snapshot.qualifiedSource) &&
        <CaptureGapNotice review={sourceGapReview(snapshot.qualifiedSource)!} />}
      {correctionsEnabled && snapshot.state === "complete" && snapshot.sessionId && snapshot.transcript &&
        <CaptureTranscriptEditor key={`${snapshot.sessionId}:${snapshot.transcript.id}`} workspaceId={workspaceId}
          sessionId={snapshot.sessionId} rawId={snapshot.transcript.id} identity={identity} locked={draftLocked || reviewLocked}
          qualifiedSource={snapshot.qualifiedSource} onLock={setTranscriptLocked} onSource={setWorking} />}
      {snapshot.state === "complete" && snapshot.transcript && <details open={!correctionsEnabled} className="capture-transcript" aria-label="Source transcript">
        <summary>{correctionsEnabled ? "Original recording transcript" : "Source transcript"}</summary>
        <p className="team-fine">Speech-to-text from this recording. Review the wording before using it in a note.</p>
        <div className="capture-transcript-segments">{snapshot.transcript.segments.map((segment, index) => <p key={`${segment.start_ms}:${index}`}>
          <span className="capture-speaker">{segment.speaker_role === "unknown" ? "Speaker" : segment.speaker_role === "clinician" ? "Clinician" : segment.speaker_role === "patient" ? "Patient" : "Other speaker"} · {Math.floor(segment.start_ms / 60000)}:{String(Math.floor(segment.start_ms / 1000) % 60).padStart(2, "0")}</span>
          {segment.content}
        </p>)}</div>
      </details>}
      {notesEnabled && snapshot.state === "complete" && snapshot.sessionId && snapshot.transcript &&
        (!correctionsEnabled || working?.working_transcript.note_ready) &&
        <CaptureDraftPanel key={`${snapshot.sessionId}:${snapshot.transcript.id}:${working?.working_sha256 ?? "raw"}`} workspaceId={workspaceId}
          sessionId={snapshot.sessionId} sourceId={snapshot.transcript.id} identity={identity} onDraftLock={setDraftLocked}
          scratchpad={scratchpad} notebookDirty={notebookDirty} onNotebook={onNotebook}
          taskBot={taskBot}
          onReviewDraft={onReviewDraft} onCurrentDraft={onCurrentDraft} reviewLocked={reviewLocked || transcriptLocked} sourceLocked={transcriptLocked} />}
      {error && <p className="capture-error" role="alert">{error}</p>}
    </div>}
  </section>;
}

function code(cause: unknown): string {
  return cause && typeof cause === "object" && "code" in cause && typeof cause.code === "string" ? cause.code : "";
}
function message(cause: unknown): string {
  switch (code(cause)) {
    case "capture_context_changed": return "The encounter or team changed. Open recording again to confirm consent.";
    case "bot_paused": case "team_revision_conflict": return "This bot's settings changed. Refresh the encounter and check its settings before starting a new task.";
    case "capture_connection_required": return "Recording is not connected for this encounter yet.";
    case "capture_consent_unavailable": return "Recording consent is no longer available. Capture cannot continue.";
    case "core_capture_access_unavailable": case "capture_access_unavailable": return "Recording access is unavailable. Saved audio has been retained.";
    case "capture_saved_session_changed": return "A different saved recording needs attention. Its audio has been retained.";
    case "queue_storage_profile_changed": return "This saved recording needs its previous capture setup. Its audio has been retained; restore that setup before continuing.";
    case "native_queue_unavailable": return "Secure recording storage is unavailable on this device. Saved work has been retained.";
    default: return "The recording step could not be confirmed. Saved work has been retained; retry when the connection is available.";
  }
}

async function closeRuntime(runtime: CaptureRuntime) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try { await runtime.close(); return; } catch { /* Retry a failed source close without discarding queued work. */ }
  }
  window.alert("Recording controls could not finish shutting down. Close this window before continuing.");
}
