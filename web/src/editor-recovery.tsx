import { createContext, useContext, useEffect, useRef, useState } from "react";
import { editorAddress, type DraftJournal, type EditorDraft, type EditorKind } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import type { Workspace } from "./workspace-api";
import { useUnsavedWork } from "./unsaved-work";

export type EditorRecoveryAccess = {
  journal: DraftJournal;
  workspaceId: string;
  authorize(): Promise<Workspace>;
  denied(error: unknown): void;
};
// undefined is a synthetic/standalone editor; null is an authenticated workspace
// whose store has not become available. It must not silently bypass recovery.
export const EditorRecoveryContext = createContext<EditorRecoveryAccess | null | undefined>(undefined);
export function editorDraft(workspaceId: string, editor: EditorKind, data: unknown, pending: string | null = null): EditorDraft {
  return {kind:"editor",workspaceId,editor,data,pending};
}
export function editorData(value: unknown, keys: string): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join(",") !== keys.split(",").sort().join(",")) throw new DraftStoreError("integrity");
}
type Phase = "checking" | "ready" | "saving" | "failed";
export function useEditorRecovery(workspaceId: string, kind: EditorKind, value: EditorDraft | null, paused: boolean,
  options:{required?:boolean;scopeKey?:string;identity?:unknown}={}) {
  const context = useContext(EditorRecoveryContext),access=options.required&&context===undefined?null:context;
  const [phase,setPhase] = useState<Phase>(access === undefined ? "ready" : "checking");
  const [offer,setOffer] = useState<EditorDraft | null>(null);
  const [epoch,setEpoch] = useState(0);
  const [message,setMessage] = useState("");
  const ready = useRef(false), alive = useRef(false), sequence = useRef(0), restoring = useRef(false);
  const writeSequence = useRef(0);
  const address = editorAddress(workspaceId,kind);
  const signature = JSON.stringify(value);
  const liveAccess = useRef(access); liveAccess.current = access;
  useEffect(() => {
    alive.current = true; ready.current = false; restoring.current = false;
    const current = ++sequence.current;
    setOffer(null); setMessage("");
    if (access === undefined) { ready.current = true; setPhase("ready"); }
    else if (!access || access.workspaceId !== workspaceId) setPhase("checking");
    else {
      setPhase("checking");
      void access.journal.load(address).then(draft => {
        if (!alive.current || current !== sequence.current) return;
        if (draft && (draft.kind !== "editor" || draft.editor !== kind)) throw new DraftStoreError("integrity");
        setOffer(draft as EditorDraft | null); ready.current = !draft; setPhase("ready");
      }).catch(() => { if (alive.current && current === sequence.current) setPhase("failed"); });
    }
    return () => { alive.current = false; ready.current = false; sequence.current++; };
  },[access,address,workspaceId,kind,epoch,options.scopeKey,options.identity]);
  const current = (saved: EditorRecoveryAccess | null | undefined, generation: number) =>
    alive.current && liveAccess.current === saved && sequence.current === generation;
  async function commit(next: EditorDraft | null) {
    if (access === undefined) return;
    if (!access || !ready.current || !alive.current) throw new DraftStoreError("unavailable");
    const generation = sequence.current;
    const write = ++writeSequence.current;
    setPhase("saving");
    try {
      await access.journal.persist(address,next);
      if (!current(access,generation)) throw new DraftStoreError("unavailable");
      if (write === writeSequence.current && ready.current) {
        setPhase("ready"); setMessage(next ? "Working copy saved on this device." : "No unsaved editor changes.");
      }
    } catch (error) {
      if (current(access,generation)) { ready.current = false; setPhase("failed"); }
      throw error;
    }
  }
  useEffect(() => {
    if (!access || !ready.current || paused || restoring.current) return;
    let canceled = false;
    setPhase("saving");
    void commit(JSON.parse(signature) as EditorDraft | null).catch(() => {
      if (!canceled) setMessage("Your editor could not be saved on this device. Existing local work is retained.");
    });
    return () => { canceled = true; };
  // Only editor input, a completed load or a restored offer starts an autosave.
  },[signature,paused,access,epoch,offer,phase === "checking"]);
  async function restore(apply: (draft: EditorDraft, workspace: Workspace, isCurrent:()=>boolean) => Promise<void>) {
    if (!access || !offer || restoring.current) return;
    const generation = sequence.current;
    restoring.current = true; setPhase("checking"); setMessage("");
    try {
      const workspace = await access.authorize();
      if (!current(access,generation)) return;
      await apply(offer,workspace,()=>current(access,generation));
      if (!current(access,generation)) return;
      ready.current = true; setOffer(null); setPhase("ready");
      setMessage("Recovered your saved work. Compare the current saved version before continuing; nothing was submitted.");
    } catch (error) {
      if (current(access,generation)) {
        access.denied(error); setPhase("ready");
        setMessage("This editor could not be restored with current access and source information. The local record is retained.");
      }
    } finally { if (current(access,generation)) restoring.current = false; }
  }
  async function discard() {
    if (!access || !offer || offer.pending || restoring.current) return;
    const generation = sequence.current; setPhase("checking");
    try {
      await access.journal.persist(address,null);
      if (current(access,generation)) { ready.current = true; setOffer(null); setPhase("ready"); setMessage("Local editor draft discarded. Saved history is unchanged."); }
    } catch { if (current(access,generation)) setPhase("failed"); }
  }
  const blocked = access !== undefined && (!access || !!offer || phase === "checking" || phase === "failed");
  useUnsavedWork(!!offer || phase === "saving" || phase === "failed");
  return {access,offer,phase,message,blocked,commit,restore,discard,
    recheck:()=>setEpoch(n=>n+1), denied:(error:unknown)=>access?.denied(error),
    suspend:()=>{ready.current=false;setPhase("failed");}};
}
export function EditorRecoveryNotice({recovery,label,onRestore}: {
  recovery: ReturnType<typeof useEditorRecovery>; label: string;
  onRestore: (draft: EditorDraft, workspace: Workspace, isCurrent:()=>boolean) => Promise<void>;
}) {
  if (recovery.access === undefined) return null;
  return <div className={recovery.offer || recovery.phase === "failed" ? "team-recovery" : "team-fine"} aria-label={`${label} recovery`}>
    {recovery.offer && <><p>A saved {label.toLowerCase()} draft is available on this device.{recovery.offer.pending ? " Its save is unconfirmed; restore the exact request before continuing." : " Restore it to compare with saved history, or discard this local draft."}</p>
      <button disabled={recovery.phase === "checking" || recovery.phase === "failed"} onClick={()=>void recovery.restore(onRestore)}>Restore {label.toLowerCase()} draft</button>
      {!recovery.offer.pending && <button disabled={recovery.phase === "checking" || recovery.phase === "failed"} onClick={()=>void recovery.discard()}>Discard {label.toLowerCase()} draft</button>}</>}
    {recovery.phase === "checking" && <p role="status">Checking {label.toLowerCase()} recovery…</p>}
    {recovery.phase === "saving" && <p className="team-fine">Saving {label.toLowerCase()} edits on this device…</p>}
    {recovery.phase === "failed" && <div role="alert"><p>Local editor storage is unavailable. Existing work is retained; recheck before editing or saving.</p><button onClick={recovery.recheck}>Recheck {label.toLowerCase()} recovery</button></div>}
    {recovery.message && recovery.message !== "No unsaved editor changes." && <p className="team-fine" role="status">{recovery.message}</p>}
  </div>;
}
