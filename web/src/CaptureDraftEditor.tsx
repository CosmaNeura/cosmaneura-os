import { useEffect, useRef, useState } from "react";
import { captureDraft, resolveCaptureSave, saveCaptureDraft, validateDraft, type CaptureDraft } from "./capture-notes-api";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { notebookSourceKey } from "./notebook-source";
import { useUnsavedWork } from "./unsaved-work";
import { EditorRecoveryNotice, editorData, editorDraft, useEditorRecovery } from "./editor-recovery";
import { DraftStoreError } from "./draft-store";

const sameFields = (left: Record<string, string>, right: Record<string, string> | null) => !!right &&
  Object.keys(left).length === Object.keys(right).length && Object.keys(left).every(key => left[key] === right[key]);

export function CaptureDraftEditor({ initial, workspaceId, identity, onLock, onReviewDraft, onCurrentDraft, onReloadSource, reviewLocked = false, sourceLocked = false, simpleFlow=false }: {
  initial: CaptureDraft; workspaceId: string; identity: AuthenticatedWorkspaceIdentity; onLock: (locked: boolean) => void;
  onReviewDraft?: (draft: CaptureDraft) => void; reviewLocked?: boolean;
  onCurrentDraft?: (draft: CaptureDraft) => void;
  onReloadSource?: () => void;
  sourceLocked?: boolean;
  simpleFlow?: boolean;
}) {
  const [base, setBase] = useState(initial);
  const [fields, setFields] = useState(initial.fields ?? {});
  const [editing, setEditing] = useState(simpleFlow);
  const [busy, setBusy] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState<CaptureDraft | null>(null);
  const [saved, setSaved] = useState(false);
  const [sourceChanged, setSourceChanged] = useState(false);
  const key = useRef<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const dirty = base.status === "draft" && !sameFields(fields, base.fields);
  const localDraft = (pending: string | null = key.current) => editorDraft(workspaceId,"core-note",{base,fields},pending);
  const recovery = useEditorRecovery(workspaceId,"core-note", dirty || key.current ? localDraft() : null, !!busy || uncertain);
  const valid = base.status === "draft" && Object.keys(fields).length === base.field_order!.length && base.field_order!.every(name=>
    typeof fields[name] === "string" && !fields[name].includes("\0")) && new TextEncoder().encode(JSON.stringify(fields)).length <= 262144;
  const blocked = sourceLocked || recovery.blocked;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.abort(); }; }, []);
  useEffect(() => { onLock(dirty || !!busy || uncertain || recovery.blocked); return () => onLock(false); }, [dirty, busy, uncertain, recovery.blocked, onLock]);
  useUnsavedWork(dirty || uncertain || busy === "save");

  function adopt(value: CaptureDraft) {
    onCurrentDraft?.(value);
    setBase(value); setFields(value.fields!); setConflict(null); setUncertain(false); setError("");
    setSourceChanged(false);
    key.current = null;
  }
  async function check() {
    if (blocked || busy) return;
    const request = new AbortController(); active.current = request;
    setBusy("read"); setError("");
    try {
      const result = await captureDraft(workspaceId, base.session_id, base.scribe_source_id, identity, base.schema_ref, "read", request.signal);
      if (!mounted.current || request.signal.aborted) return;
      onCurrentDraft?.(result);
      if (key.current && recovery.access !== undefined) {
        setUncertain(true); setError("The current draft was checked. Retry the original save to confirm its exact result; matching text alone does not confirm that request."); return;
      }
      if (result.status !== "draft" || result.source_sha256 !== base.source_sha256 || notebookSourceKey(result.notebook_source) !== notebookSourceKey(base.notebook_source)) {
        setSourceChanged(true); setUncertain(true); setError("The recording source changed. Your text is preserved below; keep a copy before discarding local edits and loading the current source."); return;
      }
      if (sameFields(fields, result.fields)) { await recovery.commit(null); if (!mounted.current || request.signal.aborted) return; adopt(result); setSaved(true); }
      else if (result.note_ref === base.note_ref && result.note_sha256 === base.note_sha256) {
        setUncertain(false); setConflict(null);
      } else if (!dirty) { adopt(result); setSaved(false); }
      else { setConflict(result); setUncertain(false); }
    } catch (cause) { if (mounted.current && !request.signal.aborted) { recovery.denied(cause); setError("The saved draft could not be checked. Your editor text is preserved."); } }
    finally { if (mounted.current && !request.signal.aborted) setBusy(""); }
  }
  async function save() {
    if (blocked || busy || !valid || conflict || sourceChanged) return;
    const request = new AbortController(); active.current = request;
    key.current ??= crypto.randomUUID();
    setBusy("save"); setError(""); setSaved(false);
    let transmitted = false;
    try {
      await recovery.commit(localDraft());
      if (!mounted.current || request.signal.aborted) return;
      transmitted = true;
      const result = await saveCaptureDraft(workspaceId, identity, base, fields, key.current, request.signal);
      if (!mounted.current || request.signal.aborted) return;
      const latest = recovery.access === undefined ? result : await captureDraft(workspaceId,base.session_id,base.scribe_source_id,identity,base.schema_ref,"read",request.signal);
      if (!mounted.current || request.signal.aborted) return;
      if (latest.status !== "draft" || latest.source_sha256 !== result.source_sha256 || notebookSourceKey(latest.notebook_source) !== notebookSourceKey(result.notebook_source)) {
        throw new Error("current source not confirmed");
      }
      if (latest.note_ref !== result.note_ref || latest.note_sha256 !== result.note_sha256) {
        await recovery.commit(editorDraft(workspaceId,"core-note",{base:result,fields}));
        if (!mounted.current || request.signal.aborted) return;
        key.current = null; setBase(result); setConflict(latest); setUncertain(false); onCurrentDraft?.(latest);
        setError("Your edit was saved. A newer Core version is current; compare before continuing.");
      } else {
        await recovery.commit(null);
        if (mounted.current && !request.signal.aborted) { adopt(latest); setSaved(true); }
      }
    } catch (cause) {
      if (mounted.current && !request.signal.aborted) {
        recovery.denied(cause);
        if (!transmitted) { key.current = null; setUncertain(false); setError("The request was not sent. Recheck local editor storage before saving."); }
        else { setUncertain(true); setError("Save not confirmed. Your text and exact request are retained. Retry the original save to recover its result."); }
      }
    } finally { if (mounted.current && !request.signal.aborted) setBusy(""); }
  }
  async function resolve() {
    if (blocked || busy || !valid || !key.current) return;
    const request=new AbortController(); active.current=request;
    setBusy("resolve"); setError(""); setSaved(false);
    try {
      const result=await resolveCaptureSave(workspaceId,identity,base,fields,key.current,request.signal);
      if (!mounted.current || request.signal.aborted) return;
      const latest=await captureDraft(workspaceId,base.session_id,base.scribe_source_id,identity,base.schema_ref,"read",request.signal);
      if (!mounted.current || request.signal.aborted) return;
      const changed=latest.status!=="draft" || latest.source_sha256!==base.source_sha256 || notebookSourceKey(latest.notebook_source)!==notebookSourceKey(base.notebook_source);
      if (result.status==="saved" && !changed && latest.note_ref===result.result_note_ref && latest.note_sha256===result.result_sha256) {
        await recovery.commit(null);
        if (mounted.current && !request.signal.aborted) { adopt(latest); setSaved(true); }
      } else {
        await recovery.commit(localDraft(null));
        if (!mounted.current || request.signal.aborted) return;
        key.current=null; setSourceChanged(changed); setUncertain(changed); onCurrentDraft?.(latest);
        setConflict(!changed && (latest.note_ref!==base.note_ref || latest.note_sha256!==base.note_sha256) ? latest : null);
        setError((result.status==="saved" ? "The original save is confirmed in Core history." : "The original request was closed without saving. It cannot commit later.")+
          (changed ? " The source changed; your text is retained for comparison before loading the current source." : " Your text is retained. Compare the current version before continuing."));
      }
    } catch (cause) {
      if (mounted.current && !request.signal.aborted) { recovery.denied(cause); setUncertain(true); setError("The original save could not be resolved. Your text and exact request are retained."); }
    } finally { if (mounted.current && !request.signal.aborted) setBusy(""); }
  }
  return <div className="capture-note-result">
    <EditorRecoveryNotice recovery={recovery} label="Core note" onRestore={async draft => {
      const data = draft.data; editorData(data,"base,fields");
      if (!data.base || typeof data.base !== "object" || !data.fields || typeof data.fields !== "object" || Array.isArray(data.fields)) throw new DraftStoreError("integrity");
      const stored = data.base as CaptureDraft;
      const restored = await validateDraft(stored as unknown as Record<string,unknown>,initial.session_id,initial.scribe_source_id,stored.schema_ref,workspaceId);
      const local = data.fields as Record<string,string>;
      if (restored.status !== "draft" || Object.keys(local).sort().join("\0") !== restored.field_order!.slice().sort().join("\0") ||
          Object.values(local).some(value=>typeof value !== "string" || value.length > 262144)) throw new DraftStoreError("integrity");
      if (draft.pending && (Object.values(local).some(value=>value.includes("\0")) || new TextEncoder().encode(JSON.stringify(local)).length > 262144)) throw new DraftStoreError("integrity");
      const latest = await captureDraft(workspaceId,restored.session_id,restored.scribe_source_id,identity,restored.schema_ref,"read");
      if (!mounted.current) return;
      const changed = latest.status !== "draft" || latest.source_sha256 !== restored.source_sha256 || notebookSourceKey(latest.notebook_source) !== notebookSourceKey(restored.notebook_source);
      setBase(restored); setFields(local); setEditing(true); key.current = draft.pending; setSaved(false);
      setSourceChanged(changed); setUncertain(!!draft.pending || changed);
      setConflict(!draft.pending && !changed && (latest.note_ref !== restored.note_ref || latest.note_sha256 !== restored.note_sha256) ? latest : null);
      setError(changed ? "The recording source changed. Your recovered text is retained; compare it before discarding or preparing a new source." : "");
    }} />
    {base.status === "draft" && <p className="team-fine">{simpleFlow?'Draft saved · review the text before using it':'Saved in Core · clinical review required'}</p>}
    {base.reviewed_source?.capture_continuity && <p role="status">Recording continuity is unconfirmed. Check this draft for missing speech; gap lengths are unknown.</p>}
    <p className="team-fine">Sources: recorded transcript{base.notebook_source ? ` + saved scratch notes (revision ${base.notebook_source.revision})` : ""}.</p>
    {editing && <p className="team-fine">{simpleFlow?'Review and correct each section below. Saving keeps a draft; signing remains a separate step.':'Saving keeps the previous Core version. It does not sign the note or authorize follow-up.'}</p>}
    {(base.field_order ?? []).map(field => <section key={field}><h4>{field}</h4>{editing
      ? <textarea aria-label={`Draft ${field}`} rows={4} maxLength={262144} value={fields[field]}
        disabled={!!busy || uncertain || !!conflict || blocked} onChange={event => {
          setFields(current => ({...current, [field]: event.target.value})); key.current = null; setSaved(false);
        }} />
      : fields[field] ? <p>{fields[field]}</p> : <p className="team-fine">No draft text in this section.</p>}</section>)}
    {conflict && <div className="team-note-notice" role="status">
      <p>A newer Core draft is saved. Your text is preserved; compare the versions before continuing.</p>
      <details><summary>Compare saved draft</summary>{conflict.field_order!.map(field => <section key={field}><h4>{field}</h4><p>{conflict.fields![field]}</p></section>)}</details>
      <button disabled={!!busy || blocked} onClick={() => { adopt(conflict); setSaved(false); }}>Use saved version</button>
      <button disabled={!!busy || blocked} onClick={() => { setBase(conflict); setConflict(null); key.current = null; setSaved(false); }}>Keep my text for next version</button>
    </div>}
    <div className="capture-actions">
      {sourceChanged && onReloadSource && <button disabled={!!busy || blocked || !!key.current && recovery.access !== undefined} onClick={()=>void recovery.commit(null).then(()=>onReloadSource()).catch(()=>{})}>Discard local edits and reload source</button>}
      {!editing && base.status === "draft" && <button disabled={!!busy || blocked} onClick={() => setEditing(true)}>Edit draft</button>}
      {editing && <button className="team-primary" disabled={!dirty || !valid || !!busy || uncertain || !!conflict || blocked} onClick={() => void save()}>{simpleFlow?'Save visit note':'Save draft edits'}</button>}
      {uncertain && key.current && <button disabled={!!busy || blocked || sourceChanged} onClick={()=>void save()}>Retry Core note save</button>}
      {uncertain && key.current && <button disabled={!!busy || blocked} onClick={()=>void resolve()}>Resolve original save</button>}
      {(!simpleFlow||uncertain||error)&&<button disabled={!!busy || blocked} onClick={() => void check()}>Check saved draft</button>}
      {onReviewDraft && base.status === "draft" && <button className="team-primary" disabled={dirty || !!busy || uncertain || !!conflict || reviewLocked || blocked}
        onClick={() => onReviewDraft(base)}>{simpleFlow?'Continue to clinical review':'Use saved draft for review'}</button>}
    </div>
    {uncertain && key.current && <p className="team-fine">Resolve checks whether the original save committed and closes that request if it did not. Your editor text is retained.</p>}
    {busy && <p role="status">{busy === "save" ? "Saving a new Core version…" : busy === "resolve" ? "Resolving the original save…" : "Checking the saved draft…"}</p>}
    {dirty && !busy && <p className="team-fine">Unsaved edits</p>}
    {base.status === "draft" && !valid && <p role="alert">Shorten the note to fit the supported saved-note size before saving. Your local text is retained.</p>}
    {saved && !dirty && <p role="status">{simpleFlow?'Your visit note edits are saved. You can continue to clinical review or return Home.':'Your text is saved in Core. Clinical review is still required.'}</p>}
    {error && <p role="alert" className="capture-error">{error}</p>}
  </div>;
}
