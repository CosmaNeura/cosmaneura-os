import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {EditorRecoveryContext} from './editor-recovery';
import {editorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {WorkspaceApiError,validRecoveryScope} from './workspace-api';
import {CALENDAR_IMPORT_BUILD} from './calendar-import-api';
import {validateCalendarRecovery,type CalendarRecoveryAccess} from './calendar-import-recovery';
import {CalendarImportPanel,type CalendarImportPanelProps} from './CalendarImportPanel';
export type CalendarImportMountProps=Omit<CalendarImportPanelProps,'owner'|'recovery'>&{enabled?:boolean};
const authority=(e:unknown)=>e instanceof WorkspaceApiError&&[401,403].includes(e.status);
export function CalendarImportMount(props:CalendarImportMountProps){
 const {identity,workspace,enabled=CALENDAR_IMPORT_BUILD}=props,context=useContext(EditorRecoveryContext),recoveryScope=context?.recoveryScope;
 const callbacks=useRef(props);callbacks.current=props;
 const [retry,setRetry]=useState(0),[error,setError]=useState('');
 const live=useRef({identity,context,recoveryScope,workspaceId:workspace.id,enabled,generation:0,alive:true});
 if(live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.workspaceId!==workspace.id||live.current.enabled!==enabled)live.current={identity,context,recoveryScope,workspaceId:workspace.id,enabled,generation:live.current.generation+1,alive:true};
 const [proof,setProof]=useState<{identity:typeof identity;context:typeof context;account:AccountIdentity;generation:number}|null>(null);
 useEffect(()=>{
  live.current.alive=true;const generation=++live.current.generation,c=new AbortController();setProof(null);setError('');
  const current=()=>live.current.alive&&live.current.generation===generation&&!c.signal.aborted;
  if(enabled&&identity.mode==='clerk_jwt'&&context&&context.workspaceId===workspace.id&&validRecoveryScope(recoveryScope))void(async()=>{
   const w=await context.authorize();if(!current())return;if(w.id!==workspace.id)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity,c.signal);if(!current())return;if(account.recovery_scope!==recoveryScope)throw new WorkspaceApiError(403);
   setProof({identity,context,account,generation});
  })().catch(e=>{if(current()){setError('Calendar import could not be opened with this account and visit.');if(authority(e)){context?.denied(e);callbacks.current.onAuthenticationLost(e);}}});
  return()=>{c.abort();live.current.alive=false;live.current.generation++;};
 },[identity,context,recoveryScope,workspace.id,enabled,retry]);
 const access=useMemo<CalendarRecoveryAccess|null>(()=>{
  if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation||!enabled||context.workspaceId!==workspace.id)return null;
  const scope={box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:workspace.id},generation=proof.generation,address=editorAddress(workspace.id,'calendar-import');
  const check=()=>{if(!live.current.alive||!live.current.enabled||live.current.generation!==generation||live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.workspaceId!==scope.workspace_id)throw new WorkspaceApiError(403);};
  const authorize=async()=>{check();const w=await context.authorize();check();if(w.id!==scope.workspace_id)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity);check();if(account.box_id!==scope.box_id||account.actor_id!==scope.owner_id||account.recovery_scope!==proof.account.recovery_scope)throw new WorkspaceApiError(403);};
  // Authorize refreshes the shared visit; a saved receipt must never republish its older workspace.
  return {authorize,denied:e=>{check();context.denied(e);callbacks.current.onAuthenticationLost(e);},load:async()=>{
   await authorize();const draft=await context.journal.load(address);check();if(!draft)return null;
   if(draft.kind!=='editor'||draft.workspaceId!==scope.workspace_id||draft.editor!==('calendar-import')||draft.pending!==null)throw new DraftStoreError('integrity');
   const data=await validateCalendarRecovery(draft.data,scope);check();return data;
  },persist:async value=>{await authorize();const data=value===null?null:await validateCalendarRecovery(value,scope);check();await context.journal.persist(address,data?{kind:'editor',workspaceId:scope.workspace_id,editor:'calendar-import',data,pending:null}:null);check();}};
 },[identity,context,recoveryScope,proof,workspace.id,enabled]);
 if(!enabled)return null;
 if(identity.mode!=='clerk_jwt')return <p role="status">Calendar file import is unavailable with this sign-in.</p>;
 if(!context||context.workspaceId!==workspace.id||!validRecoveryScope(recoveryScope))return <p role="alert">Private saved-work storage for this visit is required before importing a calendar file.</p>;
 if(!proof||!access||proof.generation!==live.current.generation)return <section aria-label="Calendar import access"><p role={error?'alert':'status'}>{error||'Checking private account and visit access…'}</p>{error&&<button disabled={props.locked} onClick={()=>setRetry(n=>n+1)}>Recheck calendar import access</button>}</section>;
 return <CalendarImportPanel {...props} owner={{box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:workspace.id}} recovery={access}/>;
}
