import {useEffect,useRef,useState} from 'react';
import {coreConnectionApi} from './core-connection-api';
import type {AthenaAccount,AthenaAppointment} from './athena-connection-contract';
import type {AthenaSourceSelection,AthenaVisitLinkCommand,AthenaVisitLinkObservation} from './athena-visit-link-api';
import type {CoreConnection,CoreConnectionCommand,CoreConnectionResult,CoreCursor,CoreEncounter,CoreWindow} from './core-connection-contract';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

type Props={identity:AuthenticatedWorkspaceIdentity;connection:CoreConnection;account:AthenaAccount;source:AthenaAppointment;selection:AthenaSourceSelection;
 onBusyChange?:(busy:boolean)=>void;onAccessLost:(error:unknown)=>void;onClose:()=>void;onOpenNotebook?:(command:CoreConnectionCommand)=>Promise<void>;openBlocked?:boolean};
type Stored<T>={identity:AuthenticatedWorkspaceIdentity;scope:string;value:T};
type Review={command:AthenaVisitLinkCommand;observation:AthenaVisitLinkObservation};
type Pending={command_key:string;command_sha256:string;target:
 {operation:'link';appointment_ref:string;patient_ref:string}|{operation:'unlink';link_ref:string}};
function matchesPending(result:AthenaVisitLinkObservation,pending:Pending){
 if(!result.applied)return true;
 const target=pending.target;
 if(result.operation!==target.operation)return false;
 if(target.operation==='unlink')return result.state==='removed'&&result.link_ref===target.link_ref;
 // Status may return a newer projection, but it must still be the reviewed patient and visit.
 return !result.encounter||result.encounter.appointment.appointment_ref===target.appointment_ref&&result.encounter.patient.patient_ref===target.patient_ref;
}
function coreWindow(selection:AthenaSourceSelection):CoreWindow{
 const end=new Date(selection.end_date+'T00:00:00Z');end.setUTCDate(end.getUTCDate()+1);
 return {start_date:selection.start_date,end_date:end.toISOString().slice(0,10)};
}
function visitTime(encounter:CoreEncounter){const a=encounter.appointment;return a.timezone_known?new Date(a.appointment_date).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):a.appointment_date.slice(0,19).replace('T',' ');}

