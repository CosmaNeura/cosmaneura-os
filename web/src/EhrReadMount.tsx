import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {EditorRecoveryContext} from './editor-recovery';
import {editorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {WorkspaceApiError,validRecoveryScope} from './workspace-api';
import {EHR_READ_BUILD,ehrProviderFields,ehrProviderName} from './ehr-read-api';
import {validateEhrReadRecovery,type EhrReadRecoveryAccess} from './ehr-read-recovery';
import {EhrReadPanel,type EhrReadPanelProps} from './EhrReadPanel';
export type EhrReadMountProps=Omit<EhrReadPanelProps,'scope'|'recovery'>&{enabled?:boolean};
const authority=(e:unknown)=>e instanceof WorkspaceApiError&&[401,403].includes(e.status);
export function EhrReadMount(props:EhrReadMountProps){
 const {identity,workspace,enabled=EHR_READ_BUILD,provider='elation'}=props,context=useContext(EditorRecoveryContext),recoveryScope=context?.recoveryScope;
 const callbacks=useRef(props);callbacks.current=props;
 const [retry,setRetry]=useState(0),[error,setError]=useState('');
 const live=useRef({identity,context,recoveryScope,workspaceId:workspace.id,provider,enabled,generation:0,alive:true});
 if(live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.workspaceId!==workspace.id||live.current.enabled!==enabled||live.current.provider!==provider)live.current={identity,context,recoveryScope,workspaceId:workspace.id,provider,enabled,generation:live.current.generation+1,alive:true};
 const [proof,setProof]=useState<{identity:typeof identity;context:typeof context;account:AccountIdentity;generation:number}|null>(null);
 useEffect(()=>{
  live.current.alive=true;const generation=++live.current.generation,c=new AbortController();setProof(null);setError('');
  const current=()=>live.current.alive&&live.current.generation===generation&&!c.signal.aborted;
  if(enabled&&context&&context.workspaceId===workspace.id&&validRecoveryScope(recoveryScope))void(async()=>{
   const w=await context.authorize();if(!current())return;if(w.id!==workspace.id)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity,c.signal);if(!current())return;if(account.recovery_scope!==recoveryScope)throw new WorkspaceApiError(403);
   setProof({identity,context,account,generation});
  })().catch(e=>{if(current()){setError(`Private ${ehrProviderName(provider)} review could not be opened with this account and visit.`);if(authority(e)){context?.denied(e);callbacks.current.onAuthenticationLost(e);}}});
  return()=>{c.abort();live.current.alive=false;live.current.generation++;};
 },[identity,context,recoveryScope,workspace.id,enabled,provider,retry]);
 const access=useMemo<EhrReadRecoveryAccess|null>(()=>{
  if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation||!enabled||context.workspaceId!==workspace.id)return null;
  const scope={box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:workspace.id,...ehrProviderFields(provider)},generation=proof.generation,address=editorAddress(workspace.id,provider==='tebra'?'ehr-read:tebra':'ehr-read');
  const check=()=>{if(!live.current.alive||!live.current.enabled||live.current.generation!==generation||live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.workspaceId!==scope.workspace_id)throw new WorkspaceApiError(403);};
  const authorize=async()=>{check();const w=await context.authorize();check();if(w.id!==scope.workspace_id)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity);check();if(account.box_id!==scope.box_id||account.actor_id!==scope.owner_id||account.recovery_scope!==proof.account.recovery_scope)throw new WorkspaceApiError(403);};
  return {authorize,denied:e=>{check();context.denied(e);callbacks.current.onAuthenticationLost(e);},load:async()=>{
   await authorize();const draft=await context.journal.load(address);check();if(!draft)return null;
   if(draft.kind!=='editor'||draft.workspaceId!==scope.workspace_id||draft.editor!==(provider==='tebra'?'ehr-read:tebra':'ehr-read')||draft.pending!==null)throw new DraftStoreError('integrity');
   const data=await validateEhrReadRecovery(draft.data,scope);check();return data;
  },persist:async value=>{await authorize();const data=value===null?null:await validateEhrReadRecovery(value,scope);check();await context.journal.persist(address,data?{kind:'editor',workspaceId:scope.workspace_id,editor:provider==='tebra'?'ehr-read:tebra':'ehr-read',data,pending:null}:null);check();}};
 },[identity,context,recoveryScope,proof,workspace.id,enabled,provider]);
 if(!enabled)return null;
 if(!context||context.workspaceId!==workspace.id||!validRecoveryScope(recoveryScope))return <p role="alert">Private saved-work storage for this visit is required before opening {ehrProviderName(provider)} appointments.</p>;
 if(!proof||!access||proof.generation!==live.current.generation)return <section aria-label={`${ehrProviderName(provider)} review access`}><p role={error?'alert':'status'}>{error||'Checking private account and visit access…'}</p>{error&&<button disabled={props.locked} onClick={()=>setRetry(n=>n+1)}>Recheck {ehrProviderName(provider)} review access</button>}</section>;
 return <EhrReadPanel {...props} scope={{box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:workspace.id,...ehrProviderFields(provider)}} recovery={access}/>;
}
