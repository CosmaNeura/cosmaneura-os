import {useEffect,useRef,useState} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {memberCode,type MemberChange,type MemberChangeResult,type MembersPage,type PracticeMember} from './practice-members-contract';
import {accessDenied,accessFailure,usePracticeAccessTask} from './PracticeAccessGate';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export function PracticeMembersPanel({identity,blocked=false,onBusyChange,onAccessLost}:{identity:AuthenticatedWorkspaceIdentity;blocked?:boolean;onBusyChange:(busy:boolean)=>void;onAccessLost:()=>void}){
  const [page,setPage]=useState<MembersPage|null>(null),[cursor,setCursor]=useState<string|null>(null);
  const [selected,setSelected]=useState<PracticeMember|null>(null),[confirmed,setConfirmed]=useState(false);
  const [pending,setPending]=useState<MemberChange|null>(null),[receipt,setReceipt]=useState<MemberChangeResult|null>(null);
  const [error,setError]=useState('');const writing=useRef(false);
  const loss=useRef(onAccessLost);loss.current=onAccessLost;
  const {busy,run}=usePracticeAccessTask(identity);
  useEffect(()=>{onBusyChange(busy||pending!==null);return ()=>onBusyChange(false);},[busy,pending,onBusyChange]);
  function fail(cause:unknown){
    if(accessDenied(cause)){setPage(null);setSelected(null);setPending(null);setReceipt(null);setConfirmed(false);loss.current();}
    setError(accessFailure(cause));
  }
  async function refresh(after=cursor){
    if(writing.current||blocked)return;
    setError('');setPage(null);setSelected(null);setConfirmed(false);setCursor(after);
    await run(signal=>practiceAccessApi.members(identity,after,signal),setPage,cause=>{if(accessDenied(cause))fail(cause);else setError('Member access could not be refreshed. Try again to check current access.');});
  }
  useEffect(()=>{
    setPage(null);setSelected(null);setConfirmed(false);setCursor(null);setPending(null);setReceipt(null);setError('');
    void run(signal=>practiceAccessApi.members(identity,null,signal),setPage,fail);
  },[identity,run]);
  async function change(command:MemberChange){
    if(busy||blocked||writing.current)return;
    writing.current=true;setPending(command);setError('');setReceipt(null);let succeeded=false;
    try{await run(signal=>practiceAccessApi.memberChange(identity,command,signal),result=>{
      succeeded=true;setReceipt(result);setPending(null);setSelected(null);setConfirmed(false);setPage(null);
    },cause=>{
      if(cause instanceof WorkspaceApiError&&[409,422,429].includes(cause.status)){
        setPending(null);setSelected(null);setConfirmed(false);setPage(null);setError('The account changed or this review expired. Refresh members before trying again.');
      }else fail(cause);
    });}finally{writing.current=false;}
    // A receipt describes the recorded change. Fetch current state separately,
    // since a recovered receipt may predate another owner's access change.
    if(succeeded)await refresh();
  }
  function submit(){
    if(!selected?.action||!confirmed||pending||blocked||busy)return;
    void change({idempotency_key:crypto.randomUUID(),member_id:selected.member_id,action:selected.action,
      reviewed_at:selected.reviewed_at,review_sha256:selected.review_sha256,confirm:true});
  }
  const locked=blocked||busy||pending!==null;
  return <section className="practice-access-panel" aria-label="Connected practice members">
    <h2>Connected members</h2>
    <p>Review who can use this practice workspace. Changes here affect CosmasOS; manage direct access to outside services with those services.</p>
    {error&&<p role="alert">{error}</p>}
    {receipt&&<p role="status"><span className="practice-access-code">{memberCode(receipt.receipt)}</span> · {receipt.replayed?'Previously recorded change recovered':'Access change recorded'}: {receipt.receipt.action==='deactivate'?'access paused':'access restored'} at {new Date(receipt.receipt.recorded_at).toLocaleString()}. {page?'The member list below shows the latest checked access.':'Refresh members to check current access.'}</p>}
    {busy&&<p role="status">Checking member access…</p>}
    <div className="practice-access-actions"><button disabled={locked} onClick={()=>void refresh()}>Refresh members</button>
      {cursor!==null&&<button disabled={locked} onClick={()=>void refresh(null)}>First member page</button>}
      {page?.next_after_id&&<button disabled={locked} onClick={()=>void refresh(page.next_after_id)}>Next members</button>}</div>
    {page?.members.length===0&&<p>No members on this page.</p>}
    {page&&<ul>{page.members.map(row=><li key={row.member_id}>
      <span><bdi>{row.display_name}</bdi> · {row.role==='owner'?'Practice owner':row.state==='active'?'Access active':row.state==='inactive'?'Access paused':'Access unavailable'}<br/>
        <small>Account code: <span className="practice-access-code">{memberCode(row)}</span></small></span>
      {row.action&&<button disabled={locked} onClick={()=>{setSelected(row);setConfirmed(false);setError('');setReceipt(null);}}>Review {row.action==='deactivate'?'pause':'restore'} for {row.display_name}</button>}
    </li>)}</ul>}
    {selected&&<section className="practice-access-review" aria-label="Review member access">
      <h3>{selected.action==='deactivate'?'Pause':'Restore'} access for <bdi>{selected.display_name}</bdi></h3>
      <p>Account code: <span className="practice-access-code">{memberCode(selected)}</span></p>
      <p>{selected.action==='deactivate'?'Pausing removes this account’s access to the workspace. Saved private work is retained.':'Restoring lets this existing account use the workspace again, including its retained private work.'}</p>
      <p>Review expires {new Date(selected.expires_at).toLocaleString()}.</p>
      <label><input type="checkbox" checked={confirmed} disabled={locked} onChange={event=>setConfirmed(event.target.checked)}/>I reviewed this account and intend to {selected.action==='deactivate'?'pause':'restore'} its workspace access.</label>
      {pending?<><p>This access change is unconfirmed. Recover its recorded result before starting another change.</p>
        <button disabled={blocked||busy} onClick={()=>void change(pending)}>Recover access change</button></>:<div className="practice-access-actions">
        <button disabled={locked||!confirmed} onClick={submit}>{selected.action==='deactivate'?'Pause CosmasOS access':'Restore CosmasOS access'}</button>
        <button disabled={locked} onClick={()=>{setSelected(null);setConfirmed(false);}}>Cancel access review</button>
      </div>}
    </section>}
  </section>;
}
