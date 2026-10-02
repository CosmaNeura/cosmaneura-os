import {useEffect,useState} from 'react';
import type {WorkspaceIdentity} from './workspace-api';
import {readFaxStatus,type FaxStatus} from './fax-status-api';
import './fax-followthrough.css';

export const isFaxAction=(action:string)=>['spruce_fax','srfax_fax','documo_fax','efax_fax'].includes(action);
const names={spruce:'Spruce',srfax:'SRFax',documo:'Documo',efax:'eFax Corporate'};
export function FaxFollowthroughCard({identity,workspaceId,ticketId,version,head,revisionId,payloadHash,onReload,locked=false}:{
  identity:WorkspaceIdentity;workspaceId:string;ticketId:string;version:number;head:string;revisionId:string;payloadHash:string;onReload:()=>Promise<void>;locked?:boolean;
}){
  const [attempt,setAttempt]=useState(0);
  const [saved,setSaved]=useState<{identity:WorkspaceIdentity;workspaceId:string;ticketId:string;version:number;head:string;revisionId:string;payloadHash:string;value:FaxStatus}|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(false),[mismatch,setMismatch]=useState(false);
  const status=saved&&saved.identity===identity&&saved.workspaceId===workspaceId&&saved.ticketId===ticketId&&saved.version===version&&saved.head===head&&saved.revisionId===revisionId&&saved.payloadHash===payloadHash?saved.value:null;
  useEffect(()=>{
    const controller=new AbortController();setSaved(null);setLoading(true);setError(false);setMismatch(false);
    void readFaxStatus(identity,workspaceId,ticketId,controller.signal).then(value=>{
      if(!controller.signal.aborted){
        if(value.version!==version||value.observation_head.sha256!==head||value.revision_id!==revisionId||value.payload_hash!==payloadHash){setMismatch(true);setLoading(false);return;}
        setSaved({identity,workspaceId,ticketId,version,head,revisionId,payloadHash,value});setLoading(false);
      }
    }).catch(()=>{if(!controller.signal.aborted){setSaved(null);setError(true);setLoading(false);}});
    return()=>controller.abort();
  },[identity,workspaceId,ticketId,version,head,revisionId,payloadHash,attempt]);
  const reload=async()=>{setLoading(true);setError(false);try{await onReload();setAttempt(value=>value+1);}catch{setLoading(false);setError(true);}};
  return <section className="fax-followthrough" aria-label="Saved fax receipt and next step" aria-busy={loading}>
    {loading?<p role="status">Checking saved fax receipts…</p>:mismatch?<><p role="status">The saved fax changed since this review opened. Reload the saved work before reviewing its receipt or taking another action.</p>{error&&<p role="status">The saved work could not be reloaded. Try the same saved-work read again.</p>}<p>Reloading reads Cosmas’s saved work only; it does not contact the fax provider.</p></>:error||!status?<><p role="status">The saved fax status could not be verified.</p><p>This retries only the saved receipt read; it does not contact the fax provider.</p></>:<>
      <h5>📠 {names[status.provider]} · {status.status_label}</h5>
      <p role="status">{status.next_step.label}</p>
      <p>{status.verification==='verified'?'Local human outcome verified.':'Human completion review remains separate.'}</p>
      <p>{status.pages?`Reported pages: ${status.pages.delivered} of ${status.pages.total}.`:'Page counts were not reported together; do not assume zero pages were transmitted.'}</p>
      <p>{status.last_recorded?`Last recorded provider observation: ${status.last_recorded.observed_at}`:'No provider observation has been recorded.'}</p>
      {!status.original_account_available&&<p>Current access to the original account is unavailable.</p>}
      {status.source_current!==true&&<p>The current reviewed source needs checking. Historical transport evidence remains recorded.</p>}
      <details><summary>Recorded receipt details</summary><p>Operation: <code>{status.operation_id}</code></p><p>Observation sequence: {status.observation_head.sequence}</p><code>{status.observation_head.sha256}</code><p>Saved status commitment</p><code>{status.sha256}</code></details>
      <small>{locked?'Work is locked. ':''}This view reads saved receipts. Checking provider status, sending and human verification use the separate actions below.</small>
    </>}
    <button type="button" disabled={loading||mismatch&&locked} onClick={()=>mismatch?void reload():setAttempt(value=>value+1)}>{mismatch?'Reload saved fax work':error?'Retry saved status':'Refresh saved status'}</button>
  </section>;
}
