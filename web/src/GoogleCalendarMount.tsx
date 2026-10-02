import {useContext,useEffect,useMemo,useRef,useState} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace,validRecoveryScope} from './workspace-api';
import {GoogleCalendarPanel} from './GoogleCalendarPanel';
import {GOOGLE_CALENDAR_BUILD} from './google-calendar-api';
import {validateGoogleCalendarRecovery,type GoogleCalendarRecoveryAccess,type GoogleCalendarSaved,type GoogleCalendarVisit} from './google-calendar-recovery';
import {DraftStoreError} from './draft-store';

export type GoogleCalendarMountProps={identity:AuthenticatedWorkspaceIdentity;workspace:GoogleCalendarVisit|null;locked?:boolean;recoveryLocked?:boolean;
  currentSources?:Array<{entry_id:string;state:'current'|'unavailable'}>;
  onSaved:(workspace:Workspace)=>void;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(cause:unknown)=>void;
  onRequestCalendarAccess?:()=>void;calendarAccessBusy?:boolean;onChooseVisit?:()=>void;
  onAskChief?:(source:GoogleCalendarSaved)=>void;onRefreshVisit?:()=>Promise<void>;enabled?:boolean};
const address=accountEditorAddress('google-calendar');
export function GoogleCalendarMount({identity,enabled=GOOGLE_CALENDAR_BUILD,...props}:GoogleCalendarMountProps){
  const context=useContext(AccountRecoveryContext),scope=context?.recoveryScope;
  const [proof,setProof]=useState<{identity:AuthenticatedWorkspaceIdentity;context:typeof context;generation:number;account:AccountIdentity}|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  const live=useRef({identity,context,scope,enabled,alive:true,generation:0}),denied=useRef(props.onAuthenticationLost);denied.current=props.onAuthenticationLost;
  if(live.current.identity!==identity||live.current.context!==context||live.current.scope!==scope||live.current.enabled!==enabled)
    live.current={identity,context,scope,enabled,alive:true,generation:live.current.generation+1};
  useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;live.current.generation++;};},[]);
  useEffect(()=>{
    const generation=++live.current.generation,c=new AbortController();setProof(null);setError('');
    const current=()=>live.current.alive&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.scope===scope;
    if(enabled&&context&&validRecoveryScope(scope))void(async()=>{await context.authorize();if(!current())return;
      const account=await accountIdentityApi.read(identity,c.signal);if(!current())return;if(account.recovery_scope!==scope)throw new WorkspaceApiError(403);
      setProof({identity,context,generation,account});
    })().catch(cause=>{if(!current())return;setError('Private calendar work could not be opened with this account.');if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status))denied.current(cause);});
    return()=>{c.abort();live.current.generation++;};
  },[identity,context,scope,enabled,attempt]);
  const access=useMemo<GoogleCalendarRecoveryAccess|null>(()=>{
    if(!proof||!context||proof.identity!==identity||proof.context!==context||proof.generation!==live.current.generation||!enabled||proof.account.recovery_scope!==scope)return null;
    const expected={box_id:proof.account.box_id,actor_id:proof.account.actor_id},generation=proof.generation;
    const current=()=>live.current.alive&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context&&live.current.scope===scope;
    const check=()=>{if(!current())throw new WorkspaceApiError(403);};
    const authorize=async()=>{check();await context.authorize();check();const account=await accountIdentityApi.read(identity);check();
      if(account.recovery_scope!==scope||account.box_id!==expected.box_id||account.actor_id!==expected.actor_id)throw new WorkspaceApiError(403);};
    return {authorize,denied:cause=>denied.current(cause),
      load:async()=>{await authorize();const saved=await context.journal.load(address);check();if(!saved)return null;
        if(saved.kind!=='account-editor'||saved.editor!=='google-calendar'||saved.pending!==null)throw new DraftStoreError('integrity');
        return validateGoogleCalendarRecovery(saved.data,expected);},
      persist:async value=>{await authorize();const data=value===null?null:await validateGoogleCalendarRecovery(value,expected);check();
        await context.journal.persist(address,data?{kind:'account-editor',editor:'google-calendar',data,pending:null}:null);check();},
    };
  },[identity,context,scope,proof,enabled]);
  if(!enabled)return null;
  if(!context||!validRecoveryScope(scope))return <p role="alert">Private saved-work storage is required for calendar work.</p>;
  if(!proof||!access)return <section aria-label="Calendar work access"><p role={error?'alert':'status'}>{error||'Checking private calendar work access…'}</p>{error&&<button disabled={props.locked} onClick={()=>setAttempt(n=>n+1)}>Recheck calendar work access</button>}</section>;
  return <GoogleCalendarPanel {...props} identity={identity} scope={{box_id:proof.account.box_id,actor_id:proof.account.actor_id}} recovery={access}/>;
}
