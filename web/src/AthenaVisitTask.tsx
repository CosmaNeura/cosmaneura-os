import {useContext,useEffect,useRef,useState,type ContextType} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountIdentityApi} from './account-identity-api';
import {accountEditorAddress} from './draft-journal';
import {CoreConnectionPanel} from './CoreConnectionPanel';
import {athenaVisitTime} from './AthenaVisitLinkPanel';
import {coreConnectionApi} from './core-connection-api';
import type {CoreConnectionCommand} from './core-connection-contract';
import {EhrReadTask} from './EhrReadTask';
import {ATHENA_VISIT_LINK_BUILD,type AthenaVisitLinkObservation} from './athena-visit-link-api';
import {AthenaVisitRecoveryError,AthenaVisitRecoverySession,type AthenaVisitRecoveryRecord,type AthenaVisitRecoveryScope} from './athena-visit-link-recovery';
import {DraftStoreError} from './draft-store';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,validRecoveryScope} from './workspace-api';
import {useGoogleNativeForeground} from './use-google-native-foreground';
import './athena-visit.css';

const address=accountEditorAddress('athena-visit-link');
type Owned={generation:number;identity:AuthenticatedWorkspaceIdentity;context:NonNullable<ContextType<typeof AccountRecoveryContext>>;scope:AthenaVisitRecoveryScope;session:AthenaVisitRecoverySession;record:AthenaVisitRecoveryRecord|null};
export type AthenaVisitTaskProps={identity:AuthenticatedWorkspaceIdentity;open:boolean;returnLabel:string;contextLabel?:string;onReturn:()=>void;onBusyChange?:(busy:boolean)=>void;
 onAuthenticationLost:(cause:unknown)=>void;onOpenNotebook:(command:CoreConnectionCommand,current:()=>boolean)=>Promise<void>;openingError?:string;locked?:boolean;openBlocked?:boolean;enabled?:boolean};
