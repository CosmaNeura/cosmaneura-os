import {useEffect,useRef,useState} from 'react';
import {membershipApi} from './membership-api';
import {financeApi} from './finance-api';
import {MEMBERSHIP_REVIEW_QUESTION,MembershipSelectionTooLargeError,membershipReviewSelection,type MembershipReviewSelection} from './membership-analysis-contract';
import {WorkspaceApiError,type ConversationInput,type WorkspaceIdentity} from './workspace-api';
import type {Scope} from './membership-schema';

const words=(s:string)=>s.replaceAll('_',' ');
const label:Record<string,string>={state:'Work status',amount:'Requested amount',amount_received:'Amount received',creation:'Processor request',payment_state:'Payment status',human_evidence:'Human review notes',external_service_verified:'Membership service verified',source_current:'Reviewed source current',submit_claimed:'Request submission started',expected_outcome:'Requested outcome',ledger_observation:'Human ledger observation',membership_authority:'Membership authority',finance_evidence:'Recorded payment evidence'};
function Facts({data}:{data:Record<string,unknown>}) {
  return <dl>{Object.entries(data).filter(([key])=>!['amount_unit','currency'].includes(key)).map(([key,value])=><div key={key}>
    <dt>{label[key]??words(key)}</dt><dd>{value&&typeof value==='object'?<Facts data={value as Record<string,unknown>}/>:
      value===null?'Not recorded':typeof value==='boolean'?value?'Yes':'No':['amount','amount_received'].includes(key)&&typeof value==='number'?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value/100):<span style={{whiteSpace:'pre-wrap'}}>{['expected_outcome','instructions','human_evidence'].includes(key)?String(value):words(String(value))}</span>}</dd>
  </div>)}</dl>;
}
export function MembershipAnalysisPanel({identity,workspaceId,workspaceRevision,teamRevision,botAddress,enabled,modelEnabled,locked,onSubmit,onDenied,onOpenWork,membershipEnabled=import.meta.env.VITE_MEMBERSHIP_WORK_ENABLED==='true',paymentEnabled=import.meta.env.VITE_FINANCE_WORK_ENABLED==='true'}:{
  identity:WorkspaceIdentity;workspaceId:string;workspaceRevision:number;teamRevision:number;botAddress:string;enabled:boolean;modelEnabled:boolean;locked:boolean;
  onSubmit:(request:ConversationInput)=>Promise<void>;onDenied:(e:unknown)=>void;onOpenWork:()=>void;membershipEnabled?:boolean;paymentEnabled?:boolean;
}) {
  const [kind,setKind]=useState<'membership'|'payment'>(membershipEnabled?'membership':'payment');
  const [items,setItems]=useState<{id:string;label:string}[]>([]),[scope,setScope]=useState<Scope|null>(null),[ticket,setTicket]=useState('');
  const [selection,setSelection]=useState<MembershipReviewSelection|null>(null),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [cursor,setCursor]=useState<string|undefined>(),[next,setNext]=useState<string|null>(null),[refresh,setRefresh]=useState(0);
  const epoch=useRef(0),inFlight=useRef(false);
  const denied=useRef(onDenied);denied.current=onDenied;
  useEffect(()=>{
    const gen=++epoch.current,controller=new AbortController();setItems([]);setTicket('');setSelection(null);setConsent(false);setError('');setScope(null);setNext(null);inFlight.current=false;
    if(!enabled||!(kind==='membership'?membershipEnabled:paymentEnabled)){setBusy(false);return;}
    setBusy(true);
    void (async()=>{
      try {
        if(kind==='membership') {
          const options=await membershipApi.bootstrap(identity,workspaceId,controller.signal);
          const catalog=await membershipApi.catalog(identity,options.scope,controller.signal);
          if(gen!==epoch.current)return;
          setScope(options.scope);setItems(catalog.items.map(s=>({id:s.ticket_id,label:`${words(s.purpose)} · due ${s.due_date} · ${words(s.state)}`})));
        } else {
          const catalog=await financeApi.catalog(identity,workspaceId,cursor,controller.signal);
          if(gen!==epoch.current)return;
          setItems(catalog.items.map(s=>({id:s.ticket_id,label:`${new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(s.amount/100)} · ${words(s.state)} · payment ${words(s.payment_state)}`})));setNext(catalog.next_cursor);
        }
      } catch(e) {if(gen===epoch.current){setError('Current work could not be opened. Refresh to recheck your access.');if(e instanceof WorkspaceApiError&&[401,403,404].includes(e.status))denied.current(e);}}
      finally{if(gen===epoch.current)setBusy(false);}
    })();
    return()=>{epoch.current++;controller.abort();};
  },[identity,workspaceId,workspaceRevision,teamRevision,botAddress,enabled,kind,cursor,refresh,membershipEnabled,paymentEnabled]);
  useEffect(()=>{setConsent(false);},[locked,modelEnabled]);
  const read=async()=>{
    if(locked||busy||inFlight.current||!enabled||!ticket||kind==='membership'&&!scope)return;
    const gen=epoch.current;inFlight.current=true;setBusy(true);setSelection(null);setConsent(false);setError('');
    try{
      const detail=kind==='membership'?(await membershipApi.detail(identity,scope!,ticket)).detail:await financeApi.detail(identity,workspaceId,ticket);
      const chosen=await membershipReviewSelection(kind,detail,workspaceId,workspaceRevision);
      if(gen===epoch.current)setSelection(chosen);
    }catch(e){if(gen===epoch.current){setError(e instanceof MembershipSelectionTooLargeError?'This record contains too much text for one AI review. Open Work to prepare a shorter reviewed record.':'The selected evidence could not be opened. Refresh the work list and review it again.');if(e instanceof WorkspaceApiError&&[401,403,404].includes(e.status))denied.current(e);}}
    finally{if(gen===epoch.current){inFlight.current=false;setBusy(false);}}
  };
  const submit=async()=>{
    if(locked||busy||inFlight.current||!enabled||!modelEnabled||!consent||!selection||selection.expected_revision!==workspaceRevision)return;
    const gen=epoch.current;inFlight.current=true;setBusy(true);setConsent(false);setError('');
    try{await onSubmit({expected_revision:workspaceRevision,team_revision:teamRevision,idempotency_key:crypto.randomUUID(),role:botAddress,content:MEMBERSHIP_REVIEW_QUESTION,membership_analysis:{...selection.analysis,consented:true}});}
    catch{if(gen===epoch.current)setError('The review request could not be confirmed. Check its saved result before starting another request.');}
    finally{if(gen===epoch.current){inFlight.current=false;setBusy(false);}}
  };
  if(!membershipEnabled&&!paymentEnabled)return <p>Membership and payment work are not connected.</p>;
  return <section className="team-rehearsal" aria-label="Membership and payment coworker review" aria-busy={busy}>
    <h3>Review membership or payment work</h3><p>Choose one saved record to explain its status, evidence and next steps.</p>
    {error&&<p role="alert">{error}</p>}
    <label>Work type<select value={kind} disabled={locked||busy||!enabled} onChange={e=>{setConsent(false);setSelection(null);setCursor(undefined);setKind(e.target.value as typeof kind);}}>
      {membershipEnabled&&<option value="membership">Membership</option>}{paymentEnabled&&<option value="payment">Payment requests</option>}
    </select></label>
    <label>Saved work<select value={ticket} disabled={locked||busy||!enabled} onChange={e=>{setTicket(e.target.value);setSelection(null);setConsent(false);}}><option value="">Choose a record</option>{items.map(i=><option key={i.id} value={i.id}>{i.label}</option>)}</select></label>
    {!busy&&!items.length&&!error&&<p>No saved {kind==='membership'?'membership work':'payment requests'} on this page. Create a reviewed proposal in Work.</p>}
    <button disabled={locked||busy||!enabled||!ticket} onClick={()=>void read()}>Review selected evidence</button>
    <button disabled={locked||busy} onClick={()=>{setCursor(undefined);setRefresh(v=>v+1);}}>Refresh work</button>
    {next&&<button disabled={locked||busy} onClick={()=>setCursor(next)}>Next payment requests</button>}
    <button disabled={locked||busy} onClick={onOpenWork}>Open membership and payment work</button>
    {selection&&<div><h4>{selection.label}</h4><Facts data={selection.data}/>
      <p>AI receives only these displayed work facts and the review request. Human ledger observations do not establish live membership; payment and membership status are separate. Review the answer before using it.</p>
      {!modelEnabled&&<p role="status">AI review is not connected or is disabled for this coworker.</p>}
      <label><input type="checkbox" checked={consent} disabled={locked||busy||!enabled||!modelEnabled} onChange={e=>setConsent(e.target.checked)}/>Use this selected evidence for one AI review</label>
      <button disabled={locked||busy||!enabled||!modelEnabled||!consent} onClick={()=>void submit()}>Ask Membership/Billing</button>
    </div>}
  </section>;
}
