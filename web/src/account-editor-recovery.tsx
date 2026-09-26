import {useContext,useEffect,useRef,useState} from "react";
import {AccountRecoveryContext} from "./account-recovery";
import {accountEditorAddress,type AccountEditorDraft,type AccountEditorKind} from "./draft-journal";
import {DraftStoreError} from "./draft-store";
import {useUnsavedWork} from "./unsaved-work";

export const accountEditorDraft=(editor:AccountEditorKind,data:unknown,pending:string|null=null):AccountEditorDraft=>({kind:"account-editor",editor,data,pending});
type Phase="checking"|"ready"|"saving"|"failed";
/** Account-scoped operational forms can exist before an encounter is selected. */
export function useAccountEditorRecovery(required:boolean,kind:AccountEditorKind,value:AccountEditorDraft|null,paused:boolean,onDenied:(cause:unknown)=>void,scopeKey?:unknown) {
  const context=useContext(AccountRecoveryContext), access=required ? context??null : undefined;
  const [phase,setPhase]=useState<Phase>(required?"checking":"ready"),[offer,setOffer]=useState<AccountEditorDraft|null>(null);
  const [epoch,setEpoch]=useState(0),[message,setMessage]=useState("");
  const ready=useRef(false),alive=useRef(false),sequence=useRef(0),restoring=useRef(false),writes=useRef(0);
  const liveAccess=useRef(access);liveAccess.current=access;
  const address=accountEditorAddress(kind),signature=JSON.stringify(value);
  useEffect(()=>{
    alive.current=true;ready.current=false;restoring.current=false;const current=++sequence.current;
    setOffer(null);setMessage("");
    if(access===undefined){ready.current=true;setPhase("ready");}
    else if(!access)setPhase("checking");
    else {
      setPhase("checking");void access.journal.load(address).then(draft=>{
        if(!alive.current||current!==sequence.current)return;
        if(draft&&(draft.kind!=="account-editor"||draft.editor!==kind))throw new DraftStoreError("integrity");
        setOffer(draft as AccountEditorDraft|null);ready.current=!draft;setPhase("ready");
      }).catch(()=>{if(alive.current&&current===sequence.current)setPhase("failed");});
    }
    return()=>{alive.current=false;ready.current=false;sequence.current++;};
  },[access,address,kind,epoch,scopeKey]);
  const current=(saved:typeof access,generation:number)=>alive.current&&liveAccess.current===saved&&sequence.current===generation;
  async function commit(next:AccountEditorDraft|null) {
    if(access===undefined)return;
    if(!access||!ready.current||!alive.current)throw new DraftStoreError("unavailable");
    const generation=sequence.current,write=++writes.current;setPhase("saving");
    try {
      await access.journal.persist(address,next);
      if(!current(access,generation))throw new DraftStoreError("unavailable");
      if(write===writes.current&&ready.current){setPhase("ready");setMessage(next?"Draft saved on this device.":"No unsaved form changes.");}
    }catch(cause){if(current(access,generation)){ready.current=false;setPhase("failed");}throw cause;}
  }
  useEffect(()=>{
    if(!access||!ready.current||paused||restoring.current)return;
    void commit(JSON.parse(signature) as AccountEditorDraft|null).catch(()=>{});
  },[signature,paused,access,epoch,offer,phase==="checking"]);
  async function restore(apply:(draft:AccountEditorDraft,isCurrent:()=>boolean)=>Promise<void>) {
    if(!access||!offer||restoring.current)return;
    const generation=sequence.current;restoring.current=true;setPhase("checking");setMessage("");
    try {
      await access.authorize();if(!current(access,generation))return;
      await apply(offer,()=>current(access,generation));if(!current(access,generation))return;
      ready.current=true;setOffer(null);setPhase("ready");setMessage("Recovered form. Compare current work before continuing; nothing was submitted.");
    }catch(cause){if(current(access,generation)){onDenied(cause);setPhase("ready");setMessage("This form could not be restored with current access. The local record is retained.");}}
    finally{restoring.current=false;}
  }
  async function discard() {
    if(!access||!offer||offer.pending||restoring.current)return;
    const generation=sequence.current;setPhase("checking");
    try{await access.journal.persist(address,null);if(current(access,generation)){ready.current=true;setOffer(null);setPhase("ready");setMessage("Local form discarded. Saved history is unchanged.");}}
    catch{if(current(access,generation))setPhase("failed");}
  }
  useUnsavedWork(!!offer||phase==="saving"||phase==="failed");
  return {required,access,offer,phase,message,commit,restore,discard,
    blocked:required&&(!access||!!offer||phase==="checking"||phase==="failed"),recheck:()=>setEpoch(n=>n+1),
    suspend:()=>{ready.current=false;setPhase("failed");}};
}
export function AccountEditorRecoveryNotice({recovery,label,onRestore}:{recovery:ReturnType<typeof useAccountEditorRecovery>;label:string;onRestore:(draft:AccountEditorDraft,isCurrent:()=>boolean)=>Promise<void>}) {
  if(!recovery.required||!recovery.offer&&recovery.phase==="ready"&&recovery.message==="No unsaved form changes.")return null;
  return <div className={recovery.offer||recovery.phase==="failed"?"team-recovery":"team-fine"} aria-label={`${label} recovery`}>
    {recovery.offer&&<><p>A {label.toLowerCase()} draft is saved on this device.{recovery.offer.pending?" Its save is unconfirmed; restore the exact request before continuing.":" Restore it to compare with current work, or discard this local draft."}</p>
      <button disabled={recovery.phase==="checking"||recovery.phase==="failed"} onClick={()=>void recovery.restore(onRestore)}>Restore {label.toLowerCase()} draft</button>
      {!recovery.offer.pending&&<button disabled={recovery.phase==="checking"||recovery.phase==="failed"} onClick={()=>void recovery.discard()}>Discard {label.toLowerCase()} draft</button>}</>}
    {recovery.phase==="checking"&&<p role="status">Checking {label.toLowerCase()} recovery…</p>}
    {recovery.phase==="saving"&&<p>Saving {label.toLowerCase()} on this device…</p>}
    {recovery.phase==="failed"&&<div role="alert"><p>Local form storage is unavailable. Existing work is retained.</p><button onClick={recovery.recheck}>Recheck {label.toLowerCase()} recovery</button></div>}
    {recovery.message&&<p role="status">{recovery.message}</p>}
  </div>;
}
