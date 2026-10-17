import {useContext,useEffect,useRef,useState} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {practiceAccessApi} from './practice-access-api';
import {accessName} from './practice-access-contract';
import {invitationUrl,encodeInvitationRecovery,validateInvitationRecovery,type InvitationRecovery,type InvitationOperation,type PracticeInvitation} from './practice-invitation-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

const empty=():InvitationRecovery=>({contract:'practice-invitation-recovery.v1',confirmed:null,pending:null});
const address=accountEditorAddress('practice-invite');
export function PracticeInvitationPanel({identity,onBusyChange,onAccessLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange:(busy:boolean)=>void;onAccessLost:()=>void}){
  const recovery=useContext(AccountRecoveryContext);
  const [state,setState]=useState<InvitationRecovery>(empty),[rows,setRows]=useState<PracticeInvitation[]>([]),[label,setLabel]=useState(''),[hours,setHours]=useState<24|72|168>(72);
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[retry,setRetry]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const epoch=useRef(0),flight=useRef(false),latest=useRef({identity,recovery});latest.current={identity,recovery};
  const current=(version:number)=>epoch.current===version&&latest.current.identity===identity&&latest.current.recovery===recovery;
  function fail(cause:unknown){if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){setRows([]);setState(empty());setReady(false);onAccessLost();}else setError('The invitation result could not be confirmed. Your saved request is retained.');}
  useEffect(()=>{const version=++epoch.current;setReady(false);setState(empty());setRows([]);setError('');
    if(recovery)void(async()=>{await recovery.authorize();const saved=await recovery.journal.load(address);if(!current(version))return;
      if(saved){if(saved.kind!=='account-editor'||saved.editor!=='practice-invite')throw new Error();setState(validateInvitationRecovery(saved.data));}
      const list=await practiceAccessApi.invitations(identity);if(!current(version))return;setRows(list);setReady(true);
    })().catch(cause=>{if(current(version))fail(cause);});
    return()=>{epoch.current++;};
  },[identity,recovery]);
  useEffect(()=>{onBusyChange(busy);return()=>onBusyChange(false);},[busy,onBusyChange]);
  async function persist(next:InvitationRecovery,version:number){if(!recovery)throw new Error();await recovery.journal.persist(address,{kind:'account-editor',editor:'practice-invite',data:encodeInvitationRecovery(next),pending:next.pending?.body.idempotency_key??null});if(!current(version))throw new Error();setState(next);}
  async function confirmed(row:PracticeInvitation,operation:InvitationOperation,version:number){if(!recovery)return;await recovery.authorize();if(!current(version))return;
    const next:InvitationRecovery={...state,pending:null,confirmed:operation.type==='create'?{invitation:row,token:operation.body.token}:state.confirmed?.invitation.invitation_id===row.invitation_id?{...state.confirmed,invitation:row}:state.confirmed};
    await persist(next,version);if(!current(version))return;setRows(values=>[row,...values.filter(value=>value.invitation_id!==row.invitation_id)]);setRetry(false);setMessage(operation.type==='create'?'Invitation ready to copy.':'Invitation revoked.');
  }
  async function perform(operation:InvitationOperation){if(!recovery||!ready||busy||flight.current||state.pending&&!retry)return;const version=epoch.current;flight.current=true;setBusy(true);setError('');setMessage('');setRetry(false);
    try{await recovery.authorize();if(!current(version))return;await persist({...state,pending:operation},version);if(!current(version))return;
      const row=operation.type==='create'?await practiceAccessApi.createInvitation(identity,operation.body):await practiceAccessApi.revokeInvitation(identity,operation.body);if(current(version))await confirmed(row,operation,version);
    }catch(cause){if(current(version))fail(cause);}finally{flight.current=false;if(current(version))setBusy(false);}
  }
  async function check(){if(!recovery||!ready||!state.pending||busy||flight.current)return;const version=epoch.current,operation=state.pending;flight.current=true;setBusy(true);setError('');setMessage('');
    try{await recovery.authorize();if(!current(version))return;const result=await practiceAccessApi.resolveInvitation(identity,operation);if(!current(version))return;
      if(result.outcome==='recorded'&&result.invitation)await confirmed(result.invitation,operation,version);else{setRetry(true);setMessage('No saved result was found. You can retry this same request.');}
    }catch(cause){if(current(version))fail(cause);}finally{flight.current=false;if(current(version))setBusy(false);}
  }
  function create(){if(!accessName(label.trim()))return;const bytes=crypto.getRandomValues(new Uint8Array(32));const token=Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');void perform({type:'create',body:{idempotency_key:crypto.randomUUID(),label:label.trim(),token,expires_in_hours:hours}});}
  const link=state.confirmed?.invitation.state==='active'&&Date.parse(state.confirmed.invitation.expires_at)>Date.now()?invitationUrl(state.confirmed.token):null;
  return <section className="practice-invitations" aria-label="Teammate invitations">
    <h2>Invite a teammate</h2><p>Copy a link for a teammate with an account in this practice organization. They request access; you review their name and matching code before approval.</p>
    {!ready&&<p role="status">{recovery?'Checking saved invitations…':'Device recovery must be ready to create an invitation.'}</p>}
    {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    {state.pending?<div className="team-recovery"><p>An invitation request is retained on this device.</p><button disabled={!ready||busy} onClick={()=>void check()}>Check invitation result</button>{retry&&<button disabled={busy} onClick={()=>void perform(state.pending!)}>Retry same invitation request</button>}</div>:<form onSubmit={event=>{event.preventDefault();create();}}>
      <label>Invitation label<input maxLength={120} value={label} disabled={!ready||busy} placeholder="For Morgan" onChange={event=>setLabel(event.target.value)}/></label>
      <label>Expires in<select value={hours} disabled={!ready||busy} onChange={event=>setHours(Number(event.target.value) as 24|72|168)}><option value={24}>24 hours</option><option value={72}>3 days</option><option value={168}>7 days</option></select></label>
      <button disabled={!ready||busy||!accessName(label.trim())}>Create invitation link</button>
    </form>}
    {link&&<div><label>Invitation link<input readOnly value={link} onFocus={event=>event.target.select()}/></label><button onClick={()=>void navigator.clipboard.writeText(link).then(()=>setMessage('Invitation link copied.')).catch(()=>setError('Copy is unavailable. Select the link and copy it.'))}>Copy invitation link</button><p>Expires {new Date(state.confirmed!.invitation.expires_at).toLocaleString()}. This device retains the latest link in encrypted recovery.</p></div>}
    {rows.length>0&&<ul>{rows.map(row=><li key={row.invitation_id}><strong>{row.label}</strong> · {row.state} · {row.requests} {row.requests===1?'request':'requests'}<span> · Expires {new Date(row.expires_at).toLocaleString()}</span>{row.state==='active'&&<button disabled={!ready||busy||!!state.pending} onClick={()=>void perform({type:'revoke',body:{idempotency_key:crypto.randomUUID(),invitation_id:row.invitation_id}})}>Revoke {row.label}</button>}</li>)}</ul>}
  </section>;
}