/** One account-owned host shared by Chief and Settings; hiding it retains recovery. */
export function AthenaVisitTask({identity,open,returnLabel,contextLabel,onReturn,onBusyChange,onAuthenticationLost,onOpenNotebook,openingError='',locked=false,openBlocked=false,enabled=ATHENA_VISIT_LINK_BUILD}:AthenaVisitTaskProps){
 const context=useContext(AccountRecoveryContext),namespace=context?.recoveryScope;
 const [owned,setOwned]=useState<Owned|null>(null),[mode,setMode]=useState<'saved'|'schedule'>('saved'),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const [busy,setBusy]=useState(false),[childBusy,setChildBusy]=useState(false),[result,setResult]=useState<AthenaVisitLinkObservation|null>(null);
 const live=useRef({identity,context,namespace,enabled,generation:0});
 const mountedSession=useRef<AthenaVisitRecoverySession|null>(null);
 if(live.current.identity!==identity||live.current.context!==context||live.current.namespace!==namespace||live.current.enabled!==enabled)live.current={identity,context,namespace,enabled,generation:live.current.generation+1};
 const callbacks=useRef({onAuthenticationLost,onBusyChange});callbacks.current={onAuthenticationLost,onBusyChange};
 const native=useGoogleNativeForeground(identity,{suspended:()=>{live.current.generation++;mountedSession.current?.close();setOwned(null);setResult(null);setBusy(false);setChildBusy(false);},resumed:()=>setRetry(value=>value+1)});
 useEffect(()=>{callbacks.current.onBusyChange?.(busy||childBusy);return()=>callbacks.current.onBusyChange?.(false);},[busy,childBusy]);
 useEffect(()=>{
  const generation=++live.current.generation;let active=true,session:AthenaVisitRecoverySession|undefined;setOwned(null);setResult(null);setError('');setBusy(false);setChildBusy(false);
  const current=()=>active&&native.foreground.current&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.namespace===namespace&&live.current.enabled;
  if(enabled&&native.foreground.current&&context&&validRecoveryScope(namespace))void(async()=>{
   await context.authorize();if(!current())return;
   const account=await accountIdentityApi.read(identity);if(!current())return;
   if(account.recovery_scope!==namespace)throw new WorkspaceApiError(403);
   const scope={box_id:account.box_id,owner_id:account.actor_id,recovery_scope:account.recovery_scope};
   const authorize=async()=>{if(!current())throw new WorkspaceApiError(403);await context.authorize();if(!current())throw new WorkspaceApiError(403);
    const next=await accountIdentityApi.read(identity);if(!current()||next.box_id!==scope.box_id||next.actor_id!==scope.owner_id||next.recovery_scope!==scope.recovery_scope)throw new WorkspaceApiError(403);};
   session=new AthenaVisitRecoverySession(scope,{authorize,current,load:async()=>{const saved=await context.journal.load(address);if(!saved)return null;
    if(saved.kind!=='account-editor'||saved.editor!=='athena-visit-link'||saved.pending!==null)throw new DraftStoreError('integrity');return saved.data;},
    persist:async record=>{await context.journal.persist(address,{kind:'account-editor',editor:'athena-visit-link',data:record,pending:null});}},command=>coreConnectionApi.read(identity,command));
   mountedSession.current=session;
   const record=await session.restore();if(!current())return;
   setOwned({generation,identity,context,scope,session,record});setMode(record?'saved':'schedule');
  })().catch(cause=>{if(!current())return;setError('Private Athena visit work could not be opened. Recheck this account before continuing.');
   if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)||cause instanceof AthenaVisitRecoveryError&&cause.code==='scope_changed')callbacks.current.onAuthenticationLost(new WorkspaceApiError(403));});
  return()=>{active=false;live.current.generation++;session?.close();};
 },[identity,context,namespace,enabled,retry]);
 const visible=native.foreground.current&&owned?.generation===live.current.generation&&owned.identity===identity&&owned.context===context&&owned.scope.recovery_scope===namespace?owned:null;
 const lockedNow=locked||busy||childBusy;
 const update=()=>{if(!visible)return;try{const record=visible.session.snapshot();setOwned({...visible,record});if(record?.resolution===null){setResult(null);setMode('saved');}}catch{setOwned(null);setResult(null);}};
 async function check(){
  if(!visible||lockedNow)return;const selected=visible;setBusy(true);setError('');setResult(null);
  try{const observed=await selected.session.check();if(live.current.generation!==selected.generation||live.current.identity!==selected.identity||live.current.context!==selected.context)return;
   setResult(observed);setOwned({...selected,record:selected.session.snapshot()});
  }catch(cause){
   if(live.current.generation!==selected.generation||live.current.identity!==selected.identity||live.current.context!==selected.context)return;
   setError('The saved visit result could not be verified. Check it again before making another change.');
   if(cause instanceof AthenaVisitRecoveryError&&cause.code==='scope_changed'){setOwned(null);callbacks.current.onAuthenticationLost(new WorkspaceApiError(403));}
  }finally{if(live.current.generation===selected.generation&&live.current.identity===selected.identity&&live.current.context===selected.context)setBusy(false);}
 }
 async function requestNotebook(command:CoreConnectionCommand){
  if(!visible||locked||busy||openBlocked)return;const selected=visible;setBusy(true);setError('');
  const current=()=>native.foreground.current&&live.current.generation===selected.generation&&live.current.identity===selected.identity&&live.current.context===selected.context;
  try{await selected.context.authorize();if(!current())return;await onOpenNotebook(command,current);}
  catch{if(current())setError('The linked notebook could not be opened. Check the saved result again.');}finally{if(current())setBusy(false);}
 }
 async function openNotebook(){
  const encounter=result?.encounter;if(!encounter||lockedNow)return;
  await requestNotebook({action:'open',request_nonce:crypto.randomUUID(),connection_sha256:encounter.connection_sha256,appointment_ref:encounter.appointment.appointment_ref,source_sha256:encounter.source_sha256});
 }
 if(!enabled)return null;
 return <EhrReadTask title="Find or connect an Athena visit" open={open} context={native.suspended?'Return to the app to continue.':contextLabel?`Starting from ${contextLabel}. Review the Athena appointment and its matching practice visit.`:'Review the Athena appointment and its matching practice visit.'} returnLabel={returnLabel} returnBlocked={lockedNow} onReturn={onReturn}>
  {native.suspended?<p role="status">Return to the app to check your saved Athena work.</p>:!context||!validRecoveryScope(namespace)?<p role="alert">Private saved-work storage is required before connecting an Athena visit.</p>:<>
   {error&&<p role="alert">{error}</p>}
   {openingError&&<p role="alert">{openingError}</p>}
   {!visible?<><p role="status">{error?'Your saved work is retained.':'Checking private account access…'}</p>{error&&<button disabled={lockedNow} onClick={()=>setRetry(value=>value+1)}>Recheck private Athena work</button>}</>:<>
    {mode==='saved'&&visible.record&&<section aria-label="Saved Athena visit result"><h2>Check your saved visit connection</h2>
     <p>{visible.record.resolution?'A previous visit connection result is saved. Check its current status before opening patient details.':'Your last visit connection needs to be checked. This will not repeat the change.'}</p>
     <button disabled={lockedNow} onClick={()=>void check()}>{busy?'Checking saved result…':'Check saved visit result'}</button>
     {result?.state==='not_found'&&<p role="status">No saved result was found. Find the appointment and review the patient and visit again before making a new change.</p>}
     {result?.state==='review_required'&&<p role="status">This patient or visit connection needs practice review. Ask your practice administrator to review the match.</p>}
     {result?.state==='removed'&&<p role="status">The visit connection was removed. Its history is retained.</p>}
     {result?.state==='linked'&&result.encounter&&<div><p role="status">Connected to {result.encounter.patient.display_name}</p>
      <p>{athenaVisitTime(result.encounter)}</p>{!result.encounter.appointment.timezone_known&&<p>Practice local time · Time zone not supplied by the practice</p>}
      {openBlocked&&<p>Save or recover unfinished work before opening another notebook. Your Chief draft is retained.</p>}
      <button disabled={lockedNow||openBlocked} onClick={()=>void openNotebook()}>Open linked notebook</button></div>}
     {visible.record.resolution&&<button disabled={lockedNow} onClick={()=>{setMode('schedule');setResult(null);setError('');}}>Find another Athena visit</button>}
    </section>}
    {mode==='schedule'&&<><fieldset disabled={locked||busy} style={{border:0,padding:0,margin:0,minWidth:0}}>
     <CoreConnectionPanel identity={identity} athenaOnly athenaEnabled appointmentSetupEnabled={false} athenaRecovery={visible.session} onAthenaRecoveryChange={update}
      onBusyChange={setChildBusy} onAuthenticationLost={cause=>{setResult(null);setOwned(null);callbacks.current.onAuthenticationLost(cause);}} onOpenNotebook={requestNotebook} openBlocked={openBlocked}/>
     </fieldset>{visible.record&&<button disabled={lockedNow} onClick={()=>{setMode('saved');setResult(null);setError('');}}>Check previous visit connection</button>}</>}
   </>}
  </>}
 </EhrReadTask>;
}
