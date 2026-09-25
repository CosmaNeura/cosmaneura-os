import { useEffect, useRef, useState } from "react";
import { correctWorking, readWorking, validateWorking, validTranscriptText, type SegmentEdit, type SpeakerRole, type WorkingReceipt } from "./capture-working-api";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { validateCaptureSource, type CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";
import { useUnsavedWork } from "./unsaved-work";
import { EditorRecoveryNotice, editorData, editorDraft, useEditorRecovery } from "./editor-recovery";
import { DraftStoreError } from "./draft-store";

const fields = (value: WorkingReceipt) => value.working_source.segments.map(({source_segment_id, content, speaker_role}) => ({source_segment_id, content, speaker_role}));
const changed = (base: WorkingReceipt, edits: SegmentEdit[]) => edits.filter(e => {
  const saved = base.working_source.segments.find(s => s.source_segment_id === e.source_segment_id);
  return saved?.content !== e.content || saved.speaker_role !== e.speaker_role;
});
type Pending = { base: WorkingReceipt; edits: SegmentEdit[]; key: string };
export function CaptureTranscriptEditor({workspaceId, sessionId, rawId, identity, qualifiedSource, locked = false, onLock, onSource}: {
  workspaceId: string; sessionId: string; rawId: string; identity: AuthenticatedWorkspaceIdentity; locked?: boolean;
  qualifiedSource?: CaptureSourceEnvelope;
  onLock: (value: boolean) => void; onSource: (value: WorkingReceipt) => void;
}) {
  const [base, setBase] = useState<WorkingReceipt | null>(null);
  const [edits, setEdits] = useState<SegmentEdit[]>([]);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [conflict, setConflict] = useState<WorkingReceipt | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef<AbortController | null>(null), mounted = useRef(false);
  const pending = useRef<Pending | null>(null);
  const anchor = useRef(qualifiedSource);
  const dirty = !!base && changed(base, edits).length > 0;
  const localDraft = (request: Pending | null = pending.current) => editorDraft(workspaceId,"transcript",{base,edits,qualifiedSource:anchor.current ?? null},request?.key ?? null);
  const recovery = useEditorRecovery(workspaceId,"transcript", base && (dirty || pending.current) ? localDraft() : null, !!busy || uncertain);
  const blocked = locked || recovery.blocked;
  const valid = edits.every(e => validTranscriptText(e.content)) && edits.reduce((sum,e) => sum + [...e.content].length, 0) <= 100000;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.abort(); }; }, []);
  useEffect(() => { onLock(dirty || !!busy || uncertain || !!conflict || recovery.blocked); return () => onLock(false); }, [dirty, busy, uncertain, conflict, recovery.blocked, onLock]);
  useUnsavedWork(dirty || uncertain || busy === "save");
  function adopt(value: WorkingReceipt) {
    setBase(value); setEdits(fields(value)); setConflict(null); setUncertain(false); pending.current = null;
    onSource(value);
  }
  function begin(kind: string) {
    if (active.current || blocked) return null;
    const controller = new AbortController(); active.current = controller;
    setBusy(kind); setError(""); setNotice(""); return controller;
  }
  const current = (r: AbortController) => mounted.current && !r.signal.aborted;
  function finish(r: AbortController) {
    if (active.current === r) active.current = null;
    if (current(r)) setBusy("");
  }
  async function check() {
    if (uncertain) return;
    const r = begin("read"); if (!r) return;
    try {
      const value = await readWorking(workspaceId, sessionId, rawId, identity, r.signal, anchor.current);
      if (!current(r)) return;
      onSource(value);
      if (base && dirty && value.working_sha256 !== base.working_sha256) setConflict(value);
      else if (!dirty) adopt(value);
      else setNotice("Your opened version is still current. Your edits have not been saved.");
    } catch (cause) { if (current(r)) { recovery.denied(cause); setError("The current transcript could not be checked. Your text is preserved. Retry when access and the connection are available."); } }
    finally { finish(r); }
  }
  async function save() {
    if (!base || !valid || conflict || !dirty) return;
    const r = begin("save"); if (!r) return;
    pending.current ??= {base, edits:changed(base, edits), key:crypto.randomUUID()};
    const attempt = pending.current;
    let transmitted = false;
    try {
      await recovery.commit(localDraft(attempt));
      if (!current(r)) return;
      transmitted = true;
      const receipt = await correctWorking(workspaceId, identity, attempt.base, attempt.edits, attempt.key, r.signal, anchor.current);
      const latest = await readWorking(workspaceId, sessionId, rawId, identity, r.signal, anchor.current);
      if (!current(r)) return;
      if (latest.working_source.source_transcript_version < receipt.working_source.source_transcript_version) throw new Error("unconfirmed");
      await recovery.commit(latest.working_sha256 === receipt.working_sha256 ? null : localDraft(null));
      if (!current(r)) return;
      setUncertain(false); pending.current = null; onSource(latest);
      if (latest.working_sha256 !== receipt.working_sha256) {
        setConflict(latest); setNotice("Your correction was saved. A newer version is now current; compare before continuing.");
      } else {
        adopt(latest); setNotice("Transcript correction saved. Prepare and review a new note from this version.");
      }
    } catch (cause) {
      if (!current(r)) return;
      recovery.denied(cause);
      if (!transmitted) { pending.current = null; setUncertain(false); setError("The request was not sent. Recheck local editor storage before saving."); return; }
      // A bounded Core conflict/unavailable response grants no success. Read
      // current state for a deliberate comparison; never infer a save from text.
      if (cause && typeof cause === "object" && "status" in cause && cause.status === 409) {
        try {
          const latest = await readWorking(workspaceId, sessionId, rawId, identity, r.signal, anchor.current);
          if (!current(r)) return;
          if (latest.working_sha256 !== attempt.base.working_sha256) {
            await recovery.commit(localDraft(null));
            if (!current(r)) return;
            setConflict(latest); setUncertain(false); pending.current = null; onSource(latest); return;
          }
        } catch { /* Retain the exact pending request until confirmation. */ }
      }
      if (current(r)) { setUncertain(true); setError("Save not confirmed. Your text and save request are preserved. Retry this save to recover its result."); }
    } finally { finish(r); }
  }
  useEffect(() => { if (!dirty && !pending.current) anchor.current = qualifiedSource; void check(); }, [workspaceId, sessionId, rawId, identity, qualifiedSource, recovery.blocked]);
  return <section className="capture-transcript capture-working" aria-label="Working transcript">
    <EditorRecoveryNotice recovery={recovery} label="Transcript" onRestore={async draft => {
      const data = draft.data; editorData(data,"base,edits,qualifiedSource");
      const restored = await validateWorking(data.base,sessionId,rawId);
      if (!Array.isArray(data.edits) || data.edits.length !== restored.working_source.segments.length) throw new DraftStoreError("integrity");
      const local = data.edits as SegmentEdit[];
      for (const [index,edit] of local.entries()) {
        editorData(edit,"source_segment_id,content,speaker_role");
        if (edit.source_segment_id !== restored.working_source.segments[index].source_segment_id || typeof edit.content !== "string" || edit.content.length > 200000 ||
            !["clinician","patient","other","unknown"].includes(edit.speaker_role as string)) throw new DraftStoreError("integrity");
      }
      if (draft.pending && (!changed(restored,local).length || local.some(edit=>!validTranscriptText(edit.content)) ||
          local.reduce((sum,edit)=>sum+[...edit.content].length,0) > 100000)) throw new DraftStoreError("integrity");
      const evidence = data.qualifiedSource === null ? undefined : await validateCaptureSource(data.qualifiedSource,sessionId);
      if (!!evidence !== !!qualifiedSource || evidence && (evidence.raw_transcript.id !== rawId || evidence.working_transcript.raw_transcript_sha256 !== restored.raw_transcript_sha256 ||
          evidence.recovery_sha256 !== qualifiedSource?.recovery_sha256)) throw new DraftStoreError("integrity");
      const latest = await readWorking(workspaceId,sessionId,rawId,identity,undefined,evidence);
      if (!mounted.current) return;
      anchor.current = evidence; setBase(restored); setEdits(local); setEditing(true);
      pending.current = draft.pending ? {base:restored,edits:changed(restored,local),key:draft.pending} : null;
      setUncertain(!!draft.pending); setConflict(!draft.pending && latest.working_sha256 !== restored.working_sha256 ? latest : null);
      setError(""); setNotice("Recovered transcript corrections. Check the saved version before continuing.");
    }} />
    <h3>Transcript {base && <span className="team-fine">· version {base.working_source.source_transcript_version}</span>}</h3>
    <p className="team-fine">Correct the wording or speaker before preparing your note. The original recording transcript stays preserved.</p>
    {base && !base.working_transcript.note_ready && <p className="capture-error" role="status">
      This source needs attention before a note can be prepared: {[...new Set(base.working_transcript.blockers.map(b =>
        b.code === "source_overlap" ? "overlapping speech" : b.code === "translation_missing" ? "reviewed translation needed" : "source language unresolved"))].join("; ")}. Text edits do not clear these issues.
    </p>}
    <div className="capture-transcript-segments">{base?.working_source.segments.map((segment, index) => <section key={segment.source_segment_id}>
      <span className="capture-speaker">{Math.floor(segment.start_ms / 60000)}:{String(Math.floor(segment.start_ms / 1000) % 60).padStart(2, "0")}</span>
      {editing ? <><label>Speaker for segment {index + 1}<select value={edits[index].speaker_role} disabled={!!busy || uncertain || !!conflict || blocked}
        onChange={event => { setEdits(list => list.map((e,i) => i === index ? {...e,speaker_role:event.target.value as SpeakerRole} : e)); pending.current = null; }}>
        <option value="clinician">Clinician</option><option value="patient">Patient</option><option value="other">Other speaker</option><option value="unknown">Unknown speaker</option>
      </select></label><textarea aria-label={`Transcript segment ${index + 1}`} value={edits[index].content} rows={4} maxLength={200000}
        disabled={!!busy || uncertain || !!conflict || blocked} onChange={event => {
          setEdits(list => list.map((e,i) => i === index ? {...e,content:event.target.value} : e)); pending.current = null; setNotice("");
        }} /></> : <p><span className="capture-speaker">{segment.speaker_role === "unknown" ? "Unknown speaker" : segment.speaker_role}</span>{segment.content}</p>}
    </section>)}</div>
    {conflict && <div className="team-note-notice" role="status"><p>A newer transcript is saved. Your text is preserved; compare before continuing.</p>
      <details><summary>Compare saved transcript · version {conflict.working_source.source_transcript_version}</summary>{conflict.working_source.segments.map(s => <p key={s.source_segment_id}>{s.speaker_role}: {s.content}</p>)}</details>
      <button disabled={!!busy || blocked} onClick={() => { adopt(conflict); setNotice(""); }}>Use saved transcript</button>
      <button disabled={!!busy || blocked} onClick={() => {
        const local = changed(base!, edits), next = fields(conflict).map(e => local.find(s => s.source_segment_id === e.source_segment_id) ?? e);
        setBase(conflict); setEdits(next); setConflict(null); pending.current = null; setNotice("Your corrections are ready to save against the newer version.");
      }}>Keep my corrections for next version</button>
    </div>}
    <div className="capture-actions">
      {base && !editing && <button disabled={!!busy || blocked} onClick={() => setEditing(true)}>Correct transcript</button>}
      {editing && !uncertain && <button className="team-primary" disabled={!dirty || !valid || !!busy || !!conflict || blocked} onClick={() => void save()}>Save transcript corrections</button>}
      {dirty && !uncertain && !conflict && <button disabled={!!busy || blocked} onClick={() => { adopt(base!); setNotice("Unsaved corrections discarded. The saved transcript is unchanged."); }}>Discard transcript edits</button>}
      {uncertain && <button className="team-primary" disabled={!!busy || blocked} onClick={() => void save()}>Retry transcript save</button>}
      <button disabled={!!busy || uncertain || blocked} onClick={() => void check()}>Check current transcript</button>
    </div>
    {dirty && !valid && <p className="capture-error" role="alert">Each segment needs text, with at most 100,000 characters across this transcript.</p>}
    {dirty && <p className="team-fine">Unsaved transcript corrections</p>}
    {locked && <p className="team-fine">Finish the note edit or current workspace step before changing this transcript.</p>}
    {busy && <p role="status">{busy === "save" ? "Saving and checking the current version…" : "Checking the current transcript…"}</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="capture-error" role="alert">{error}</p>}
  </section>;
}
