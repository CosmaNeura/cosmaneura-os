import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,validRecoveryScope} from './workspace-api';
import {EFaxInboundPanel} from './EFaxInboundPanel';
import {EFAX_INBOUND_BUILD} from './efax-inbound-api';
import {validateEFaxRecovery,type EFaxInboundRecoveryAccess} from './efax-inbound-recovery';
import {DraftStoreError} from './draft-store';
import type {EFaxInboundPanelProps} from './EFaxInboundPanel';

const address=accountEditorAddress('efax-inbound');
export function EFaxInboundMount({identity,enabled=EFAX_INBOUND_BUILD,locked=false,onBusyChange,onAuthenticationLost,onReviewDocument}:{identity:AuthenticatedWorkspaceIdentity;enabled?:boolean;locked?:boolean;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(e:unknown)=>void;onReviewDocument?:EFaxInboundPanelProps['onReviewDocument']}){
 const context=useContext(AccountRecoveryContext),scope=context?.recoveryScope;
 const [proof,setProof]=useState<{identity:AuthenticatedWorkspaceIdentity;context:typeof context;generation:number;account:AccountIdentity}|null>(null),[error,setError]=useState('');
 const live=useRef({identity,context,scope,enabled,alive:true,generation:0}),denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
 if(live.current.identity!==identity||live.current.context!==context||live.current.scope!==scope||live.current.enabled!==enabled)live.current={identity,context,scope,enabled,alive:true,generation:live.current.generation+1};
 useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;live.current.generation++;};},[]);
 useEffect(()=>{const generation=++live.current.generation,c=new AbortController();setProof(null);setError('');
  const current=()=>live.current.alive&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.scope===scope;
  if(enabled&&context&&validRecoveryScope(scope))void(async()=>{await context.authorize();if(!current())return;const account=await accountIdentityApi.read(identity,c.signal);if(!current())return;if(account.recovery_scope!==scope)throw new WorkspaceApiError(403);setProof({identity,context,generation,account});})().catch(e=>{if(!current())return;setError('Private received-fax work could not be opened with this account.');if(e instanceof WorkspaceApiError&&[401,403,404,426].includes(e.status))denied.current(e);});
  return()=>{c.abort();live.current.generation++;};
 },[identity,context,scope,enabled]);
 const access=useMemo<EFaxInboundRecoveryAccess|null>(()=>{
  if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation||!enabled||proof.account.recovery_scope!==scope)return null;
  const expected={box_id:proof.account.box_id,owner_id:proof.account.actor_id},generation=proof.generation;
  const check=()=>{if(!live.current.alive||!live.current.enabled||live.current.generation!==generation||live.current.identity!==identity||live.current.context!==context||live.current.scope!==scope)throw new WorkspaceApiError(403);};
  const authorize=async()=>{check();await context.authorize();check();const account=await accountIdentityApi.read(identity);check();if(account.recovery_scope!==scope||account.box_id!==expected.box_id||account.actor_id!==expected.owner_id)throw new WorkspaceApiError(403);};
  return {authorize,denied:e=>denied.current(e),load:async()=>{await authorize();const saved=await context.journal.load(address);check();if(!saved)return null;if(saved.kind!=='account-editor'||saved.editor!=='efax-inbound'||saved.pending!==null)throw new DraftStoreError('integrity');return validateEFaxRecovery(saved.data,expected);},
   persist:async v=>{await authorize();const data=v===null?null:await validateEFaxRecovery(v,expected);check();await context.journal.persist(address,data?{kind:'account-editor',editor:'efax-inbound',data,pending:null}:null);check();}};
 },[identity,context,scope,proof,enabled]);
 if(!enabled)return <section aria-label="Received eFax"><h2>Received eFax</h2><p>Received-fax access is not enabled in this app build. Your administrator must configure it separately from sending faxes.</p></section>;
 if(!context||!validRecoveryScope(scope))return <p role="alert">Private saved-work storage is required for received eFax.</p>;
 if(!proof||!access)return <section aria-label="Received-fax account access"><p role={error?'alert':'status'}>{error||'Checking private received-fax account access…'}</p></section>;
 return <EFaxInboundPanel identity={identity} scope={{box_id:proof.account.box_id,owner_id:proof.account.actor_id}} recovery={access} locked={locked} onBusyChange={onBusyChange} onAuthenticationLost={onAuthenticationLost} onReviewDocument={onReviewDocument}/>;
}
