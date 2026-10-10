import { useContext, useEffect, useRef, useState } from "react";
import { captureDraft, captureNoteTemplates, type CaptureDraft, type CaptureNoteTemplate } from "./capture-notes-api";
import type { AuthenticatedWorkspaceIdentity, CaptureTaskBot } from "./workspace-api";
import { CaptureDraftEditor } from "./CaptureDraftEditor";
import { CaptureGapNotice } from "./CaptureGapNotice";
import type { SavedScratchpad } from "./notebook-source";
import { EditorRecoveryContext } from "./editor-recovery";
import { editorAddress, type EditorDraft } from "./draft-journal";

export function CaptureDraftPanel({ workspaceId, sessionId, sourceId, identity, onDraftLock, onReviewDraft, onCurrentDraft, reviewLocked, sourceLocked = false, scratchpad, notebookDirty = false, onNotebook, taskBot, simpleFlow=false }: {
  workspaceId: string; sessionId: string; sourceId: string; identity: AuthenticatedWorkspaceIdentity;
  onDraftLock?: (locked: boolean) => void;
  onReviewDraft?: (draft: CaptureDraft) => void; reviewLocked?: boolean;
  onCurrentDraft?: (draft: CaptureDraft) => void;
  sourceLocked?: boolean;
  scratchpad?: SavedScratchpad; notebookDirty?: boolean; onNotebook?: () => void;
  taskBot?: CaptureTaskBot;
  simpleFlow?: boolean;
}) {
  const [templates, setTemplates] = useState<CaptureNoteTemplate[] | null>(null);
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<CaptureDraft | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [editorLocked, setEditorLocked] = useState(false);
  const recoveryAccess = useContext(EditorRecoveryContext);
  const storedEditor = recoveryAccess?.journal.records.get(editorAddress(workspaceId,"core-note"))?.value?.body as EditorDraft | undefined;
  const storedSchema = (storedEditor?.data as {base?: {schema_ref?: string}} | undefined)?.base?.schema_ref;
  useEffect(() => { onDraftLock?.(editorLocked || !!busy); return () => onDraftLock?.(false); }, [editorLocked, busy, onDraftLock]);
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.abort(); }; }, []);

  async function loadTemplates() {
    if (sourceLocked || recoveryAccess === null) return;
    active.current?.abort();
    const request = new AbortController(); active.current = request;
    setBusy("templates"); setError("");
    try {
      const result = await captureNoteTemplates(workspaceId, sessionId, identity, request.signal);
      if (!mounted.current || request.signal.aborted) return;
      setTemplates(result);
      const soap = result.filter(item => /^soap(?:\s|$)/iu.test(item.note_type));
      setSelected(current => storedSchema && result.some(item=>item.schema_ref === storedSchema) ? storedSchema : result.some(item => item.schema_ref === current) ? current : soap.length === 1 ? soap[0].schema_ref : result.length === 1 ? result[0].schema_ref : "");
    } catch (cause) { if (mounted.current && !request.signal.aborted) setError(message(cause)); }
    finally { if (mounted.current && !request.signal.aborted) setBusy(""); }
  }

  async function loadDraft(action: "read" | "prepare", schema = selected) {
    if (!schema || sourceLocked || action === "prepare" && (notebookDirty || reviewLocked || editorLocked || taskBot && (!taskBot.enabled || !!scratchpad && !taskBot.includeNotebook))) return;
    active.current?.abort();
    const request = new AbortController(); active.current = request;
    setBusy(action); setError(""); setDraft(null);
    try {
      const result = await captureDraft(workspaceId, sessionId, sourceId, identity, schema, action, request.signal, scratchpad?.id, action === "prepare" ? taskBot?.selection : undefined);
      if (mounted.current && !request.signal.aborted) { setDraft(result); onCurrentDraft?.(result); }
    } catch (cause) { if (mounted.current && !request.signal.aborted) setError(message(cause)); }
    finally { if (mounted.current && !request.signal.aborted) setBusy(""); }
  }

  useEffect(() => { if (!sourceLocked && templates === null) void loadTemplates(); }, [workspaceId, sessionId, identity, sourceLocked, recoveryAccess]);
  useEffect(() => { if (!sourceLocked) { setDraft(null); if (selected) void loadDraft("read", selected); } }, [selected, sourceId, sourceLocked]);
  const notebookChanged = draft?.status === "draft" && !!scratchpad && draft.notebook_source?.entry_id !== scratchpad.id;

  return <section className="capture-note" aria-label="Recorded visit draft">
    <h3>Visit note</h3>
    <p className="team-fine">{simpleFlow?(draft?.status==='draft'?'Review each section below. Save any corrections before continuing.':'Choose a note template, then create and review your visit note.'):`Choose your Core template to prepare a draft from this recording${scratchpad ? ` and saved scratch notes (revision ${scratchpad.revision})` : ""}.`}</p>
    {notebookDirty && <p role="status">Save your scratch notes before preparing the draft. Unsaved typing is not included.</p>}
    {taskBot && (!taskBot.enabled || scratchpad && !taskBot.includeNotebook) && <p role="status">Enable {taskBot.name} and its saved-notebook source in team settings before preparing this draft.</p>}
    {onNotebook && (!simpleFlow||scratchpad||notebookDirty) && <button className="team-subtle" onClick={onNotebook}>Open scratch notes</button>}
    {templates !== null && templates.length === 0 && <p>No note templates are available for your account. Add a template in Core to prepare this draft.</p>}
    {!!templates?.length && <label>Note template<select value={selected} disabled={!!busy || editorLocked || sourceLocked} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a template</option>{templates.map(item => <option key={item.schema_ref} value={item.schema_ref}>{item.note_type}</option>)}
    </select></label>}
    <div className="capture-actions">
      {templates === null && !busy && <button disabled={sourceLocked} onClick={() => void loadTemplates()}>Retry templates</button>}
      {selected && draft?.status !== "draft" && (!simpleFlow||error) && <button disabled={!!busy || sourceLocked} onClick={() => void loadDraft("read")}>Check saved draft</button>}
      {selected && (draft?.status === "not_prepared" || notebookChanged) && <button className="team-primary" disabled={!!busy || sourceLocked || notebookDirty || reviewLocked || editorLocked || !!taskBot && (!taskBot.enabled || !!scratchpad && !taskBot.includeNotebook)} onClick={() => void loadDraft("prepare")}>{notebookChanged ? "Prepare new draft from saved notes" : simpleFlow?'Create visit note':"Prepare draft note"}</button>}
    </div>
    {busy && <p role="status">{busy === "prepare" ? "Preparing your draft…" : busy === "templates" ? "Loading your templates…" : "Checking for a saved draft…"}</p>}
    {error && <p className="capture-error" role="alert">{error}</p>}
    {draft?.capture_gap_review && <CaptureGapNotice review={draft.capture_gap_review} />}
    {storedSchema && templates && !templates.some(item=>item.schema_ref === storedSchema) && <p role="status">An earlier Core editor is retained on this device. Its template is not currently available; restore that template's access to recover it.</p>}
    {draft && (draft.status === "draft" || storedEditor) && <CaptureDraftEditor key={selected} initial={draft}
      workspaceId={workspaceId} identity={identity} onLock={setEditorLocked} onReviewDraft={onReviewDraft} onCurrentDraft={onCurrentDraft}
      onReloadSource={() => void loadDraft("read")} reviewLocked={reviewLocked || notebookChanged || notebookDirty} sourceLocked={sourceLocked} simpleFlow={simpleFlow} />}
    {notebookChanged && <p role="status">Saved scratch notes changed. The earlier draft is retained; prepare a new version before review.</p>}
    {sourceLocked && <p className="team-fine">Finish checking or saving the transcript before preparing or changing its note.</p>}
  </section>;
}

function message(cause: unknown): string {
  const code = cause && typeof cause === "object" && "code" in cause ? cause.code : "";
  if (code === "capture_note_conflict") return "The source or template changed. Refresh the recording and check its saved draft.";
  if (code === "capture_notebook_changed") return "The saved scratch notes changed. Refresh the encounter and prepare a draft from the latest saved revision.";
  if (code === "capture_source_unavailable" || code === "capture_consent_unavailable") return "This recording is not currently available for note preparation.";
  if (code === "capture_notes_unavailable") return "Draft preparation is not connected for this account yet.";
  return "The draft could not be confirmed. Your saved work is retained. Check the saved draft when the connection is available.";
}
