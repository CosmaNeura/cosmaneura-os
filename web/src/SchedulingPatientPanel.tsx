import {useEffect,useRef,useState} from 'react';
import {EditorRecoveryNotice,editorDraft,useEditorRecovery} from './editor-recovery';
import {DraftStoreError} from './draft-store';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {useUnsavedWork} from './unsaved-work';
import {schedulingPatientApi,validSchedulingPatientCommand,validSchedulingPatientDate,type SchedulingPatientChoice,type SchedulingPatientCommand,
 SchedulingPatientRefusal,type SchedulingPatientReceipt,type SchedulingPatientStatus} from './scheduling-patient-api';
import {emptySchedulingPatientRecovery,validateSchedulingPatientRecovery,schedulingPatientReceiptMatches,schedulingPatientSelected,
 type SchedulingPatientRecovery} from './scheduling-patient-recovery';

export type SchedulingPatientPanelProps={identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;enabled:boolean;locked:boolean;recoveryLocked?:boolean;observationStamp?:number;
 onBusyChange?:(busy:boolean)=>void;onLinked?:(receipt:SchedulingPatientReceipt)=>void;onAccessLost?:(error:WorkspaceApiError)=>void};
export function SchedulingPatientPanel({identity,workspace,enabled,locked,recoveryLocked,observationStamp=0,onBusyChange,onLinked,onAccessLost}:SchedulingPatientPanelProps){
 const [record,setRecord]=useState(()=>emptySchedulingPatientRecovery(workspace.id,workspace.appointment_id)),[status,setStatus]=useState<SchedulingPatientStatus|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[samePatient,setSamePatient]=useState(false),[exactIdentity,setExactIdentity]=useState(false);
 const [authorityLost,setAuthorityLost]=useState(false),[verifiedPreview,setVerifiedPreview]=useState(false),[verifiedSaved,setVerifiedSaved]=useState(false),[notFound,setNotFound]=useState(false),[now,setNow]=useState(Date.now);
 const [confirmedRefusal,setConfirmedRefusal]=useState(false),[sourceLost,setSourceLost]=useState(false);
 const active=useRef<AbortController|null>(null),inFlight=useRef(false),live=useRef({identity,workspaceId:workspace.id,appointmentId:workspace.appointment_id,enabled,alive:true});
 live.current={...live.current,identity,workspaceId:workspace.id,appointmentId:workspace.appointment_id,enabled};
 const recovery=useEditorRecovery(workspace.id,'scheduling-patient',record.query||record.pending||record.preview||record.saved?
  editorDraft(workspace.id,'scheduling-patient',record,record.pending?.idempotency_key??null):null,busy||record.pending!==null,{required:true,identity});
 const liveJournal=useRef(recovery.access?.journal);liveJournal.current=recovery.access?.journal;
 const original=useRef({identity,workspaceId:workspace.id,appointmentId:workspace.appointment_id,journal:recovery.access?.journal});
 if(!original.current.journal&&recovery.access)original.current.journal=recovery.access.journal;
 const scopeInvalidated=useRef(false),availabilityUnchecked=useRef(false);if(!enabled)availabilityUnchecked.current=true;
 const observation=useRef({stamp:observationStamp,generation:0});
 if(observation.current.stamp!==observationStamp){observation.current={stamp:observationStamp,generation:observation.current.generation+1};availabilityUnchecked.current=true;}
 const changed=original.current.identity!==identity||original.current.workspaceId!==workspace.id||original.current.appointmentId!==workspace.appointment_id||
  !!original.current.journal&&!!recovery.access&&original.current.journal!==recovery.access.journal;
 if(changed)scopeInvalidated.current=true;const scopeChanged=scopeInvalidated.current;
 const selected=schedulingPatientSelected(record),expired=!!record.preview?.preview&&now>=Date.parse(record.preview.preview.expires_at);
 const withheld=authorityLost||sourceLost||scopeChanged||recovery.access===null||record.preview?.source_withheld===true||record.saved?.source_withheld===true||
  availabilityUnchecked.current&&(record.preview!==null||record.saved!==null);
 const previewVisible=record.pending===null&&verifiedPreview&&!withheld&&!expired&&!availabilityUnchecked.current;
 const ready=verifiedSaved&&!withheld&&!availabilityUnchecked.current&&record.saved?.status==='saved'&&!!record.saved.mapping;
 const disabled=!enabled||locked||busy||recovery.blocked||!!record.pending||authorityLost||scopeChanged;
 const pendingLocked=!enabled||(recoveryLocked??locked)||busy||recovery.blocked||authorityLost||scopeChanged;
 const unfinishedQuery=record.query.length>0&&record.saved===null;
 useUnsavedWork(!!record.pending||unfinishedQuery||busy||!!recovery.offer);
 useEffect(()=>{onBusyChange?.(busy||!!record.pending||!!recovery.offer||recovery.phase==='failed'||unfinishedQuery);return()=>onBusyChange?.(false);},[busy,record.pending,unfinishedQuery,recovery.offer,recovery.phase,onBusyChange]);
 useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;active.current?.abort();};},[]);
 useEffect(()=>{if(observation.current.generation===0)return;active.current?.abort();setVerifiedPreview(false);setVerifiedSaved(false);setSamePatient(false);setExactIdentity(false);setStatus(null);setNotFound(false);
  setMessage('Patient connection information changed. Check the saved setup again before viewing details or continuing.');},[observationStamp]);
 useEffect(()=>{if(!record.preview?.preview)return;const at=Date.parse(record.preview.preview.expires_at);setNow(Date.now());const timer=setTimeout(()=>{setNow(Date.now());setSamePatient(false);setExactIdentity(false);setVerifiedPreview(false);},Math.max(1,at-Date.now()+1));return()=>clearTimeout(timer);},[record.preview]);
 const sameOwner=(scope:{identity:AuthenticatedWorkspaceIdentity;workspaceId:string;appointmentId:string;generation:number})=>live.current.alive&&live.current.identity===scope.identity&&live.current.workspaceId===scope.workspaceId&&live.current.appointmentId===scope.appointmentId&&
  (!original.current.journal||liveJournal.current===original.current.journal);
 const current=(scope:Parameters<typeof sameOwner>[0])=>sameOwner(scope)&&live.current.enabled&&observation.current.generation===scope.generation;
 const requestScope=()=>({identity,workspaceId:workspace.id,appointmentId:workspace.appointment_id,generation:observation.current.generation});
 const fail=(cause:unknown)=>{if(cause instanceof SchedulingPatientRefusal&&['scheduling_patient_grant_unavailable','scheduling_patient_source_changed','scheduling_patient_account_changed','scheduling_patient_preview_superseded','scheduling_patient_preview_expired'].includes(cause.code??'')){
   setSourceLost(true);setVerifiedPreview(false);setVerifiedSaved(false);setSamePatient(false);setExactIdentity(false);
  }if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)){
   setAuthorityLost(true);setVerifiedPreview(false);setVerifiedSaved(false);setSamePatient(false);setExactIdentity(false);recovery.denied(cause);onAccessLost?.(cause);
  }if(cause instanceof SchedulingPatientRefusal&&cause.code==='scheduling_patient_mapping_review_required'){
   setSourceLost(true);setVerifiedPreview(false);setVerifiedSaved(false);setSamePatient(false);setExactIdentity(false);
  }setError(cause instanceof SchedulingPatientRefusal&&cause.code==='scheduling_patient_mapping_review_required'?
    'A patient connection is already saved. Check its saved details; ask your practice administrator to review any correction.':cause instanceof DraftStoreError?'Private storage could not save this step. Existing work is retained; recheck recovery.':
    'Patient setup could not be confirmed. Keep the exact request and check its saved result before trying anything new.');};
 async function authorize(){if(!recovery.access)throw new DraftStoreError('unavailable');const fresh=await recovery.access.authorize();
  if(fresh.id!==workspace.id||fresh.appointment_id!==workspace.appointment_id)throw new WorkspaceApiError(403);return fresh;}
 async function apply(receipt:SchedulingPatientReceipt,next:SchedulingPatientRecovery,scope:Parameters<typeof current>[0]){
  const confirmed=await validateSchedulingPatientRecovery({...next,pending:null,...(receipt.kind==='preview'?{preview:receipt,selected_choice_ref:null,saved:null}:{saved:receipt})},workspace.id);
  if(!current(scope))return;
  await recovery.commit(editorDraft(workspace.id,'scheduling-patient',confirmed));if(!current(scope)){
   // A connector refresh can land while the encrypted completion write is
   // finishing. Retain this exact command until explicit current-key inspection.
   if(next.pending&&sameOwner(scope))await recovery.commit(editorDraft(workspace.id,'scheduling-patient',next,next.pending.idempotency_key));
   return;
  }
  setRecord(confirmed);setNotFound(false);setSourceLost(receipt.source_withheld);setSamePatient(false);setExactIdentity(false);
  availabilityUnchecked.current=false;
  setVerifiedPreview(receipt.kind==='preview'&&!receipt.source_withheld||receipt.kind==='confirm'&&!receipt.source_withheld&&verifiedPreview);setVerifiedSaved(receipt.kind==='confirm'&&!receipt.source_withheld);
  setMessage(receipt.source_withheld?'The exact saved setup is confirmed. Patient details are unavailable until access is checked.':receipt.kind==='preview'?'Choose the matching patient below.':
    'Patient connection saved. You can prepare an appointment proposal; no appointment was booked.');
  if(receipt.kind==='confirm'&&!receipt.source_withheld)onLinked?.(receipt);
 }
 async function submit(command:SchedulingPatientCommand,retry=false){
  if(inFlight.current||pendingLocked||(!retry&&disabled))return;
  if(!validSchedulingPatientCommand(command))return;
  const scope=requestScope(),c=new AbortController();active.current=c;inFlight.current=true;setBusy(true);setError('');setMessage('');
  const next={...record,pending:structuredClone(command)};setRecord(next);setNotFound(false);setConfirmedRefusal(false);
  try{await authorize();if(!current(scope))return;await recovery.commit(editorDraft(workspace.id,'scheduling-patient',next,command.idempotency_key));if(!current(scope))return;
   const result=await schedulingPatientApi.command(identity,workspace.id,command,c.signal);if(!current(scope))return;
   if(result.status==='saved')await apply(result,next,scope);else{const retained={...next,...(command.action==='preview'?{preview:result}:{saved:null})};await recovery.commit(editorDraft(workspace.id,'scheduling-patient',retained,command.idempotency_key));if(!current(scope))return;
    setRecord(retained);setVerifiedPreview(false);setVerifiedSaved(false);setMessage('The service has an unfinished request. Check the saved result; no new lookup will be sent automatically.');}
  }catch(cause){if(current(scope)){setConfirmedRefusal(cause instanceof SchedulingPatientRefusal&&['workspace_revision_conflict','invalid_scheduling_patient_request','scheduling_patient_mapping_review_required'].includes(cause.code??''));fail(cause);}}
  finally{inFlight.current=false;if(active.current===c){active.current=null;if(live.current.alive)setBusy(false);}}
 }
 async function check(kind:'status'|'preview'|'pending'){
  if(inFlight.current||pendingLocked)return;const scope=requestScope(),c=new AbortController();active.current=c;inFlight.current=true;setBusy(true);setError('');setMessage('');
  try{await authorize();if(!current(scope))return;
   if(kind==='status'){const result=await schedulingPatientApi.status(identity,workspace.id,c.signal);if(current(scope)){setStatus(result);setVerifiedPreview(false);setVerifiedSaved(false);if(result.state==='link_required'){if(record.preview||record.saved)setSourceLost(true);setSamePatient(false);setExactIdentity(false);}
    setMessage(result.state==='linked'?'A patient connection is saved. Check the saved setup to show its current details.':'Search for the patient to connect this visit to Scheduling.');}}
   else if(kind==='preview'){
    const id=record.saved?.request_id??record.preview?.request_id;if(!id)return;
    const result=await schedulingPatientApi.inspect(identity,workspace.id,id,c.signal);if(!current(scope))return;
    const old=record.saved??record.preview!;if(result.request_key!==old.request_key||result.request_sha256!==old.request_sha256||result.source_sha256!==old.source_sha256)throw new WorkspaceApiError(502);
    if(result.status==='saved')await apply(result,record,scope);
   }else if(record.pending){
    const result=await schedulingPatientApi.resolve(identity,workspace.id,record.pending,c.signal);if(!current(scope))return;
    if(result.status==='saved'&&await schedulingPatientReceiptMatches(result,workspace.id,record.pending))await apply(result,record,scope);
    else if(result.status==='not_found'){setNotFound(true);setMessage('No saved request was found. You may explicitly retry the same request; its original key is retained.');}
    else{setNotFound(false);setVerifiedPreview(false);setVerifiedSaved(false);setMessage('The original request remains unfinished. Check again later; a second provider lookup will not be sent.');}
   }
  }catch(cause){if(current(scope))fail(cause);}finally{inFlight.current=false;if(active.current===c){active.current=null;if(live.current.alive)setBusy(false);}}
 }
 async function reset(){if(record.pending||record.saved||pendingLocked)return;const scope=requestScope();setBusy(true);try{await authorize();if(!current(scope))return;await recovery.commit(null);if(current(scope)){setRecord(emptySchedulingPatientRecovery(workspace.id,workspace.appointment_id));setSourceLost(false);setVerifiedPreview(false);setVerifiedSaved(false);setStatus(null);setSamePatient(false);setExactIdentity(false);}}
  catch(cause){fail(cause);}finally{setBusy(false);}}
 async function setAside(){if(!record.pending||!notFound||!confirmedRefusal||pendingLocked)return;const scope=requestScope();setBusy(true);
  try{await authorize();if(!current(scope))return;await recovery.commit(null);if(!current(scope))return;setRecord(emptySchedulingPatientRecovery(workspace.id,workspace.appointment_id));setSourceLost(false);setVerifiedPreview(false);setVerifiedSaved(false);setNotFound(false);setConfirmedRefusal(false);setSamePatient(false);setExactIdentity(false);}
  catch(cause){fail(cause);}finally{setBusy(false);}}
 function choose(choice:SchedulingPatientChoice){if(disabled||!previewVisible)return;setRecord({...record,selected_choice_ref:choice.choice_ref});setSamePatient(false);setExactIdentity(false);}
 function search(){const command:SchedulingPatientCommand={action:'preview',expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),search:{kind:'search',query:record.query.trim(),birth_date:record.birth_date}};
  if(validSchedulingPatientCommand(command))void submit(command);}
 function confirm(){if(!selected||!previewVisible||!samePatient||!exactIdentity||!record.preview?.request_id||!record.preview.source_sha256)return;
  void submit({action:'confirm',expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),preview_id:record.preview.request_id,preview_sha256:record.preview.source_sha256,
   choice_ref:selected.choice_ref,identity_sha256:selected.identity_sha256,reviewed_same_patient:true,reviewed_exact_identity:true});}
 if(!enabled)return <section aria-label="Scheduling patient setup"><h3>📅 Patient connection</h3><p role="status">Setup unavailable</p><p>Scheduling patient lookup needs a qualified connection for this practice.</p></section>;
 if(authorityLost||scopeChanged)return <section aria-label="Scheduling patient setup"><h3>📅 Patient connection</h3><p role="alert">Patient access is unavailable. Private details are withheld and your saved setup is retained.</p></section>;
 return <section className="scheduling-patient-panel" aria-label="Scheduling patient setup" aria-busy={busy||recovery.phase==='checking'}>
  <h3>📅 {ready?'Patient ready':'Connect the patient'}</h3><p role="status">{ready?'Ready for appointment proposals':busy?'Checking patient setup…':record.pending?'Setup needs confirmation':withheld?'Details unavailable':'Setup needed'}</p>
  <p>Connect this visit to the correct Scheduling patient. Date of birth is optional. This does not book or change a visit.</p>
  <EditorRecoveryNotice recovery={recovery} label="Scheduling patient" onRestore={async(draft,fresh,isCurrent)=>{
    const restored=await validateSchedulingPatientRecovery(draft.data,workspace.id);if(fresh.appointment_id!==restored.appointment_id)throw new WorkspaceApiError(403);
    if(isCurrent()){setRecord(restored);setVerifiedPreview(false);setVerifiedSaved(false);setSamePatient(false);setExactIdentity(false);setNotFound(false);setMessage('Your setup was restored. Check the saved result before viewing patient choices or continuing. Nothing was submitted.');}
  }}/>
  {ready&&selected&&<p><strong>{selected.display_name}</strong> · {selected.birth_date??'DOB not supplied'}<br/>Patient connection saved; no booking made.</p>}
  {!record.pending&&!record.saved&&!ready&&!withheld&&<div style={{display:'grid',gap:8,minWidth:0,maxWidth:480}}>
   <label>Patient name<input aria-label="Patient name" value={record.query} maxLength={120} disabled={disabled} onChange={e=>{setRecord({...record,query:e.target.value,preview:null,selected_choice_ref:null,saved:null});setVerifiedPreview(false);setSamePatient(false);setExactIdentity(false);}}/></label>
   <label>Date of birth (optional)<input type="date" aria-label="Date of birth (optional)" value={record.birth_date??''} disabled={disabled} onChange={e=>{setRecord({...record,birth_date:e.target.value||null,preview:null,selected_choice_ref:null,saved:null});setVerifiedPreview(false);setSamePatient(false);setExactIdentity(false);}}/></label>
   <button type="button" disabled={disabled||!record.query.trim()||!validSchedulingPatientDate(record.birth_date)} onClick={search}>Find patient</button>
  </div>}
  {!record.pending&&!ready&&<button type="button" disabled={disabled} onClick={()=>void check('status')}>Check patient setup</button>}
  {!record.pending&&(record.preview||record.saved)&&<button type="button" disabled={disabled} onClick={()=>void check('preview')}>Check saved patient details</button>}
  {!record.saved&&previewVisible&&record.preview?.preview&&<div>
   {!record.preview.preview.choices.length&&<p>No matching patients were returned. Try a more specific name or add DOB if available.</p>}
   {record.preview.preview.more&&<p>More matches exist. Narrow the name or add DOB if available; only five choices are shown.</p>}
   <div role="group" aria-label="Patient matches" style={{display:'grid',gap:6}}>{record.preview.preview.choices.map(choice=><button type="button" key={choice.choice_ref} aria-pressed={choice.choice_ref===record.selected_choice_ref} disabled={disabled} onClick={()=>choose(choice)}>
    {choice.display_name} · {choice.birth_date??'DOB not supplied'}</button>)}</div>
   {selected&&<div><p>Selected: <strong>{selected.display_name}</strong> · {selected.birth_date??'DOB not supplied'}</p>
    <label><input type="checkbox" checked={samePatient} disabled={disabled} onChange={e=>setSamePatient(e.target.checked)}/> This is the patient for this visit.</label><br/>
    <label><input type="checkbox" checked={exactIdentity} disabled={disabled} onChange={e=>setExactIdentity(e.target.checked)}/> I checked the displayed name and DOB, including any missing DOB.</label><br/>
    <button type="button" disabled={disabled||!samePatient||!exactIdentity} onClick={confirm}>Save patient connection</button></div>}
  </div>}
  {expired&&!record.pending&&<p role="alert">Patient choices expired. Search again to check current details.</p>}
  {withheld&&<p role="alert">Current source access is unavailable. Patient names and DOB are withheld; check access before continuing.</p>}
  {record.pending&&<div><p>Keep this exact {record.pending.action==='preview'?'patient search':'patient confirmation'} until its saved result is checked.</p>
   <button type="button" disabled={pendingLocked} onClick={()=>void check('pending')}>Check saved setup result</button>
   {notFound&&<button type="button" disabled={pendingLocked} onClick={()=>void submit(record.pending!,true)}>Retry same setup request</button>}
   {notFound&&confirmedRefusal&&<button type="button" disabled={pendingLocked} onClick={()=>void setAside()}>Set aside unsuccessful setup</button>}</div>}
  {!record.pending&&!record.saved&&(record.query||record.preview)&&<button type="button" disabled={pendingLocked} onClick={()=>void reset()}>Start a new patient search</button>}
  {record.saved&&<p>A patient connection is already saved. Ask your practice administrator to review any correction.</p>}
  {status?.state==='linked'&&!ready&&<p>A mapping is saved. Its patient identity has not been shown until the saved receipt is checked.</p>}
  {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
 </section>;
}
