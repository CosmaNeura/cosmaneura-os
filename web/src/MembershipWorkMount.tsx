import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {EditorRecoveryContext,editorDraft,type EditorRecoveryAccess} from './editor-recovery';
import {editorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {membershipApi} from './membership-api';
import {MembershipWorkPanel} from './MembershipWorkPanel';
import {sameMembershipScope} from './membership-contract';
import {validateMembershipRecovery,type MembershipRecoveryAccess} from './membership-recovery';
import {membershipEvidenceAdapter} from './membership-evidence-adapter';
import {vendorCanonical} from './vendor-contract';
import type {Scope} from './membership-schema';

export const MEMBERSHIP_WORK_BUILD=import.meta.env.VITE_MEMBERSHIP_WORK_ENABLED==='true';

/** Derive owner IDs from an authorized server view, never from journal contents. */
export function MembershipWorkspaceMount({identity,workspaceId,locked,enabled=MEMBERSHIP_WORK_BUILD}:{identity:WorkspaceIdentity;workspaceId:string;locked?:boolean;enabled?:boolean}){
 const context=useContext(EditorRecoveryContext),[loaded,setLoaded]=useState<{identity:WorkspaceIdentity;context:EditorRecoveryAccess;scope:Scope}|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{
  let active=true;const controller=new AbortController();setLoaded(null);setError('');
  if(enabled&&context&&context.workspaceId===workspaceId)void (async()=>{
   try{const workspace=await context.authorize();if(!active)return;if(workspace.id!==workspaceId)throw new WorkspaceApiError(403);const options=await membershipApi.bootstrap(identity,workspaceId,controller.signal);if(active)setLoaded({identity,context,scope:options.scope});}
   catch(e){if(active){setError('Private membership review could not be opened. Recheck access and try again.');if(e instanceof WorkspaceApiError&&[401,403,404].includes(e.status))context.denied(e);}}
  })();
  return()=>{active=false;controller.abort();};
 },[identity,context,workspaceId,enabled,retry]);
 if(!enabled)return null;
 if(!loaded||loaded.identity!==identity||loaded.context!==context||loaded.scope.workspace_id!==workspaceId)return <section aria-label="Private membership review"><h3>Membership review</h3><p role={error?'alert':'status'}>{error||'Checking private encounter access and recovery…'}</p>{error&&<button disabled={!context} onClick={()=>setRetry(v=>v+1)}>Retry opening membership review</button>}</section>;
 return <MembershipScopedMount identity={identity} context={loaded.context} scope={loaded.scope} locked={locked}/>;
}

function MembershipScopedMount({identity,context,scope,locked}:{identity:WorkspaceIdentity;context:EditorRecoveryAccess;scope:Scope;locked?:boolean}){
 const scopeKey=vendorCanonical(scope),live=useRef({identity,context,scopeKey,active:true});live.current={identity,context,scopeKey,active:true};
 useEffect(()=>()=>{live.current.active=false;},[]);
 const adapters=useMemo(()=>{
  const current=()=>live.current.active&&live.current.identity===identity&&live.current.context===context&&live.current.scopeKey===scopeKey;
  const check=()=>{if(!current())throw new WorkspaceApiError(403);};
  const address=editorAddress(scope.workspace_id,'membership-work');
  const recovery:MembershipRecoveryAccess={
   async load(){check();const draft=await context.journal.load(address);check();if(!draft)return null;if(draft.kind!=='editor'||draft.editor!=='membership-work'||draft.workspaceId!==scope.workspace_id||draft.pending!==null)throw new DraftStoreError('integrity');return validateMembershipRecovery(draft.data,scope);},
   async persist(value){check();if(value){if(!sameMembershipScope(value.scope,scope))throw new DraftStoreError('integrity');await validateMembershipRecovery(value,scope);}check();await context.journal.persist(address,value?editorDraft(scope.workspace_id,'membership-work',value):null);check();},
   async authorize(){check();const workspace=await context.authorize();check();if(workspace.id!==scope.workspace_id)throw new WorkspaceApiError(403);},
   denied:error=>{if(current())context.denied(error);},
  };
  return {recovery,evidence:membershipEvidenceAdapter(identity,scope,context,current)};
 },[identity,context,scopeKey]);
 return <MembershipWorkPanel identity={identity} scope={scope} recovery={adapters.recovery} evidence={adapters.evidence} enabled locked={locked}/>;
}
