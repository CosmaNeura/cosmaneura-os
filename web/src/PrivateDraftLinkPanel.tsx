import {useEffect,useRef,useState} from 'react';
import type {EditorRecoveryAccess} from './editor-recovery';
import {editorAddress} from './draft-journal';
import {validatePrivateDraftLinkRecovery,type PrivateDraftLink} from './private-draft-recovery';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace,type WorkspaceEncounter} from './workspace-api';

export function PrivateDraftLinkPanel({identity,workspace,recovery,locked,onSaved,onAccessLost,onBusyChange}:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;
  recovery:EditorRecoveryAccess|null;locked:boolean;onSaved:(value:Workspace)=>void;onAccessLost:(cause:unknown)=>void;onBusyChange?:(busy:boolean)=>void}){
  const [pending,setPending]=useState<PrivateDraftLink|null>(null),[choices,setChoices]=useState<WorkspaceEncounter[]|null>(null);
  const [selection,setSelection]=useState(''),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[ready,setReady]=useState(false),[retryAllowed,setRetryAllowed]=useState(false),[error,setError]=useState('');
  const live=useRef({identity,workspaceId:workspace.id,recovery,epoch:0,alive:true});
  if(live.current.identity!==identity||live.current.workspaceId!==workspace.id||live.current.recovery!==recovery)live.current={identity,workspaceId:workspace.id,recovery,epoch:live.current.epoch+1,alive:true};
  const current=(epoch:number)=>live.current.alive&&live.current.epoch===epoch&&live.current.identity===identity&&live.current.workspaceId===workspace.id&&live.current.recovery===recovery;
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  useEffect(()=>{callback.current?.(busy||!!pending);},[busy,pending]);
  const address=editorAddress(workspace.id,'private-draft-link');
  useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;};},[]);
  useEffect(()=>{const epoch=++live.current.epoch;setReady(false);setPending(null);setChoices(null);setSelection('');setConfirmed(false);setBusy(false);setError('');
    if(!recovery)return;
    void(async()=>{await recovery.authorize();if(!current(epoch))return;const saved=await recovery.journal.load(address);if(!current(epoch))return;
      if(saved){if(saved.kind!=='editor'||saved.editor!=='private-draft-link')throw new Error();setPending(validatePrivateDraftLinkRecovery(saved.data,workspace.id).pending);}setReady(true);
    })().catch(()=>{if(current(epoch))setError('The visit-link request could not be recovered. Recheck draft recovery before linking.');});
  },[identity,workspace.id,recovery]);
  async function persist(value:PrivateDraftLink|null){if(!recovery)throw new Error();await recovery.journal.persist(address,value?{kind:'editor',workspaceId:workspace.id,editor:'private-draft-link',data:{contract:'private-draft-link-recovery.v1',workspace_id:workspace.id,pending:value},pending:value.idempotency_key}:null);}
  function failure(cause:unknown){setError('The link could not be confirmed. Check the exact saved link before another action.');if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){setChoices(null);onAccessLost(cause);}}
  async function load(){if(!recovery||!ready||busy||locked||pending)return;const epoch=live.current.epoch;setBusy(true);setError('');
    try{await recovery.authorize();if(!current(epoch))return;const catalog=await workspaceApi.catalog(identity);if(current(epoch)){setChoices(catalog);setSelection('');setConfirmed(false);}}
    catch(cause){if(current(epoch))failure(cause);}finally{if(current(epoch))setBusy(false);}}
  async function link(retry=false){if(!recovery||!ready||busy||locked||pending&&(!retry||!retryAllowed)||retry&&!pending||!retry&&(!confirmed||!choices?.some(choice=>choice.appointment_id===selection)))return;
    const epoch=live.current.epoch,body:PrivateDraftLink=pending??{expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),appointment_id:selection,appointment_link_confirmed:true};setBusy(true);setRetryAllowed(false);setError('');
    try{await recovery.authorize();if(!current(epoch))return;await persist(body);if(!current(epoch))return;setPending(body);
      const result=await workspaceApi.linkAppointment(identity,workspace.id,body);if(!current(epoch))return;
      await recovery.authorize();if(!current(epoch))return;await persist(null);if(current(epoch)){setPending(null);onSaved(result.workspace);}}
    catch(cause){if(current(epoch))failure(cause);}finally{if(current(epoch))setBusy(false);}}
  async function resolve(){if(!recovery||!ready||busy||locked||!pending)return;const epoch=live.current.epoch;setBusy(true);setError('');
    try{await recovery.authorize();if(!current(epoch))return;const result=await workspaceApi.resolveAppointmentLink(identity,workspace.id,pending);if(!current(epoch))return;
      await recovery.authorize();if(!current(epoch))return;if(result.outcome==='saved'&&result.workspace){await persist(null);if(current(epoch)){setPending(null);onSaved(result.workspace);}}else{setRetryAllowed(true);setError('No saved link was found. The exact original request is retained; retry only that same request.');}}
    catch(cause){if(current(epoch))failure(cause);}finally{if(current(epoch))setBusy(false);}}
  if(!workspace.private_draft||workspace.private_draft.state==='linked')return null;
  return <section className="private-draft-link" aria-label="Link private draft to a visit"><h2>Private draft</h2><p>This note is not linked to a patient or appointment. Recording and visit actions remain unavailable.</p>
    {pending?<><p>The earlier visit link is unconfirmed. Its exact request is retained.</p><button disabled={!ready||busy||locked} onClick={()=>void resolve()}>Check saved visit link</button>{retryAllowed&&<button disabled={!ready||busy||locked} onClick={()=>void link(true)}>Retry same visit link</button>}</>:<details><summary>Link a confirmed visit</summary>
      <p>Choose an appointment you can access, then confirm the note belongs to that patient and visit. Your draft history is kept.</p>
      <button disabled={!ready||busy||locked} onClick={()=>void load()}>Load available visits</button>
      {choices&&<><label>Visit<select disabled={busy||locked} value={selection} onChange={event=>{setSelection(event.target.value);setConfirmed(false);}}><option value="">Choose a visit…</option>{choices.map(choice=><option key={choice.appointment_id} value={choice.appointment_id}>{choice.label}</option>)}</select></label>
        {!choices.length&&<p>No confirmed visits are available. Your private note remains available.</p>}
        <label><input type="checkbox" disabled={busy||locked||!selection} checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>I checked that this note belongs to the selected patient and visit.</label>
        <button disabled={!ready||busy||locked||!selection||!confirmed} onClick={()=>void link()}>Link this visit</button></>}
    </details>}{error&&<p role="alert">{error}</p>}</section>;
}
