import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { NoteOperation, Workspace, WorkspaceEntry } from "./workspace-api";
import { CaptureGapNotice } from "./CaptureGapNotice";
import { captureGapKey, validateCaptureGapReview, type CaptureGapReview } from "./capture-gap-review";
import { useUnsavedWork } from "./unsaved-work";
import { EditorRecoveryNotice, editorData, editorDraft, useEditorRecovery } from "./editor-recovery";
import { DraftStoreError } from "./draft-store";

export function NoteReview({ workspace, locked: parentLocked, onSave, onSources, active=false,onStateChange,onTeamDrafts }: {
  workspace: Workspace; locked: boolean; onSave: (operation: NoteOperation) => void; onSources: () => void; active?:boolean;
  onStateChange?:(state:'editing'|'review'|'saved')=>void;
  onTeamDrafts?:(noteId:string)=>void;
}) {
  const latest = workspace.note?.latest;
  const core = !!latest?.core_source;
  const [content, setContent] = useState(latest?.content ?? "");
  const [baseId, setBaseId] = useState(latest?.id ?? null);
  const [sourceId, setSourceId] = useState(latest?.source_reply_id ?? null);
  const baseCore = useRef(core);
  const [reconciled, setReconciled] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [acknowledgedGapTarget, setAcknowledgedGapTarget] = useState<string | null>(null);
  let gaps: CaptureGapReview | undefined; let invalidGaps = false;
  if (latest?.core_source?.capture_gap_review !== undefined) {
    try { gaps = validateCaptureGapReview(latest.core_source.capture_gap_review); }
    catch { invalidGaps = true; }
  }
  const gapTarget = gaps ? JSON.stringify([latest?.id, latest?.core_source?.source_sha256,
    latest?.core_source?.note_sha256, captureGapKey(gaps)]) : null;
  const gapsConfirmed = gapTarget !== null && acknowledgedGapTarget === gapTarget;
  const [replacement, setReplacement] = useState<WorkspaceEntry | null>(null);
  const [detached, setDetached] = useState<{content:string;baseId:string|null;sourceId:string|null} | null>(null);
  const changingToCore = core && latest?.id !== baseId && !baseCore.current;
  const compare = changingToCore ? workspace.note?.history.find(note=>note.id === baseId) : latest;
  const localText = !baseCore.current && (content !== (compare?.content ?? "") || sourceId !== (compare?.source_reply_id ?? null));
  const retained = detached ?? (localText ? {content,baseId,sourceId} : null);
  const recovery = useEditorRecovery(workspace.id,"private-note", retained ? editorDraft(workspace.id,"private-note",retained) : null, parentLocked);
  const locked = parentLocked || recovery.blocked || !!detached;
  useUnsavedWork(!!detached);
  // A confirmed save/retry can be adopted without overwriting any editor text.
  // Different text from another client stays visible for explicit comparison.
  useEffect(() => {
    if (latest?.core_source && latest.id !== baseId) {
      if (changingToCore && localText) setDetached(previous=>previous ?? {content,baseId,sourceId});
      baseCore.current = true;
      setContent(latest.content); setSourceId(latest.source_reply_id); setBaseId(latest.id);
      setConfirmed(false); setReconciled(false); setAcknowledgedGapTarget(null);
    } else if (latest && latest.id !== baseId && !baseId && !content && sourceId === null) {
      baseCore.current = false;
      setContent(latest.content); setSourceId(latest.source_reply_id);
      setBaseId(latest.id); setReconciled(false); setConfirmed(false);
    } else if (latest && latest.id !== baseId && latest.content === content && latest.source_reply_id === sourceId) {
      baseCore.current = !!latest.core_source;
      setBaseId(latest.id); setReconciled(false); setConfirmed(false);
    }
  }, [latest, baseId, content, sourceId, changingToCore, localText]);
  const otherVersion = (latest?.id ?? null) !== baseId;
  const dirty = !latest || content !== latest.content || sourceId !== latest.source_reply_id || reconciled;
  useUnsavedWork(!core && (content !== (latest?.content ?? "") || sourceId !== (latest?.source_reply_id ?? null) || reconciled));
  const scribe = workspace.entries.filter(e => e.reply?.role === "scribe" &&
    e.reply.backend.startsWith("azure_gpt41") && !e.reply.backend.endsWith("unavailable")).at(-1);
  const sourceEntry = workspace.entries.find(e => e.id === sourceId);
  const sourceRevision = sourceEntry?.reply?.context_revision;
  const newestSource = Math.max(0, ...workspace.entries.filter(e =>
    ["scratchpad", "evidence", "synthetic_source"].includes(e.kind)).map(e => e.revision));
  const sourcesChanged = sourceId !== latest?.source_reply_id && sourceRevision !== undefined
    ? newestSource > sourceRevision : latest?.sources_changed ?? false;
  useEffect(()=>{onStateChange?.(!dirty&&!otherVersion&&!sourcesChanged&&latest?.review?'saved':content.trim()?'review':'editing');},[dirty,otherVersion,sourcesChanged,latest?.review,!!content.trim(),onStateChange]);
  function useScribe(entry: WorkspaceEntry) {
    baseCore.current = false;
    setContent(entry.reply!.content); setSourceId(entry.id); setReconciled(false); setConfirmed(false); setReplacement(null);
  }
  // Opening review can adopt an available draft only into a genuinely empty editor.
  // Recovery and saved-version conflicts take precedence over this convenience.
  const initializingScribe=active&&!locked&&!latest&&!content&&sourceId===null&&!!scribe;
  useLayoutEffect(()=>{
    if(initializingScribe)useScribe(scribe!);
  },[initializingScribe,scribe]);
  return <section className="team-note-review" aria-label="Private note review">
    <EditorRecoveryNotice recovery={recovery} label="Private note" onRestore={async (draft,current) => {
      const data = draft.data; editorData(data,"content,baseId,sourceId");
      if (typeof data.content !== "string" || data.content.length > 20000 ||
          [data.baseId,data.sourceId].some(id=>id !== null && (typeof id !== "string" || !id || id.length > 200))) throw new DraftStoreError("integrity");
      if (current.note?.latest?.core_source) setDetached({content:data.content,baseId:data.baseId as string|null,sourceId:data.sourceId as string|null});
      else { baseCore.current = false; setContent(data.content); setBaseId(data.baseId as string | null); setSourceId(data.sourceId as string | null); }
      setConfirmed(false); setReconciled(false); setAcknowledgedGapTarget(null); setReplacement(null);
    }} />
    {detached && <aside className="team-note-notice"><p>Your earlier private draft is recovered below. The encounter now uses a saved Core note. Compare this text with that note in the recorded visit editor before recording a review.</p>
      <label>Recovered earlier private draft<textarea readOnly value={detached.content} rows={8} /></label>
      <button disabled={parentLocked || recovery.blocked} onClick={()=>void recovery.commit(null).then(()=>setDetached(null)).catch(()=>{})}>Discard recovered earlier private draft</button></aside>}
    <div className="team-task-actions">
    <div className="team-notebook-title"><h2>Note review</h2><span className="team-pill">
      {otherVersion ? "New version available" : dirty ? "Review version not saved" : sourcesChanged ? "Sources changed" : latest?.review ? "Reviewed privately" : "Needs review"}
    </span></div>
    {latest && !otherVersion && !dirty && !sourcesChanged && !latest.review && <div className="team-note-approval">
      <label className="team-check"><input type="checkbox" checked={confirmed} disabled={locked} onChange={e => setConfirmed(e.target.checked)} />I reviewed this saved note and its sources.</label>
      {gaps && <label className="team-check"><input type="checkbox" checked={gapsConfirmed} disabled={locked}
        onChange={e => setAcknowledgedGapTarget(e.target.checked ? gapTarget : null)} />I reviewed these capture interruptions and checked this note for missing context.</label>}
    </div>}
    {!core && <button className="team-primary" disabled={locked || otherVersion || !content.trim() || !dirty} onClick={() => onSave({type: "note", body: {
      expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), base_note_id: baseId,
      source_reply_id: sourceId, content, sources_reconciled: reconciled,
    }})}>Save note version</button>}
    {latest && !otherVersion && !dirty && !sourcesChanged && !latest.review && <button disabled={locked || !confirmed || invalidGaps || !!gaps && !gapsConfirmed} onClick={() => onSave({type: "review", noteId: latest.id, body: {
        expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), content_hash: latest.content_hash,
        source_fingerprint: latest.source_fingerprint,
        ...(gaps ? {gap_acknowledgment: {recovery_sha256: gaps.recovery_sha256, acknowledged: true as const}} : {}),
      }})}>Record private review</button>}
    </div>
    {!dirty&&latest&&<p className="team-fine">Note version {latest.version} saved · {latest.review?"Private review recorded":"Needs your review"}.</p>}
    {latest&&onTeamDrafts&&<section aria-label="Next steps from this note">
      <p>Use the saved Scribe note with Chief to prepare a patient email draft, provider action items and a treatment assessment.</p>
      <button type="button" className="team-primary" disabled={locked||dirty||otherVersion||sourcesChanged}
        onClick={()=>{if(!locked&&!dirty&&!otherVersion&&!sourcesChanged)onTeamDrafts(latest.id);}}>Prepare follow-up and research</button>
      {(dirty||otherVersion||sourcesChanged)&&<p className="team-fine">Save and reconcile this note before preparing team drafts.</p>}
    </section>}
    {dirty&&<p className="team-fine">Your working copy and the saved review version are separate. Choose Save note version when your edits are ready for review.</p>}
    <p className="team-fine">{core ? "This is the exact saved Core version. Make changes in the recorded visit draft and use its saved version for review. Core is checked again when you review or authorize follow-up." : "Edit the note, save a version, then review the exact saved text."} Private review does not sign the clinical record or send a follow-up.</p>
    {otherVersion && <div role="status" className="team-note-notice"><p>A different saved note is available. Your editor text is preserved.</p>
      <details><summary>Compare latest saved note</summary><p>{latest?.content}</p></details>
      <button disabled={locked} onClick={() => { baseCore.current = !!latest?.core_source; setContent(latest?.content ?? ""); setBaseId(latest?.id ?? null);
        setSourceId(latest?.source_reply_id ?? null); setConfirmed(false); setReconciled(false); }}>Use latest saved note</button>
      {!core && <button disabled={locked} onClick={() => { baseCore.current = false; setBaseId(latest?.id ?? null);
        setSourceId(sourceId ?? latest?.source_reply_id ?? null); setConfirmed(false); setReconciled(false);
      }}>Keep my text as next version</button>}</div>}
    {scribe && !core && <button disabled={locked || otherVersion} onClick={() => content.trim() ? setReplacement(scribe) : useScribe(scribe)}>Use latest Scribe draft</button>}
    {replacement && !core && <div className="team-note-notice" role="status"><p>Replace the editor with Scribe's latest draft? Saved versions remain in history.</p>
      <button disabled={locked} onClick={() => useScribe(replacement)}>Replace editor with draft</button>
      <button disabled={locked} onClick={() => setReplacement(null)}>Keep my text</button></div>}
    <label htmlFor="private-note-text">Private note draft</label>
    <textarea id="private-note-text" rows={10} maxLength={core ? undefined : 20000} value={content} readOnly={core} disabled={locked || otherVersion || initializingScribe}
      onChange={e => { setContent(e.target.value); setConfirmed(false); }} placeholder="Review a Scribe draft or write your own note…" />
    <button className="team-subtle" onClick={onSources}>Check notebook and sources</button>
    {latest?.core_source?.reviewed_source?.capture_continuity && <p role="status" className="team-note-notice">Recording continuity is unconfirmed. Check the note for missing speech. The length of any gap is unknown.</p>}
    {gaps && <CaptureGapNotice review={gaps} />}
    {invalidGaps && <p role="alert">Capture interruption details could not be checked. Reload the current note before reviewing.</p>}
    {sourcesChanged && <div className="team-note-notice"><p>The note's source context has changed. Check the changes and update the note before reviewing.</p>
      {core ? <p>Check the recorded visit draft against these changes, save any edits in Core, then use that saved version for review.</p> : <label className="team-check"><input type="checkbox" checked={reconciled} disabled={locked || otherVersion}
        onChange={e => { setReconciled(e.target.checked); setConfirmed(false); }} />I checked the newer sources and reconciled this note.</label>}</div>}

    {latest?.review && !dirty && !otherVersion && <p className="team-fine">Version {latest.version} reviewed by you at {new Date(latest.review.created_at).toLocaleString()}.{sourcesChanged ? " That review predates the source changes." : ""}</p>}
    {!!workspace.note?.history.length && <details className="team-history"><summary>Note version history</summary>
      {[...workspace.note.history].reverse().map(n => <article key={n.id}><small>Version {n.version} · {n.review ? "Review recorded" : "Unreviewed"}{n.sources_changed ? " · Sources changed" : ""}</small><p>{n.content}</p></article>)}
    </details>}
  </section>;
}