export function AthenaVisitLinkPanel({identity,connection,account,source,selection,onBusyChange,onAccessLost,onClose,onOpenNotebook,openBlocked=false}:Props){
 const scope=JSON.stringify([connection.connection_sha256,account.account_sha256,selection]);
 const currentScope=useRef({identity,scope});currentScope.current={identity,scope};
 const [stored,setStored]=useState<Stored<AthenaVisitLinkObservation>|null>(null),[storedPage,setStoredPage]=useState<Stored<CoreConnectionResult>|null>(null);
 const [storedReview,setStoredReview]=useState<Stored<Review>|null>(null),[storedPending,setStoredPending]=useState<Stored<Pending>|null>(null);
 const [window,setWindow]=useState(()=>coreWindow(selection)),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const epoch=useRef(0),running=useRef(false),controller=useRef<AbortController|null>(null);
 const visible=<T,>(value:Stored<T>|null)=>value?.identity===identity&&value.scope===scope?value.value:null;
 const observation=visible(stored),page=visible(storedPage),review=visible(storedReview),pending=visible(storedPending);
 const remember=<T,>(value:T):Stored<T>=>({identity,scope,value});
 useSetupNavigationBusy(busy||pending!==null,onBusyChange);
 useEffect(()=>{
  epoch.current++;controller.current?.abort();running.current=false;setStored(null);setStoredPage(null);setStoredReview(null);setStoredPending(null);setConfirmed(false);setWindow(coreWindow(selection));setError('');setBusy(false);
  void run(base('athena_visit_lookup',{source:selection}));
  return()=>{epoch.current++;controller.current?.abort();running.current=false;};
 // The serialized scope includes every selected source field; callbacks do not define ownership.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[identity,scope]);
 function base(action:AthenaVisitLinkCommand['action'],fields:Partial<AthenaVisitLinkCommand>={}):AthenaVisitLinkCommand{
  return {action,request_nonce:crypto.randomUUID(),connection_sha256:connection.connection_sha256,account_sha256:account.account_sha256,...fields};
 }
 async function run(command:AthenaVisitLinkCommand){
  if(running.current)return;
  running.current=true;const version=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
  const isCurrent=()=>version===epoch.current&&currentScope.current.identity===identity&&currentScope.current.scope===scope;
  const write=command.action==='athena_visit_link'||command.action==='athena_visit_unlink';
  setBusy(true);setError('');
  if(command.action==='athena_visit_lookup'){setStored(null);setStoredReview(null);setStoredPage(null);setConfirmed(false);}
  try{
   const result=(await coreConnectionApi.read(identity,command,abort.signal)).athena_visit_link;
   if(!isCurrent())return;
   if(command.action==='athena_visit_status'&&(!pending||!matchesPending(result,pending)))throw new WorkspaceApiError(502);
   setStored(remember(result));
   if(command.action==='athena_visit_preview'||command.action==='athena_visit_unlink_preview'){
    setStoredReview(result.state==='ready'&&result.plan_sha256&&result.command_sha256?remember({command,observation:result}):null);setConfirmed(false);
   }else setStoredReview(null);
   if(write||command.action==='athena_visit_status'){setStoredPending(null);setConfirmed(false);setStoredPage(null);}
  }catch(cause){
   if(!isCurrent())return;
   if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)){onAccessLost(cause);return;}
   if(write||command.action==='athena_visit_status')setError('The saved result could not be verified. Check the saved result before making another change.');
   else if(cause instanceof WorkspaceApiError&&cause.status===409){setStoredReview(null);setConfirmed(false);setError('The appointment or connection changed. Close this view and refresh the Athena schedule before reviewing again.');}
   else setError(cause instanceof WorkspaceApiError&&cause.status===404?'Visit linking is not enabled for this practice yet.':'This connection could not be checked. Try again.');
  }finally{if(isCurrent()){running.current=false;setBusy(false);}}
 }
 async function loadVisits(cursor?:CoreCursor){
  if(running.current||pending)return;
  const days=(Date.parse(window.end_date)-Date.parse(window.start_date))/86400000;
  if(!Number.isFinite(days)||days<1||days>31){setError('Choose a date range of 1 to 31 days.');return;}
  running.current=true;const version=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
  const isCurrent=()=>version===epoch.current&&currentScope.current.identity===identity&&currentScope.current.scope===scope;
  setBusy(true);setError('');setStoredPage(null);setStoredReview(null);setConfirmed(false);
  try{
   const received=await coreConnectionApi.read(identity,{action:'encounters',request_nonce:crypto.randomUUID(),connection_sha256:connection.connection_sha256,window,...(cursor?{cursor}:{})},abort.signal);
   if(isCurrent())setStoredPage(remember(received));
  }catch(cause){
   if(!isCurrent())return;
   if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)){onAccessLost(cause);return;}
   setError('Available Cosmaneura visits could not be loaded. Check the connection and try again.');
  }finally{if(isCurrent()){running.current=false;setBusy(false);}}
 }
 function save(){
  if(!review||!confirmed||busy||pending)return;
  const r=review.observation;
  if(!r.command_key||!r.command_sha256||!r.plan_sha256)return;
  const command:AthenaVisitLinkCommand={...review.command,action:review.command.action==='athena_visit_preview'?'athena_visit_link':'athena_visit_unlink',request_nonce:crypto.randomUUID(),plan_sha256:r.plan_sha256,confirmed:true};
  const target:Pending['target']|null=command.action==='athena_visit_link'
   ?command.appointment_ref&&r.encounter?{operation:'link',appointment_ref:command.appointment_ref,patient_ref:r.encounter.patient.patient_ref}:null
   :command.link_ref?{operation:'unlink',link_ref:command.link_ref}:null;
  if(!target)return;
  setStoredPending(remember({command_key:r.command_key,command_sha256:r.command_sha256,target}));
  void run(command);
 }
 async function openVisit(){
  const e=observation?.encounter;if(!e||!onOpenNotebook||openBlocked||running.current||pending)return;
  running.current=true;const version=++epoch.current;setBusy(true);setError('');
  const isCurrent=()=>version===epoch.current&&currentScope.current.identity===identity&&currentScope.current.scope===scope;
  try{await onOpenNotebook({action:'open',request_nonce:crypto.randomUUID(),connection_sha256:e.connection_sha256,appointment_ref:e.appointment.appointment_ref,source_sha256:e.source_sha256});}
  catch{if(isCurrent())setError('The visit could not be opened. Check its current connection and try again.');}
  finally{if(isCurrent()){running.current=false;setBusy(false);}}
 }
 const locked=busy||pending!==null;
 const canChoose=observation&&['not_linked','removed'].includes(observation.state)&&!review&&!pending;
 return <section className="athena-visit-link" aria-label="Connect Athena visit">
  <h4>Connect Athena visit</h4>
  <p>Athena appointment {source.appointment_ref} · Patient reference {source.patient_ref}</p>
  <p>{source.source_local_start.replace('T',' ')} · {account.department_label}</p>
  <p>This saves a connection to an existing Cosmaneura visit. Athena stays read-only.</p>
  {error&&<p role="alert">{error}</p>}
  {busy&&<p role="status">Checking visit connection…</p>}
  {pending&&<div role="status"><p>The result of your last change needs to be checked.</p><button disabled={busy} onClick={()=>void run(base('athena_visit_status',{command_key:pending.command_key,command_sha256:pending.command_sha256}))}>Check saved result</button></div>}
  {!pending&&<button disabled={busy} onClick={()=>void run(base('athena_visit_lookup',{source:selection}))}>Check current visit connection</button>}
  {observation?.state==='review_required'&&!pending&&<p role="status">This patient or visit connection needs review. Ask your practice administrator to review the patient match before continuing.</p>}
  {observation?.state==='review_required'&&observation.link_ref&&!pending&&<button disabled={busy} onClick={()=>void run(base('athena_visit_unlink_preview',{link_ref:observation.link_ref!,command_key:crypto.randomUUID()}))}>Review removing connection</button>}
  {observation?.state==='not_found'&&!pending&&<p role="status">No saved result was found for that change. Check the current connection and review again before saving.</p>}
  {observation?.state==='removed'&&!review&&!pending&&<p role="status">The visit connection was removed. Its history is retained.</p>}
  {observation?.state==='linked'&&observation.encounter&&!pending&&<div>
   <p role="status">Connected to {observation.encounter.patient.display_name}</p><p>{visitTime(observation.encounter)}</p>
   {openBlocked&&<p>Save or recover unfinished work before opening a notebook.</p>}
   {onOpenNotebook&&<button disabled={busy||openBlocked} onClick={()=>void openVisit()}>Open linked notebook</button>}
   <button disabled={busy} onClick={()=>void run(base('athena_visit_unlink_preview',{link_ref:observation.link_ref!,command_key:crypto.randomUUID()}))}>Review removing connection</button>
  </div>}
  {canChoose&&<div>
   <h5>Choose an existing Cosmaneura visit</h5>
   <p>Verify the patient in Athena, then select the same patient and visit below.</p>
   <div className="connection-date-range"><label>Visits from<input type="date" value={window.start_date} disabled={locked} onChange={e=>{setWindow({...window,start_date:e.target.value});setStoredPage(null);}}/></label>
    <label>Visits before<input type="date" value={window.end_date} disabled={locked} onChange={e=>{setWindow({...window,end_date:e.target.value});setStoredPage(null);}}/></label></div>
   <button disabled={locked} onClick={()=>void loadVisits()}>Find Cosmaneura visits</button>
   {page&&<><ul className="connection-appointments">{page.discovery.encounters.map(e=><li key={e.appointment.appointment_ref}>
    <strong>{e.patient.display_name}</strong><span>{visitTime(e)}</span>{!e.appointment.timezone_known&&<small>Time zone not supplied by the practice</small>}
    <button disabled={locked} onClick={()=>void run(base('athena_visit_preview',{source:selection,appointment_ref:e.appointment.appointment_ref,core_source_sha256:e.source_sha256,command_key:crypto.randomUUID()}))}>Review this visit</button>
   </li>)}</ul>{!page.discovery.encounters.length&&<p>No available visits on this page. Check another date range or connect your existing appointments.</p>}
   {page.discovery.next_cursor&&<button disabled={locked} onClick={()=>void loadVisits(page.discovery.next_cursor!)}>Next Cosmaneura visits</button>}</>}
  </div>}
  {review&&!pending&&<div className="connection-review">
   <h5>{review.command.action==='athena_visit_preview'?'Confirm the patient and visit':'Remove this visit connection?'}</h5>
   {review.observation.encounter&&<><strong>{review.observation.encounter.patient.display_name}</strong><p>{visitTime(review.observation.encounter)}</p></>}
   <p>Athena patient reference {source.patient_ref} · Appointment {source.appointment_ref}</p>
   <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>{review.command.action==='athena_visit_preview'?'I verified that these are the same patient and visit.':'I want to remove this connection and retain its history.'}</label>
   <button disabled={busy||!confirmed} onClick={save}>{review.command.action==='athena_visit_preview'?'Save visit connection':'Remove visit connection'}</button>
   <button disabled={busy} onClick={()=>void run(base('athena_visit_lookup',{source:selection}))}>Cancel review</button>
  </div>}
  <button disabled={locked} onClick={onClose}>Close visit connection</button>
 </section>;
}
