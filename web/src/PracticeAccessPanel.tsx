import {PracticeInvitationPanel} from './PracticeInvitationPanel';
import {PracticeMembersPanel} from './PracticeMembersPanel';
import {useCallback,useEffect,useRef,useState} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {accessCode,type AccessRequest,type AccessDecision} from './practice-access-contract';
import {accessDenied,accessFailure,usePracticeAccessTask,type PracticeAccessContext} from './PracticeAccessGate';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export function PracticeAccessPanel({identity,access,onBusyChange}:{identity:AuthenticatedWorkspaceIdentity;access:PracticeAccessContext;onBusyChange:(busy:boolean)=>void}) {
  const [rows,setRows]=useState<AccessRequest[]|null>(null),[selected,setSelected]=useState<AccessRequest|null>(null);
  const [matched,setMatched]=useState(false),[error,setError]=useState(''),[receipt,setReceipt]=useState('');
  const [unconfirmed,setUnconfirmed]=useState<AccessDecision|null>(null);
  const [inviteOpen,setInviteOpen]=useState(false),[inviteBusy,setInviteBusy]=useState(false);
  const reportInviteBusy=useCallback((value:boolean)=>setInviteBusy(value),[]);
  const [membersOpen,setMembersOpen]=useState(false),[membersBusy,setMembersBusy]=useState(false);
  const reportMembersBusy=useCallback((value:boolean)=>setMembersBusy(value),[]);
  const writing=useRef(false);
  const {busy,run}=usePracticeAccessTask(identity);
  const loss=useRef(access.onAccessLost);loss.current=access.onAccessLost;
  useEffect(()=>{onBusyChange(busy||unconfirmed!==null||membersBusy||inviteBusy);return ()=>onBusyChange(false);},[busy,unconfirmed,membersBusy,inviteBusy,onBusyChange]);
  function fail(cause:unknown){
    if(accessDenied(cause)){setRows(null);setSelected(null);setMatched(false);setUnconfirmed(null);loss.current();}
    setError(accessFailure(cause));
  }
  function refresh(){
    if(unconfirmed||membersBusy)return;
    setError('');setSelected(null);setMatched(false);
    return run(signal=>practiceAccessApi.pending(identity,signal),setRows,fail);
  }
  useEffect(()=>{
    setRows(null);setSelected(null);setMatched(false);setUnconfirmed(null);setError('');setReceipt('');
    if(access.role==='owner')void run(signal=>practiceAccessApi.pending(identity,signal),setRows,fail);
  },[identity,access.role,run]);
  async function decide(command:AccessDecision){
    if(busy||membersBusy||writing.current)return;
    writing.current=true;
    setError('');setReceipt('');setUnconfirmed(command);
    try {await run(signal=>practiceAccessApi.decide(identity,command,signal),row=>{
      setReceipt(`${row.display_name}: access ${row.state}.`);
      setRows(previous=>previous?.filter(item=>item.request_id!==row.request_id)??null);
      setSelected(null);setMatched(false);setUnconfirmed(null);
    },cause=>{
      if(cause instanceof WorkspaceApiError && [409,422,429].includes(cause.status)){
        setUnconfirmed(null);setSelected(null);setMatched(false);setRows(null);
        setError('This request could not be approved or declined. Refresh requests to review its current state.');
      }else fail(cause);
    });} finally {writing.current=false;}
  }
  if(access.role!=='owner')return <section className="practice-access-panel"><h2>Your practice access</h2><p>You are connected as a practice member. Your practice owner reviews requests from new teammates.</p></section>;
  return <section className="practice-access-panel" aria-label="Practice member requests">
    <button disabled={busy||unconfirmed!==null||membersBusy} onClick={()=>setMembersOpen(value=>!value)}>{membersOpen?'Hide connected members':'Manage connected members'}</button>
    {membersOpen&&<PracticeMembersPanel identity={identity} blocked={busy||unconfirmed!==null} onBusyChange={reportMembersBusy} onAccessLost={()=>loss.current()}/>}
    <button disabled={busy||unconfirmed!==null||membersBusy||inviteBusy} onClick={()=>setInviteOpen(value=>!value)}>{inviteOpen?'Close invitations':'Invite a teammate'}</button>
    {inviteOpen&&<PracticeInvitationPanel identity={identity} onBusyChange={reportInviteBusy} onAccessLost={()=>loss.current()}/>}
    <h2>Requests to join</h2>
    <p>Approve teammates you know to join this practice workspace. Only the practice owner can review these requests.</p>
    {error && <p role="alert">{error}</p>}{receipt && <p role="status">{receipt}</p>}
    {busy && <p role="status">Checking access requests…</p>}
    <button disabled={busy||unconfirmed!==null||membersBusy} onClick={()=>void refresh()}>Refresh requests</button>
    {rows?.length===0 && <p>No pending access requests.</p>}
    {rows && rows.length>0 && <ul>{rows.map(row=><li key={row.request_id}>
      <span>{row.display_name} <span className="practice-access-code">{accessCode(row)}</span></span>
      <button disabled={busy||unconfirmed!==null||membersBusy} onClick={()=>{setSelected(row);setMatched(false);setError('');setReceipt('');}}>Review {row.display_name}</button>
    </li>)}</ul>}
    {selected && <section className="practice-access-review" aria-label="Review access request">
      <h2>{selected.display_name}</h2><p>This name was supplied by the requester. Confirm their identity with them using this matching code:</p>
      <p className="practice-access-code">{accessCode(selected)}</p>
      <p>Requested {new Date(selected.created_at).toLocaleString()}. Expires {new Date(selected.expires_at).toLocaleString()}.</p>
      <p>Approval connects this signed-in account as a practice member. Clinical permissions and outside-service connections require their own setup.</p>
      <label><input type="checkbox" checked={matched} disabled={busy||unconfirmed!==null||membersBusy} onChange={event=>setMatched(event.target.checked)}/>I matched this name and code with the teammate I intend to approve.</label>
      {unconfirmed ? <><p>The last decision is unconfirmed. Retry that same decision to retrieve its result.</p>
        <button disabled={busy||membersBusy} onClick={()=>void decide(unconfirmed)}>Recover {unconfirmed.decision==='approve'?'approval':'decline'}</button></> : <div className="practice-access-actions">
        <button disabled={busy||membersBusy||!matched} onClick={()=>void decide({request_id:selected.request_id,review_sha256:selected.review_sha256,confirm:true,decision:'approve'})}>Approve member</button>
        <button disabled={busy||membersBusy} onClick={()=>void decide({request_id:selected.request_id,review_sha256:selected.review_sha256,confirm:true,decision:'decline'})}>Decline request</button>
        <button disabled={busy||membersBusy} onClick={()=>{setSelected(null);setMatched(false);}}>Back to requests</button>
      </div>}
    </section>}
  </section>;
}
