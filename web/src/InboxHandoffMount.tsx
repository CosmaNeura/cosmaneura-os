import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {WorkspaceApiError,workspaceApi,validRecoveryScope,type WorkspaceIdentity} from './workspace-api';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {InboxHandoffPanel} from './InboxHandoffPanel';
import {validateInboxHandoffRecovery,type InboxHandoffRecoveryAccess} from './inbox-handoff-recovery';
import {validateInboxHandoffPeople} from './inbox-handoff-preparation';
import {vendorCanonical} from './vendor-contract';

export const INBOX_HANDOFF_BUILD=import.meta.env.VITE_INBOX_HANDOFF_ENABLED==='true';
export type InboxHandoffMountProps={identity:WorkspaceIdentity;onDenied:(error:unknown)=>void;enabled?:boolean;sourceItemId?:string;sourceRequest?:number;selectedTicketId?:string;ticketRequest?:number;onDone?:()=>void;onBusyChange?:(blocked:boolean)=>void};
const ADDRESS=accountEditorAddress('inbox-handoffs');

/** Staff and owners obtain their actor only from the current signed account identity endpoint.
 * The opaque recovery scope must also match the already-authorized encrypted account journal. */
export function InboxHandoffMount({identity,onDenied,enabled=INBOX_HANDOFF_BUILD,sourceItemId,sourceRequest,selectedTicketId,ticketRequest,onDone,onBusyChange}:InboxHandoffMountProps){
  const context=useContext(AccountRecoveryContext),scope=context?.recoveryScope;
  const denied=useRef(onDenied);denied.current=onDenied;
  const live=useRef({identity,context,scope,enabled,active:true,generation:0}),readSequence=useRef(0);
  if(live.current.identity!==identity||live.current.context!==context||live.current.scope!==scope||live.current.enabled!==enabled)live.current={identity,context,scope,enabled,active:true,generation:live.current.generation+1};
  const [proof,setProof]=useState<{identity:WorkspaceIdentity;context:typeof context;scope:string;generation:number;sequence:number;account:AccountIdentity}|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  useEffect(()=>{live.current.active=true;return()=>{live.current.active=false;readSequence.current++;};},[]);
  useEffect(()=>{
    const sequence=++readSequence.current,generation=live.current.generation,controller=new AbortController();let cancelled=false;
    setProof(null);setError('');
    const current=()=>!cancelled&&live.current.active&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.scope===scope&&live.current.enabled&&sequence===readSequence.current;
    if(enabled&&context&&validRecoveryScope(scope)&&'mode'in identity)void(async()=>{
      await context.authorize();if(!current())return;
      const account=await accountIdentityApi.read(identity,controller.signal);if(!current())return;
      if(account.recovery_scope!==scope)throw new WorkspaceApiError(403,'workspace_recovery_unavailable');
      setProof({identity,context,scope,generation,sequence,account});
    })().catch(cause=>{if(!current())return;setError('Assigned incoming work could not be opened with this signed account and private recovery scope.');if(cause instanceof WorkspaceApiError&&[401,403,404].includes(cause.status))denied.current(cause);});
    return()=>{cancelled=true;controller.abort();};
  },[identity,context,scope,enabled,attempt]);
  const bindings=useMemo(()=>{
    if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.scope!==scope||proof.generation!==live.current.generation||proof.sequence!==readSequence.current||!enabled)return null;
    const {account,generation,sequence}=proof,actor={box_id:account.box_id,actor_id:account.actor_id};
    const current=()=>live.current.active&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.scope===account.recovery_scope&&context.recoveryScope===account.recovery_scope&&readSequence.current===sequence;
    const check=()=>{if(!current())throw new WorkspaceApiError(403);};
    const authorize=async()=>{
      check();await context.authorize();check();
      const fresh=await accountIdentityApi.read(identity);check();
      if(vendorCanonical(fresh)!==vendorCanonical(account)||fresh.recovery_scope!==context.recoveryScope)throw new WorkspaceApiError(403,'workspace_recovery_unavailable');
    };
    const reject=(cause:unknown)=>{if(!current())return;readSequence.current++;setProof(null);setError('Access to assigned incoming work is unavailable. Sign in and reopen.');denied.current(cause);};
    const recovery:InboxHandoffRecoveryAccess={
      async authorize(){await authorize();},
      async load(){
        check();const envelope=await context.journal.load(ADDRESS);check();if(!envelope)return null;
        if(envelope.kind!=='account-editor'||envelope.editor!=='inbox-handoffs'||envelope.pending!==null)throw new DraftStoreError('integrity');
        const record=await validateInboxHandoffRecovery(envelope.data,actor);check();return record;
      },
      async persist(value){
        check();if(value===null)throw new DraftStoreError('invalid');
        const record=await validateInboxHandoffRecovery(value,actor);check();
        await context.journal.persist(ADDRESS,{kind:'account-editor',editor:'inbox-handoffs',pending:null,data:record});check();
      },
      denied:reject,
    };
    const loadPeople=async()=>{
      await authorize();const page=await workspaceApi.practiceWork(identity);check();
      await authorize();check();return validateInboxHandoffPeople(page.people);
    };
    return {actor,recovery,loadPeople};
  },[proof,context,scope,identity,enabled]);
  if(!enabled)return null;
  if(!context||!validRecoveryScope(scope))return <section aria-label="Assigned incoming work"><h2>Incoming follow-up</h2><p role="status">A current signed account recovery scope is required before assigned work can be opened.</p></section>;
  if(!('mode'in identity))return <section aria-label="Assigned incoming work"><h2>Incoming follow-up</h2><p role="alert">Sign in to open assigned incoming work. A local demo identity cannot select a private account.</p></section>;
  if(!bindings)return <section aria-label="Assigned incoming work"><h2>Incoming follow-up</h2><p role={error?'alert':'status'}>{error||'Checking signed account access and private recovery…'}</p>{error&&<button onClick={()=>setAttempt(n=>n+1)}>Recheck assigned work access</button>}</section>;
  return <InboxHandoffPanel identity={identity} actor={bindings.actor} recovery={bindings.recovery} enabled sourceItemId={sourceItemId} sourceRequest={sourceRequest} selectedTicketId={selectedTicketId} ticketRequest={ticketRequest} loadPeople={bindings.loadPeople} onDone={onDone} onBusyChange={onBusyChange}/>;
}
