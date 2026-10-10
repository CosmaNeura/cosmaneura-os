import {useEffect,useRef,useState} from 'react';
import {openPrivateRecordingStore,type PrivateRecordingStore} from './private-recording-runtime';
import {PrivateRecordingLedgerController} from './private-recording-ledger';
import {privateRecordingApi,type RecordingVisitBinding,type RecordingVisitRequest} from './private-recording-api';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace,type WorkspaceEncounter} from './workspace-api';
import type {SavedRecordingEntry} from './SavedRecordingTranscriptionPanel';
import {vendorCanonical} from './vendor-contract';

/** A visit selection never changes the recording's original notebook mapping. */
export function RecordingVisitPanel({entry,identity,origin,team,locked,isCurrent,onSelected}:{entry:SavedRecordingEntry;
  identity:AuthenticatedWorkspaceIdentity;origin:Workspace;team:ProviderTeam;locked:boolean;isCurrent:()=>boolean;
  onSelected:(workspace:Workspace,binding:RecordingVisitBinding|null)=>Promise<void>}){
  const [choices,setChoices]=useState<WorkspaceEncounter[]|null>(null),[choice,setChoice]=useState(''),[confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(true),[error,setError]=useState(''),[pending,setPending]=useState(false),[reload,setReload]=useState(0);
  const store=useRef<PrivateRecordingStore|null>(null),flight=useRef(false);
  const live=useRef({identity,isCurrent,locked});live.current={identity,isCurrent,locked};
  const alive=useRef(false),key='visit-binding:'+entry.recordingId;
  const current=()=>alive.current&&live.current.identity===identity&&live.current.isCurrent();
  function failure(cause:unknown){if(current())setError(cause instanceof WorkspaceApiError&&cause.code==='private_recording_visit_in_use'
    ?'This visit already has a saved recording transfer. Your original audio is retained.'
    :cause instanceof WorkspaceApiError&&cause.code==='private_recording_visit_changed'
    ?'The visit changed. Return Home and reopen your recording to check its saved connection.'
    :'The visit connection could not be confirmed. Your recording is saved. Use the button below to check or continue your saved connection.');}
  async function original(check=current){if(!store.current||!check())throw new WorkspaceApiError(403);
    const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store:store.current,scope:entry.scope,isCurrent:check});
    const record=await ledger.readCurrent(entry.recordingId);if(record?.state!=='finished'||!record.receipt)throw new WorkspaceApiError(409);
    const receipt=await privateRecordingApi.read(identity,record.attach,team,record.receipt.recording_id);
    if(!check())throw new WorkspaceApiError(403);return {record,receipt};}
  async function selected(binding:RecordingVisitBinding,check=current){
    const result=await workspaceApi.openExisting(identity,{workspace_id:binding.target_workspace_id,appointment_id:binding.appointment_id});
    if(check())await onSelected(result.workspace,binding);
  }
  useEffect(()=>{alive.current=true;let mounted=true,opened:PrivateRecordingStore|null=null;const check=()=>mounted&&current();
    void(async()=>{opened=await openPrivateRecordingStore(entry.scope,entry.platform);if(!check()){opened.close();return;}store.current=opened;
      const {record,receipt}=await original(check),saved=await opened.read(key);if(!check())return;
      const binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);if(!check())return;
      if(binding){if(saved!==null&&vendorCanonical(saved)!==vendorCanonical(binding.request))throw new WorkspaceApiError(409);await selected(binding,check);return;}
      if(origin.appointment_id&&await opened.read('transfer:'+entry.recordingId)!==null){if(check())await onSelected(origin,null);return;}
      if(saved!==null){setPending(true);return;}
      const rows=await workspaceApi.catalog(identity);if(check())setChoices(rows);
    })().catch(cause=>{if(check())failure(cause);}).finally(()=>{if(check())setBusy(false);});
    return()=>{mounted=false;alive.current=false;store.current=null;opened?.close();};
  },[identity,entry.scope,entry.recordingId,origin.id,reload]);
  async function confirm(){if(!current()||!store.current||flight.current||busy||live.current.locked||!pending&&(!confirmed||!choice))return;
    flight.current=true;setBusy(true);setError('');
    try{const saved=await store.current.read(key);if(!current())return;
      let command:RecordingVisitRequest;
      if(saved!==null)command=saved as RecordingVisitRequest; // The closed API validates before dispatch.
      else{const result=await workspaceApi.open(identity,choice);if(!current())return;
        command={idempotency_key:crypto.randomUUID(),target_workspace_id:result.workspace.id,appointment_id:choice,expected_target_revision:result.workspace.revision,visit_confirmed:true};
        await store.current.write(key,null,command);if(!current())return;setPending(true);}
      const {record,receipt}=await original();
      const binding=await privateRecordingApi.bindVisit(identity,record.attach,team,receipt,command);if(current())await selected(binding);
    }catch(cause){failure(cause);}finally{flight.current=false;if(current())setBusy(false);}
  }
  return <section className="capture-panel saved-visit-selection" aria-label="Choose a visit for this recording">
    <h2>Choose a visit for this recording</h2><p>Your audio and private notebook stay saved. Select the patient and visit this recording belongs to.</p>
    {busy&&<p role="status">Opening your saved visit connection…</p>}
    {pending?<button className="team-primary" disabled={busy||locked} onClick={()=>void confirm()}>Continue with saved visit</button>
      :choices&&<><label>Patient and visit<select value={choice} disabled={busy||locked} onChange={e=>{setChoice(e.target.value);setConfirmed(false);}}>
        <option value="">Choose a visit…</option>{choices.map(row=><option key={row.appointment_id} value={row.appointment_id} disabled={!!origin.appointment_id&&origin.appointment_id!==row.appointment_id}>{row.label}</option>)}
      </select></label>
      <label className="private-recording-check"><input type="checkbox" checked={confirmed} disabled={busy||locked||!choice} onChange={e=>setConfirmed(e.target.checked)}/>I checked that this recording belongs to the patient and visit selected above.</label>
      <button className="team-primary" disabled={busy||locked||!choice||!confirmed} onClick={()=>void confirm()}>Use this visit</button>
      {!choices.length&&<p role="status">No confirmed visits are available. Your recording remains saved on this device.</p>}</>}
    {error&&<><p role="alert">{error}</p>{!pending&&!choices&&<button disabled={busy||locked} onClick={()=>{setBusy(true);setError('');setReload(v=>v+1);}}>Check saved visit connection</button>}</>}
  </section>;
}
