import {useEffect,useRef,useState} from 'react';
import {SchedulingGoogleHandoff} from './SchedulingGoogleHandoff';
import {schedulingEnrollmentRequest,type EnrollmentCommand,type EnrollmentResponse,type EnrollmentReview,type EnrollmentReceipt,type EnrollmentStatus} from './scheduling-enrollment-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
type Review={request:EnrollmentCommand;response:EnrollmentReview};
type Stored<T>={identity:AuthenticatedWorkspaceIdentity;value:T};
export function SchedulingEnrollmentPanel({identity,onBusyChange,onAuthenticationLost,onConnected}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void;onConnected:()=>void}){
 const [stored,setStored]=useState<Stored<EnrollmentResponse>|null>(null),[storedReview,setStoredReview]=useState<Stored<Review>|null>(null),[storedPending,setStoredPending]=useState<Stored<EnrollmentCommand>|null>(null);
 const [busy,setBusy]=useState(false),[handoffBusy,setHandoffBusy]=useState(false),[message,setMessage]=useState(''),[location,setLocation]=useState(''),[kind,setKind]=useState(''),[confirmed,setConfirmed]=useState(false);
 const epoch=useRef(0),controller=useRef<AbortController|null>(null),running=useRef(false),current=useRef(identity);current.current=identity;
 const visible=<T,>(value:Stored<T>|null)=>value?.identity===identity?value.value:null;
 const result=visible(stored),review=visible(storedReview),pending=visible(storedPending),start=result&&'authorization_url' in result?result:null;
 const status=result&&'catalog' in result&&result.state!=='ready'?result as EnrollmentStatus:null;
 const receipt=result&&'applied' in result?result as EnrollmentReceipt:null;
 const catalog=status?.catalog,locked=busy||handoffBusy||!!pending;
 useSetupNavigationBusy(locked,onBusyChange);
 useEffect(()=>{
  epoch.current++;controller.current?.abort();running.current=false;setStored(null);setStoredReview(null);setStoredPending(null);setBusy(false);setHandoffBusy(false);setMessage('');setConfirmed(false);setLocation('');setKind('');
  void run({action:'enrollment_status'});
  return()=>{epoch.current++;controller.current?.abort();running.current=false;};
 // Callback identity does not change the authenticated account.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[identity]);
 async function run(command:EnrollmentCommand){
  if(running.current)return;
  running.current=true;const version=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
  const isCurrent=()=>current.current===identity&&version===epoch.current;
  setBusy(true);setMessage('');
  if(command.action==='enrollment_status'){setStoredReview(null);setConfirmed(false);setStored(null);}
  try{
   const received=await schedulingEnrollmentRequest(identity,command,abort.signal);if(!isCurrent())return;
   setStored({identity,value:received});
   if('state' in received&&received.state==='ready'){setStoredReview({identity,value:{request:command,response:received}});setConfirmed(false);}
   if(command.action==='enrollment_confirm'||command.action==='enrollment_result'){setStoredPending(null);setStoredReview(null);setConfirmed(false);}
   if('catalog' in received&&received.state!=='ready'&&received.catalog){
    setLocation(received.catalog.locations[0]?.id??'');setKind(received.catalog.appointment_types[0]?.id??'');
   }
   if('state' in received&&received.state==='connected')onConnected();
  }catch(cause){
   if(!isCurrent())return;
   if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)){onAuthenticationLost(cause);return;}
   if(command.action==='enrollment_confirm'||command.action==='enrollment_result')setMessage('The connection result could not be confirmed. Check the saved result before making another change.');
   else if(cause instanceof WorkspaceApiError&&cause.status===404)setMessage('First-time Scheduling connection is not enabled for this practice yet.');
   else if(cause instanceof WorkspaceApiError&&cause.status===409){setStored(null);setStoredReview(null);setConfirmed(false);setMessage('Practice access or setup changed. Check the connection again before continuing.');}
   else setMessage('Scheduling could not verify this connection. Use the account invited to your practice, then check again.');
  }finally{if(isCurrent()){running.current=false;setBusy(false);}}
 }
 function save(){
  if(!review||!confirmed||locked)return;
  const command:EnrollmentCommand={...review.request,action:'enrollment_confirm',plan_sha256:review.response.plan_sha256,confirmed:true};
  setStoredPending({identity,value:{action:'enrollment_result',attempt_ref:review.response.attempt_ref,command_key:review.response.command_key,command_sha256:review.response.command_sha256}});
  void run(command);
 }
 return <section aria-label="First Scheduling connection" className="core-connection-setup">
  <h3>Connect your practice account</h3><p>Already joined your Scheduling practice? Sign in with the account you used to accept its invitation.</p>
  {message&&<p role="status">{message}</p>}
  {busy&&<p role="status">Checking connection…</p>}
  {pending?<><p>Your last confirmation needs to be checked.</p><button disabled={busy||handoffBusy} onClick={()=>void run(pending)}>Check saved connection result</button></>:
   <button disabled={locked} onClick={()=>void run({action:'enrollment_status'})}>Check practice connection</button>}
  {status?.state==='not_connected'&&<button disabled={locked} onClick={()=>void run({action:'enrollment_start'})}>Connect my Scheduling account</button>}
  {status?.state==='sign_in_pending'&&<button disabled={locked} onClick={()=>void run({action:'enrollment_start'})}>Continue Scheduling sign-in</button>}
  {status?.state==='completing_sign_in'&&<p>Sign-in is still completing. Check the connection again after returning from Google.</p>}
  {status?.state==='review_required'&&<p>Your practice administrator needs to review this account connection.</p>}
  {receipt?.state==='not_found'&&<p>No saved confirmation was found. Check the current connection and review it again before confirming.</p>}
  {receipt?.state==='review_required'&&<p>The earlier confirmation was saved, but the connection now needs practice review.</p>}
  {start&&<SchedulingGoogleHandoff key={start.authorization_url} identity={identity} start={start} disabled={busy||!!pending} onReturn={()=>void run({action:'enrollment_status'})} onMessage={setMessage} onBusyChange={setHandoffBusy}/>}
  {status?.state==='setup_required'&&catalog&&<div><strong>{catalog.practice.label}</strong><p>{!catalog.practitioner?'Finish your practitioner setup in Scheduling using this same account.':'Ask your practice administrator to finish the location and appointment-type setup in Scheduling.'} Then check this connection again.</p></div>}
  {status?.state==='choose_schedule'&&catalog&&<div>
   <strong>{catalog.practice.label}</strong><p>{catalog.practitioner!.label}</p>
   <label>Scheduling location<select value={location} disabled={locked} onChange={e=>setLocation(e.target.value)}>{catalog.locations.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}</select></label>
   <label>Default appointment type<select value={kind} disabled={locked} onChange={e=>setKind(e.target.value)}>{catalog.appointment_types.map(v=><option key={v.id} value={v.id}>{v.label} · {v.duration_minutes} minutes</option>)}</select></label>
   <button disabled={locked||!location||!kind} onClick={()=>void run({action:'enrollment_review',attempt_ref:status.attempt_ref!,catalog_sha256:catalog.catalog_sha256,location_id:location,appointment_type_id:kind,command_key:crypto.randomUUID()})}>Review practice connection</button>
  </div>}
  {review&&!pending&&<div>
   <h4>Confirm your Scheduling account</h4><strong>{review.response.catalog.practice.label}</strong><p>{review.response.catalog.practitioner!.label}</p>
   <p>{review.response.catalog.locations.find(v=>v.id===review.response.location_id)!.label} · {review.response.catalog.appointment_types.find(v=>v.id===review.response.appointment_type_id)!.label}</p>
   <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>This is my practice account and the schedule I want to use.</label>
   <button disabled={busy||!confirmed} onClick={save}>Confirm practice connection</button>
   <button disabled={busy} onClick={()=>void run({action:'enrollment_status'})}>Change selection</button>
  </div>}
  {!pending&&(start||status&&['sign_in_pending','completing_sign_in','choose_schedule','setup_required'].includes(status.state)||review)&&<button disabled={locked} onClick={()=>{setStoredReview(null);void run({action:'enrollment_cancel'});}}>Cancel new connection</button>}
  {result&&'state' in result&&result.state==='cancelled'&&<p>New connection cancelled. Check the connection when you are ready to start again.</p>}
 </section>;
}
