import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {editorAddress,type EditorKind} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {WorkspaceApiError,validRecoveryScope,type Workspace} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import {EFAX_INBOUND_SOURCE_BUILD,validEFaxSourceOffer,validEFaxSourceVisit} from './efax-inbound-source-api';
import {validateEFaxSourceRecovery,type EFaxSourceRecoveryAccess} from './efax-inbound-source-recovery';
import {EFaxSourceReviewPanel,type EFaxSourceReviewPanelProps} from './EFaxSourceReviewPanel';

export type EFaxSourceReviewMountProps=Omit<EFaxSourceReviewPanelProps,'scope'|'recovery'> & {enabled?:boolean};
const authority=(e:unknown)=>e instanceof WorkspaceApiError&&[401,403,404,426].includes(e.status);
export function EFaxSourceReviewMount({enabled=EFAX_INBOUND_SOURCE_BUILD,...props}:EFaxSourceReviewMountProps){
 const {identity,offered,visit}=props,context=useContext(EditorRecoveryContext);
 const recoveryScope=context?.recoveryScope;
 const documentKey=vendorCanonical(offered),visitKey=vendorCanonical({id:visit.id,label:visit.label});
 const [proof,setProof]=useState<{identity:typeof identity;context:EditorRecoveryAccess;account:AccountIdentity;generation:number}|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const [proofBusy,setProofBusy]=useState(enabled&&!!context),[panelBusy,setPanelBusy]=useState(false);
 const live=useRef({identity,context,recoveryScope,documentKey,visitKey,enabled,generation:0,alive:true}),callbacks=useRef(props);callbacks.current=props;
 if(live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.documentKey!==documentKey||live.current.visitKey!==visitKey||live.current.enabled!==enabled)
 live.current={identity,context,recoveryScope,documentKey,visitKey,enabled,generation:live.current.generation+1,alive:true};
 useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;live.current.generation++;};},[]);
 useEffect(()=>{props.onOperationBusyChange?.(enabled&&(proofBusy||panelBusy));},[enabled,proofBusy,panelBusy,props.onOperationBusyChange]);
 useEffect(()=>{const notify=props.onOperationBusyChange;return()=>notify?.(false);},[props.onOperationBusyChange]);
 useEffect(()=>{
  const generation=++live.current.generation,c=new AbortController();setProof(null);setError('');
  const current=()=>live.current.alive&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.recoveryScope===recoveryScope&&live.current.documentKey===documentKey&&live.current.visitKey===visitKey;
  const eligible=enabled&&!!context&&context.workspaceId===visit.id&&validRecoveryScope(recoveryScope)&&validEFaxSourceOffer(offered)&&validEFaxSourceVisit(visit);
  setProofBusy(eligible);setPanelBusy(false);
  if(eligible&&context)void(async()=>{
   const workspace=await context.authorize();if(!current())return;if(workspace.id!==visit.id)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity,c.signal);if(!current())return;if(account.recovery_scope!==recoveryScope)throw new WorkspaceApiError(403);
   setProof({identity,context,account,generation});
  })().catch(e=>{if(current()){setError('Private fax passage review could not be opened with this account and visit.');if(authority(e)){context?.denied(e);callbacks.current.onAuthenticationLost(e);}}})
   .finally(()=>{if(current())setProofBusy(false);});
  return()=>{c.abort();live.current.generation++;};
 },[identity,context,recoveryScope,documentKey,visitKey,enabled,retry]);
 const access=useMemo<EFaxSourceRecoveryAccess|null>(()=>{
  if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation||!enabled||context.workspaceId!==visit.id)return null;
  const scope={box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:visit.id},generation=proof.generation;
  const editor:EditorKind=`efax-source-review:${offered.operation_id}`,address=editorAddress(visit.id,editor);
  const check=()=>{if(!live.current.alive||!live.current.enabled||live.current.generation!==generation||live.current.identity!==identity||live.current.context!==context||live.current.recoveryScope!==recoveryScope||live.current.documentKey!==documentKey||live.current.visitKey!==visitKey)
   throw new WorkspaceApiError(403);};
  const authorize=async():Promise<Workspace>=>{
   check();const workspace=await context.authorize();check();
   if(workspace.id!==scope.workspace_id||recoveryScope!==proof.account.recovery_scope)throw new WorkspaceApiError(403);
   const account=await accountIdentityApi.read(identity);check();
   if(account.box_id!==scope.box_id||account.actor_id!==scope.owner_id||account.recovery_scope!==proof.account.recovery_scope)throw new WorkspaceApiError(403);
   return workspace;
  };
  return {authorize:async()=>{await authorize();},denied:e=>{check();context.denied(e);callbacks.current.onAuthenticationLost(e);},
   load:async()=>{
    await authorize();check();const draft=await context.journal.load(address);check();if(draft===null)return null;
    if(draft.kind!=='editor'||draft.workspaceId!==scope.workspace_id||draft.editor!==editor||draft.pending!==null)throw new DraftStoreError('integrity');
    const data=await validateEFaxSourceRecovery(draft.data,scope,offered);check();return data;
   },
   persist:async(value)=>{
    await authorize();check();const data=value===null?null:await validateEFaxSourceRecovery(value,scope,offered);check();
    await context.journal.persist(address,data?{kind:'editor',workspaceId:scope.workspace_id,editor,data,pending:null}:null);check();
   }};
 },[identity,context,recoveryScope,proof,enabled,documentKey,visitKey]);
 const reportPanelBusy=useMemo(()=>{
  const generation=proof?.generation;
  return (blocked:boolean)=>{if(generation!==undefined&&live.current.alive&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.enabled===enabled)setPanelBusy(blocked);};
 },[proof,identity,context,enabled]);
 if(!enabled)return null;
 if(!context||context.workspaceId!==visit.id||!validRecoveryScope(recoveryScope))return <p role="alert">Private saved-work storage for the current visit is required for fax passage review.</p>;
 if(!proof||!access||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation)return <section aria-label="Fax passage access">
  <p role={error?'alert':'status'}>{error||'Checking private fax passage account and visit access…'}</p>{error&&<button disabled={props.locked} onClick={()=>setRetry(n=>n+1)}>Recheck fax passage access</button>}</section>;
 return <EFaxSourceReviewPanel {...props} onOperationBusyChange={props.onOperationBusyChange?reportPanelBusy:undefined} scope={{box_id:proof.account.box_id,owner_id:proof.account.actor_id,workspace_id:visit.id}} recovery={access}/>;
}
