import {inboxDraftSelection,type InboxDraftSelection} from './inbox-analysis-contract';
import {useEffect,useRef,useState} from 'react';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import {inboxApi} from './inbox-api';
import {isInboxCalendarDate,prepareInboxOperation,type InboxBundle,type InboxKind,type InboxRequests} from './inbox-contract';
import type {Catalog,Detail,ReviewOptions,Source,Summary} from './inbox-schema';
import {continueInboxReview,emptyInboxDraft,inboxDraftKey,parkInboxCommand,resumeInboxCommand,withInboxCommand,withInboxDraft,type InboxDraft,type InboxRecoveryAccess} from './inbox-recovery';
import {useInboxRecovery} from './inbox-recovery-ui';
import {InboxDueDateInput} from './InboxDueDateInput';
import './inbox.css';

const stateLabels:Record<Summary['state'],string>={needs_review:'Patient and thread review needed',reviewed:'Patient and thread reviewed',triaged:'Human review planned',result_recorded:'Human result awaiting review',closed_local_review:'Local review completed',needs_human:'Human attention needed'};
const classifications={administrative_review:'Administrative review',clinical_human_review:'Clinical human review',urgent_human_review:'Urgent human review',source_exception:'Source or identity exception'};
const commandLabels={review:'Patient and thread review',triage:'Human triage',result:'Human result',verify:'Local review completion'};
const rejectionLabels:Record<string,string>={inbox_version_changed:'The saved review state changed.',inbox_source_changed:'The incoming source changed.',inbox_binding_unavailable:'The reviewed connection or patient mapping is unavailable.',inbox_workspace_changed:'The matching encounter changed.',inbox_review_required:'Patient and thread review is required first.',inbox_triage_required:'A current human triage is required.',inbox_result_changed:'The human result changed.',inbox_exception_unresolved:'Human attention is still required.',inbox_feature_disabled:'New Inbox work is disabled.',inbox_history_limit:'This item reached its history limit.'};
const basis=(d:Detail)=>vendorCanonical(d);
type InboxPage='list'|'source'|'review'|'triage'|'result'|'completion'|'history'|'historical';
const binding=(d:Detail)=>({item_id:d.summary.item_id,expected_version:d.summary.version,idempotency_key:`inbox-${crypto.randomUUID()}`,...(d.summary.source_id?{source_id:d.summary.source_id,source_sha256:d.summary.source_sha256!}:{})});
const sameOptions=(o:ReviewOptions,d:Detail)=>o.item_id===d.summary.item_id&&o.item_version===d.summary.version&&o.source_id===d.summary.source_id&&o.source_sha256===d.summary.source_sha256&&o.patient_link_id===d.summary.patient_link_id;
const draftFor=(d:Detail)=>emptyInboxDraft(d.summary.item_id,d.summary.source_id,d.summary.source_sha256);
const emptyChecks=()=>({patient:false,thread:false,untrusted:false,triage:false,result:false,verifyPatient:false,verifySource:false,verifyResult:false,verifyLocal:false});

export type InboxPanelProps={identity:WorkspaceIdentity;recovery:InboxRecoveryAccess|null;enabled?:boolean;onDone?:()=>void;onBusyChange?:(busy:boolean)=>void;presentation?:'expanded'|'focused';onOpenHandoff?:(itemId:string)=>void;onDraftInbox?:(selection:InboxDraftSelection)=>void};
export function InboxPanel({identity,recovery,enabled=false,onDone,onBusyChange,presentation='expanded',onOpenHandoff,onDraftInbox}:InboxPanelProps){
  const [loaded,setLoaded]=useState<{identity:WorkspaceIdentity;recovery:InboxRecoveryAccess|null;catalog:Catalog}|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),epoch=useRef(0);
  useEffect(()=>{const gen=++epoch.current,controller=new AbortController();setLoaded(null);setError('');
    if(enabled)void inboxApi.catalog(identity,controller.signal).then(catalog=>{if(gen===epoch.current)setLoaded({identity,recovery,catalog});}).catch(e=>{if(gen===epoch.current){setError('Private Inbox could not be loaded. Recheck owner access and try again.');if(e instanceof WorkspaceApiError&&[401,403,404].includes(e.status))recovery?.denied?.(e);}});
    return()=>{epoch.current++;controller.abort();};
  },[identity,recovery,enabled,attempt]);
  if(!enabled)return <p>Inbox is not enabled in this environment.</p>;
  const hide=()=>{epoch.current++;setLoaded(null);setError('Access to private Inbox is unavailable. Sign in and reopen Inbox.');};
  if(!loaded||loaded.identity!==identity||loaded.recovery!==recovery)return <section className="inbox-panel"><h2>Private Inbox</h2><p role={error?'alert':'status'}>{error||'Loading private Inbox…'}</p>{error&&<button onClick={()=>setAttempt(n=>n+1)}>Retry loading Inbox</button>}</section>;
  return <InboxEditor key={vendorCanonical(loaded.catalog.scope)} identity={identity} recovery={recovery} initial={loaded.catalog} onDenied={hide} onDone={onDone} onBusyChange={onBusyChange} presentation={presentation} onOpenHandoff={onOpenHandoff} onDraftInbox={onDraftInbox}/>;
}
function InboxEditor({identity,recovery,initial,onDenied,onDone,onBusyChange,presentation='expanded',onOpenHandoff,onDraftInbox}:InboxPanelProps&{initial:Catalog;onDenied:()=>void}){
  const state=useInboxRecovery(recovery,initial.scope),[catalog,setCatalog]=useState(initial),[bundle,setBundle]=useState<InboxBundle|null>(null),[options,setOptions]=useState<ReviewOptions|null>(null),[historical,setHistorical]=useState<Source|null>(null),[checks,setChecks]=useState(emptyChecks),[page,setPage]=useState<InboxPage>('list'),[handoffSelection,setHandoffSelection]=useState<{itemId:string;detailKey:string;generation:number}|null>(null),epoch=useRef(0);
  const [draftSelection,setDraftSelection]=useState<{selection:InboxDraftSelection;detailKey:string;generation:number}|null>(null);
  const focused=presentation==='focused',detailKey=bundle?basis(bundle.detail):'';
  const busyCallback=useRef(onBusyChange);busyCallback.current=onBusyChange;
  const navigationBlocked=state.busy||state.saving||state.saveFailed||state.unsavedInput;
  useEffect(()=>{busyCallback.current?.(navigationBlocked);},[navigationBlocked,onBusyChange]);
  useEffect(()=>()=>{epoch.current++;busyCallback.current?.(false);},[]);
  useEffect(()=>{if(!navigationBlocked)return;const prevent=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);},[navigationBlocked]);
  useEffect(()=>{setChecks(emptyChecks());},[page]);
  useEffect(()=>{setChecks(emptyChecks());setOptions(null);setHistorical(null);},[detailKey,state.offer]);
  useEffect(()=>{if(state.denied)onDenied();},[state.denied]);
  useEffect(()=>{setChecks(emptyChecks());},[state.saveFailed]);
  useEffect(()=>{
    if(!handoffSelection)return;
    if(handoffSelection.generation!==epoch.current||handoffSelection.detailKey!==detailKey||state.record.pending||state.record.parked.some(p=>p.operation.request.item_id===handoffSelection.itemId)||state.saveFailed){setHandoffSelection(null);return;}
    if(navigationBlocked||state.blocked)return;
    setHandoffSelection(null);
    try{onOpenHandoff?.(handoffSelection.itemId);}catch{state.setStatus('Incoming follow-up could not be opened. Your saved Inbox work remains available.');}
  },[handoffSelection,navigationBlocked,state.blocked,state.record.pending,state.record.parked,state.saveFailed,detailKey,onOpenHandoff]);
  useEffect(()=>{
    if(!draftSelection)return;
    if(draftSelection.generation!==epoch.current||draftSelection.detailKey!==detailKey||state.record.pending||state.record.parked.some(p=>p.operation.request.item_id===draftSelection.selection.analysis.item_id)||state.saveFailed){setDraftSelection(null);return;}
    if(navigationBlocked||state.blocked)return;
    setDraftSelection(null);onDraftInbox?.(draftSelection.selection);
  },[draftSelection,navigationBlocked,state.blocked,state.record.pending,state.record.parked,state.saveFailed,detailKey,onDraftInbox]);
  const io=async<T,>(promise:Promise<T>,itemScoped=false)=>{const gen=epoch.current;try{const value=await promise;if(gen!==epoch.current)throw Error('Owner changed');return value;}catch(e){
    if(gen===epoch.current&&itemScoped&&e instanceof WorkspaceApiError&&e.status===404){
      setBundle(null);setOptions(null);setHistorical(null);setChecks(emptyChecks());setPage('list');
      let current:Catalog|null=null;
      try{const reread=await inboxApi.catalog(identity);if(gen===epoch.current&&vendorCanonical(reread.scope)===vendorCanonical(initial.scope))current=reread;}catch{/* Account authority must be proved before keeping this view open. */}
      if(current){setCatalog(current);setBundle(null);setOptions(null);setHistorical(null);setChecks(emptyChecks());state.setStatus('This item is unavailable. Its saved command is still unresolved; keep it parked to review a different item.');throw Error('Item unavailable; exact command retained');}
    }
    if(gen===epoch.current&&state.rejectAccess(e)){epoch.current++;setBundle(null);setOptions(null);setHistorical(null);onDenied();}throw e;
  }};
  const detail=bundle?.detail,summary=detail?.summary;
  const draft=detail?(state.record.drafts.find(x=>inboxDraftKey(x)===inboxDraftKey(draftFor(detail)))??draftFor(detail)):null;
  const parkedHere=summary?state.record.parked.find(p=>p.operation.request.item_id===summary.item_id):null;
  const inputBlocked=state.blocked||state.record.pending!==null||!!parkedHere;
  const blocked=inputBlocked||state.saving;
  const edit=(patch:Partial<InboxDraft>)=>{if(inputBlocked||!draft)return;setChecks(emptyChecks());const latest=state.current.current.drafts.find(x=>inboxDraftKey(x)===inboxDraftKey(draft))??draft;try{void state.save(withInboxDraft(state.current.current,{...latest,...patch})).catch(()=>{});}catch{state.setStatus('This edit exceeds the saved-work limits or contains unsupported text. The previous input and exact receipts are unchanged.');}};
  const refresh=async(itemId?:string)=>{setCatalog(await io(inboxApi.catalog(identity)));if(itemId){const value=await io(inboxApi.detail(identity,initial.scope,itemId),true);setBundle(value);if(focused&&detail&&basis(value.detail)!==basis(detail))setPage('source');return value;}return null;};
  const select=(itemId:string)=>void state.run(async()=>{if(state.current.current.pending)return;const value=await io(inboxApi.detail(identity,initial.scope,itemId),true);setBundle(value);setOptions(null);setHistorical(null);setChecks(emptyChecks());const existing=state.current.current.drafts.find(x=>inboxDraftKey(x)===inboxDraftKey(draftFor(value.detail)));await state.save(withInboxDraft({...state.current.current,selected_item_id:itemId},existing??draftFor(value.detail)));if(focused)setPage('source');});
  const fresh=async()=>{if(!detail)return null;const value=await io(inboxApi.detail(identity,initial.scope,detail.summary.item_id),true);if(basis(value.detail)!==basis(detail)){setBundle(value);setChecks(emptyChecks());setOptions(null);setHistorical(null);if(focused)setPage('source');state.setStatus('The incoming source or review state changed. Review the current item before saving a new action. Your earlier draft is retained.');return null;}setBundle(value);return value.detail;};
  const readOptions=async(d:Detail)=>{const choices=await io(inboxApi.reviewOptions(identity,initial.scope,d.summary.item_id),true);if(!sameOptions(choices,d)){setOptions(null);setChecks(emptyChecks());if(focused)setPage('source');state.setStatus('The source changed while matching encounters were loaded. Refresh this item.');return;}setOptions(choices);setChecks(emptyChecks());};
  const loadOptions=()=>void state.run(async()=>{if(state.current.current.pending||parkedHere)return;const d=await fresh();if(d&&d.availability.review)await readOptions(d);});
  const openPage=(next:'review'|'triage'|'result'|'completion'|'history')=>void state.run(async()=>{if(state.current.current.pending||parkedHere&&next!=='history')return;const d=await fresh();if(!d)return;
    const kind=next==='completion'?'verify':next;if(kind!=='history'&&!d.availability[kind])return;setChecks(emptyChecks());setPage(next);if(next==='review')await readOptions(d);
  });
  const openHandoff=()=>void state.run(async()=>{
    if(!onOpenHandoff||!detail||state.current.current.pending||state.current.current.parked.some(p=>p.operation.request.item_id===detail.summary.item_id)||state.saveFailed)return;
    setChecks(emptyChecks());const d=await fresh();if(d)setHandoffSelection({itemId:d.summary.item_id,detailKey:basis(d),generation:epoch.current});
  });
  const openDraft=()=>void state.run(async()=>{
    if(!onDraftInbox||!detail||state.current.current.pending||parkedHere||state.saveFailed)return;
    const d=await fresh();if(!d)return;
    const current=await io(inboxApi.detail(identity,initial.scope,d.summary.item_id),true);
    if(basis(current.detail)!==basis(d)){setBundle(current);state.setStatus('The message changed. Review the current source first.');return;}
    const selection=inboxDraftSelection(current);
    if(selection)setDraftSelection({selection,detailKey:basis(d),generation:epoch.current});
    else state.setStatus('A draft needs a complete current message, matching encounter review and administrative human triage.');
  });
  const back=()=>{if(navigationBlocked||state.blocked)return;setChecks(emptyChecks());setPage(page==='source'?'list':page==='historical'?'history':'source');};
  const execute=async<K extends InboxKind>(kind:K,request:InboxRequests[K])=>{
    const operation=await prepareInboxOperation(initial.scope,kind,request);
    await state.save(withInboxCommand(state.current.current,operation));
    const receipt=await io(inboxApi.execute(identity,operation),true);
    await state.save({...state.current.current,receipt});
    await refresh(operation.request.item_id);
    state.setStatus(receipt.outcome==='recorded'?'The exact local review action is recorded.':receipt.outcome==='rejected'?'The exact action was rejected and cannot act later. Keep its proof before starting a new action.':'No receipt was found. Keep this exact saved action for recovery.');
  };
  const command=(kind:InboxKind)=>void state.run(async()=>{
    if(state.current.current.pending||parkedHere||!draft||kind==='triage'&&!isInboxCalendarDate(draft.due_date))return;const d=await fresh();if(!d||!d.availability[kind])return;
    if(kind==='review'){
      if(!options||!checks.patient||!checks.thread||!checks.untrusted)return;
      const current=await io(inboxApi.reviewOptions(identity,initial.scope,d.summary.item_id),true);
      if(!sameOptions(current,d)||current.options_sha256!==options.options_sha256){setOptions(current);setChecks(emptyChecks());state.setStatus('The matching encounters changed. Review the current choice and confirm again.');return;}
      const selected=current.choices.find(x=>x.workspace_id===draft.workspace_id);if(!selected)return;
      await execute('review',{...binding(d),workspace_id:selected.workspace_id,expected_workspace_revision:selected.expected_workspace_revision,patient_link_id:current.patient_link_id,reviewed_patient:true,reviewed_exact_thread:true,reviewed_untrusted_source:true});
    }else if(kind==='triage'){
      if(!checks.triage||!isInboxCalendarDate(draft.due_date)||!draft.instructions.trim())return;
      if(draft.classification==='administrative_review'&&(!d.summary.workspace_current||d.summary.incomplete_content||d.summary.source_conflict||d.summary.read_issue))return;
      await execute('triage',{...binding(d),classification:draft.classification,due_date:draft.due_date,instructions:draft.instructions,human_disposition_required:true});
    }else if(kind==='result'){
      const t=d.latest_triage;if(!checks.result||!draft.result_evidence.trim()||!t?.receipt_id||!t.receipt_sha256)return;
      if(draft.result_disposition==='local_review_complete'&&(d.summary.classification!=='administrative_review'||!d.summary.workspace_current||d.summary.incomplete_content||d.summary.source_conflict||d.summary.read_issue))return;
      await execute('result',{...binding(d),triage_receipt_id:t.receipt_id,triage_receipt_sha256:t.receipt_sha256,disposition:draft.result_disposition,evidence:draft.result_evidence,no_external_action_claimed:true});
    }else{
      const r=d.latest_result;if(!checks.verifyPatient||!checks.verifySource||!checks.verifyResult||!checks.verifyLocal||!r?.receipt_id||!r.receipt_sha256)return;
      await execute('verify',{...binding(d),result_receipt_id:r.receipt_id,result_receipt_sha256:r.receipt_sha256,reviewed_patient:true,reviewed_exact_source:true,reviewed_human_result:true,confirm_local_review_only:true});
    }
  });
  const recover=(retry=false)=>void state.run(async()=>{const operation=state.current.current.pending;if(!operation||retry&&state.current.current.receipt?.outcome!=='not_found'||state.current.current.receipt?.outcome==='recorded'||state.current.current.receipt?.outcome==='rejected')return;const receipt=await io(retry?inboxApi.execute(identity,operation):inboxApi.recover(identity,operation),true);await state.save({...state.current.current,receipt});await refresh(operation.request.item_id);});
  const keepReceipt=()=>void state.run(async()=>{const previous=state.current.current.pending,proof=state.current.current.receipt;if(!previous)return;await state.save(continueInboxReview(state.current.current));setChecks(emptyChecks());if(focused)setPage('source');const updated=await refresh(previous.request.item_id);if(focused&&updated&&proof?.outcome==='recorded'){const next=previous.kind==='review'?'triage':previous.kind==='triage'?'result':previous.kind==='result'?'completion':'source';setPage(next!=='source'&&updated.detail.availability[next==='completion'?'verify':next]?next:'source');}});
  const park=()=>void state.run(async()=>{await state.save(parkInboxCommand(state.current.current));setBundle(null);setOptions(null);setHistorical(null);setChecks(emptyChecks());setPage('list');state.setStatus('The unresolved command is kept exactly. It has not been cancelled. A new command for that item remains blocked until its exact receipt is resolved.');});
  const resume=(itemId:string)=>void state.run(async()=>{await state.save(resumeInboxCommand(state.current.current,itemId));setBundle(null);setOptions(null);setHistorical(null);setChecks(emptyChecks());setPage('list');state.setStatus('The original command is selected for exact recovery. Nothing was retried.');});
  const selectedOptions=options?.choices.find(x=>x.workspace_id===draft?.workspace_id);
  const check=(name:keyof ReturnType<typeof emptyChecks>,label:string)=><label className="inbox-check"><input type="checkbox" checked={checks[name]} disabled={blocked} onChange={e=>setChecks(v=>({...v,[name]:e.target.checked}))}/>{label}</label>;
  const pending=state.record.pending,receipt=state.record.receipt;
  const canAdministrative=!!summary?.workspace_current&&!summary.incomplete_content&&!summary.source_conflict&&!summary.read_issue;
  const show=(value:InboxPage)=>!focused||page===value;
  const savedTriage=bundle?.history.commands.find(c=>!!detail?.latest_triage&&c.receipt.receipt_id===detail.latest_triage.receipt_id&&c.receipt.command_kind==='triage');
  const savedResult=bundle?.history.commands.find(c=>!!detail?.latest_result&&c.receipt.receipt_id===detail.latest_result.receipt_id&&c.receipt.command_kind==='result');
  const title=!focused||page==='list'?'Private Inbox':({source:'Incoming message',review:'Patient and thread review',triage:'Human triage',result:'Record human result',completion:'Review local completion',history:'Source and review history',historical:'Historical source'} as const)[page];
  const sourceCard=detail?.source&&<article aria-label="Untrusted incoming message"><h4>Incoming message · untrusted external text</h4><p>Observed {new Date(detail.source.observed_at).toLocaleString()} · source version {detail.source.sequence}</p><pre>{detail.source.text}</pre>{detail.source.attachment_types.length>0&&<p>Unretrieved content: {detail.source.attachment_types.join(', ')}</p>}</article>;
  const triageEvidence=savedTriage&&'classification'in savedTriage.request&&<article aria-label="Saved human triage"><h4>Recorded human triage</h4><p>{classifications[savedTriage.request.classification]} · due {savedTriage.request.due_date}</p><pre>{savedTriage.request.instructions}</pre><p>{savedTriage.receipt.recorded_at&&new Date(savedTriage.receipt.recorded_at).toLocaleString()}</p></article>;
  const resultEvidence=savedResult&&'disposition'in savedResult.request&&<article aria-label="Saved human result"><h4>Recorded human result</h4><p>{savedResult.request.disposition==='local_review_complete'?'Local administrative review performed':'Further human attention needed'}</p><pre>{savedResult.request.evidence}</pre><p>{savedResult.receipt.recorded_at&&new Date(savedResult.receipt.recorded_at).toLocaleString()}</p></article>;
  const historyContent=detail&&bundle&&<>
    <p>Exact recorded and rejected requests are preserved. Earlier observations do not replace the current source.</p>
    {bundle.history.sources.map(s=><button key={s.source_id} disabled={state.blocked||state.saving} onClick={()=>void state.run(async()=>{setHistorical(await io(inboxApi.source(identity,initial.scope,detail.summary.item_id,s,detail.summary.patient_link_id),true));if(focused)setPage('historical');})}>Read source version {s.sequence}</button>)}
    {!focused&&historical&&<article aria-label="Historical untrusted message"><h4>Earlier source observation · version {historical.sequence}</h4><pre>{historical.text}</pre></article>}
    <ol>{bundle.history.commands.map(({request,receipt:r})=><li key={r.receipt_id}>{commandLabels[r.command_kind]} · {r.outcome} · {r.recorded_at&&new Date(r.recorded_at).toLocaleString()}{r.rejection&&<p>{rejectionLabels[r.rejection]}</p>}{'instructions'in request&&<p>{request.instructions}</p>}{'evidence'in request&&<p>{request.evidence}</p>}</li>)}</ol>
  </>;
  const earlierDrafts=detail&&draft&&state.record.drafts.some(d=>d.item_id===detail.summary.item_id&&inboxDraftKey(d)!==inboxDraftKey(draft))&&<details aria-label="Earlier saved human drafts"><summary>Earlier saved review drafts</summary>{state.record.drafts.filter(d=>d.item_id===detail.summary.item_id&&inboxDraftKey(d)!==inboxDraftKey(draft)).map(d=><article key={inboxDraftKey(d)}><h4>Earlier human draft · source version {bundle!.history.sources.find(s=>s.source_id===d.source_id)?.sequence??'unavailable'}</h4><p>{classifications[d.classification]} · {d.due_date||'No due date'}</p><pre>{d.instructions}</pre><pre>{d.result_evidence}</pre><button disabled={blocked} onClick={()=>{edit({instructions:d.instructions,result_evidence:d.result_evidence,due_date:d.due_date,classification:d.classification,result_disposition:'needs_human',workspace_id:''});if(focused)setPage('triage');}}>Copy earlier text for editing</button></article>)}</details>;
  return <section className={'inbox-panel'+(focused?' inbox-focused':'')} aria-label="Private Inbox" data-presentation={presentation} data-page={focused&&pending?'recovery':page}>
    <header><div><h2>{focused&&pending?'Saved Inbox action':title}</h2><p>Review incoming messages and record accountable human work.</p></div>{onDone&&<button onClick={()=>{if(!navigationBlocked)onDone();}} disabled={navigationBlocked}>Done</button>}</header>
    <p className="inbox-limit">Source observations require human review. This workspace does not send replies, notify a clinician or change vendor messages.</p>
    {state.error&&<p role="alert">{state.error}</p>}{state.status&&<p role="status">{state.status}</p>}
    {!recovery&&<p role="alert">Private saved-work storage is required before Inbox actions can be used.</p>}
    {state.loadFailed&&<button onClick={state.retryLoad}>Retry loading private Inbox recovery</button>}
    {state.saveFailed&&<button onClick={()=>void state.retrySave()} disabled={state.busy||state.saving}>Retry saving retained Inbox work</button>}
    {state.offer&&<aside><p>Saved private Inbox drafts and exact command receipts are available.</p><button onClick={()=>void state.restore()} disabled={state.busy}>Restore saved Inbox work</button></aside>}
    {pending&&<aside className="inbox-recovery" aria-label="Saved exact Inbox action"><h3>Saved {commandLabels[pending.kind]}</h3>
      {receipt?.outcome==='recorded'||receipt?.outcome==='rejected'?<><p>{receipt.outcome==='recorded'?'Recorded local action.':`Permanently rejected: ${rejectionLabels[receipt.rejection??'']??'Review the current item.'}`}</p><button onClick={keepReceipt} disabled={state.blocked||state.saving}>Keep proof and continue review</button></>:<><p>{receipt?.outcome==='not_found'?'No receipt found. The exact saved action remains pending.':'Its outcome is not confirmed. Recover the exact saved receipt.'}</p><button onClick={()=>recover()} disabled={state.blocked||state.saving}>Recover exact Inbox receipt</button>{receipt?.outcome==='not_found'&&<button onClick={()=>recover(true)} disabled={state.blocked||state.saving}>Retry exact saved Inbox action</button>}<button onClick={park} disabled={state.blocked||state.saving}>Keep unresolved action and review another item</button></>}
      {focused&&<details><summary>Exact saved request and receipt</summary><pre>{vendorCanonical({operation:pending,receipt})}</pre></details>}
    </aside>}
    {(!focused||!pending)&&<>
      {state.record.parked.length>0&&<aside aria-label="Parked exact Inbox commands"><h3>Unresolved saved actions</h3><p>These exact commands are retained. Parking does not cancel them or prove they did not execute.</p>{state.record.parked.map(p=><div key={p.operation.request.item_id}><p>{commandLabels[p.operation.kind]} · {catalog.items.find(i=>i.item_id===p.operation.request.item_id)?.label??'Unavailable incoming item'}</p><button onClick={()=>resume(p.operation.request.item_id)} disabled={state.blocked||state.saving||!!pending}>Resume exact saved action</button></div>)}</aside>}
      <button onClick={()=>void state.run(()=>refresh(focused&&page==='list'?undefined:detail?.summary.item_id).then(()=>{}))} disabled={state.blocked||state.saving}>Refresh private Inbox</button>
      {!catalog.enabled&&<p>New Inbox work is disabled. Owned history and exact command recovery remain available.</p>}
      {focused&&page!=='list'&&<nav className="inbox-focus-nav" aria-label="Inbox step navigation"><button onClick={back} disabled={navigationBlocked||state.blocked}>Back</button></nav>}
      <div className="inbox-layout">
        {show('list')&&<nav aria-label="Incoming private messages">{catalog.items.length===0?<p>No reviewed incoming sources are available.</p>:catalog.items.map(item=><button key={item.item_id} disabled={state.blocked||state.saving||!!pending} aria-pressed={summary?.item_id===item.item_id} onClick={()=>select(item.item_id)}><strong>{item.label}</strong><span>{stateLabels[item.state]}</span></button>)}</nav>}
        {(!focused||page!=='list')&&<main aria-label={focused?`Inbox ${page} page`:undefined}>{!detail||!draft?<p>Choose an incoming message. Patient review will offer matching encounters.</p>:<>
          <h3>{summary!.label}</h3><p><strong>{stateLabels[summary!.state]}</strong></p>
          {parkedHere&&<p>An unresolved command is kept for this item. Resume and resolve its exact receipt before making another change here.</p>}
          {(!summary!.binding_current||summary!.source_conflict||summary!.read_issue||summary!.incomplete_content)&&<aside role="status" className="inbox-attention"><h4>Human attention needed</h4>{!summary!.binding_current&&<p>The reviewed connection or patient mapping is unavailable.</p>}{summary!.source_conflict&&<p>Conflicting source versions are retained. A later accepted source is required before administrative completion.</p>}{summary!.read_issue&&<p>The most recent read has an unresolved source issue: {summary!.read_issue.replaceAll('_',' ')}.</p>}{summary!.incomplete_content&&<p>The complete incoming content is unavailable. Attachments, pages, buttons or events have not been retrieved, or the text is empty.</p>}</aside>}
          {show('source')&&sourceCard}
          {focused&&page==='source'&&<>
            {summary!.state==='closed_local_review'&&<p>The owner verified this local review. No reply, vendor action or clinical completion is claimed.</p>}
            <nav className="inbox-focus-actions" aria-label="Available Inbox review steps">
              {detail.availability.review&&<button onClick={()=>openPage('review')} disabled={blocked}>Review patient and thread</button>}
              {detail.availability.triage&&<button onClick={()=>openPage('triage')} disabled={blocked}>Plan human review</button>}
              {detail.availability.result&&<button onClick={()=>openPage('result')} disabled={blocked}>Record a human result</button>}
              {detail.availability.verify&&<button onClick={()=>openPage('completion')} disabled={blocked}>Review local completion</button>}
              <button onClick={()=>openPage('history')} disabled={state.blocked||state.saving}>Source and review history</button>
              {onDraftInbox&&<button onClick={openDraft} disabled={blocked||!bundle||!inboxDraftSelection(bundle)}>Draft a reply</button>}
              {onOpenHandoff&&<button onClick={openHandoff} disabled={blocked}>Open incoming follow-up</button>}
            </nav>
            {onOpenHandoff&&<p className="inbox-limit">Open existing follow-up or prepare a new task after current patient and thread review.</p>}
            {resultEvidence&&<details><summary>Last recorded human result</summary>{resultEvidence}</details>}
          </>}
          {focused&&(page==='review'||page==='completion')&&sourceCard&&<details><summary>Current incoming message</summary>{sourceCard}</details>}
          {show('review')&&(<fieldset disabled={inputBlocked||!detail.availability.review}><legend>Patient and thread review</legend>
        <button onClick={loadOptions} disabled={blocked}>Load matching encounters</button>
        {options&&<>{options.choices.length===0?<p>No current matching encounter workspace is available.</p>:<label>Matching encounter<select value={draft.workspace_id} onChange={e=>edit({workspace_id:e.target.value})}><option value="">Choose an encounter</option>{options.choices.map(o=><option key={o.workspace_id} value={o.workspace_id}>{o.label} · {new Date(o.start_at).toLocaleString()}</option>)}</select></label>}</>}
        {check('patient','I checked the patient and selected encounter')}{check('thread','I checked this exact incoming thread')}{check('untrusted','I reviewed the source as untrusted external text')}
        <button onClick={()=>command('review')} disabled={blocked||!selectedOptions||!checks.patient||!checks.thread||!checks.untrusted}>Record patient and thread review</button>
      </fieldset>)}
          {show('triage')&&(<fieldset disabled={inputBlocked||!detail.availability.triage}><legend>Human triage</legend>
        <label>Review classification<select value={draft.classification} onChange={e=>edit({classification:e.target.value as InboxDraft['classification']})}>{Object.entries(classifications).map(([value,label])=><option key={value} value={value} disabled={value==='administrative_review'&&!canAdministrative}>{label}</option>)}</select></label>
        {(draft.classification==='clinical_human_review'||draft.classification==='urgent_human_review')&&<p>This remains a human clinical review task. No clinical decision or notification is made here.</p>}
        <InboxDueDateInput label="Review due date" value={draft.due_date} onChange={value=>edit({due_date:value})} disabled={inputBlocked||!detail.availability.triage}/><label>Human review instructions<textarea maxLength={2000} value={draft.instructions} onChange={e=>edit({instructions:e.target.value})}/></label>
        {check('triage','I confirm that a human must perform this review')}
        <button onClick={()=>command('triage')} disabled={blocked||!checks.triage||!isInboxCalendarDate(draft.due_date)||!draft.instructions.trim()||draft.classification==='administrative_review'&&!canAdministrative}>Record human triage</button>
      </fieldset>)}
          {show('result')&&<>{triageEvidence}<fieldset disabled={inputBlocked||!detail.availability.result}><legend>Human result</legend>
        <label>Review outcome<select value={draft.result_disposition} onChange={e=>edit({result_disposition:e.target.value as InboxDraft['result_disposition']})}><option value="needs_human">Further human attention needed</option><option value="local_review_complete" disabled={blocked||!canAdministrative||summary!.classification!=='administrative_review'}>Local administrative review performed</option></select></label>
        <label>Human result evidence<textarea maxLength={2000} value={draft.result_evidence} onChange={e=>edit({result_evidence:e.target.value})}/></label>
        {check('result','This result claims no reply, vendor change or clinical completion')}
        <button onClick={()=>command('result')} disabled={blocked||!savedTriage||!checks.result||!draft.result_evidence.trim()}>Record human result</button>
      </fieldset></>}
          {show('completion')&&<>{resultEvidence}<fieldset disabled={inputBlocked||!detail.availability.verify}><legend>Review local completion</legend>
        {check('verifyPatient','I checked the patient for this result')}{check('verifySource','I checked the exact source observation')}{check('verifyResult','I checked the recorded human result')}{check('verifyLocal','I confirm local review completion only')}
        <button onClick={()=>command('verify')} disabled={blocked||!savedResult||!checks.verifyPatient||!checks.verifySource||!checks.verifyResult||!checks.verifyLocal}>Complete local review</button>
      </fieldset></>}
          {show('history')&&<>{earlierDrafts}{focused?historyContent:<details><summary>Retained source and human review history</summary>{historyContent}</details>}</>}
          {focused&&page==='historical'&&historical&&<article aria-label="Historical untrusted message"><h4>Retained source observation · version {historical.sequence}</h4><p>Untrusted external message text. This observation does not replace the current source.</p><pre>{historical.text}</pre></article>}
          {!focused&&(onOpenHandoff?<button onClick={openHandoff} disabled={blocked}>Open incoming follow-up</button>:<p>Handoff to another person is unavailable until the incoming-source responsibility workflow is integrated.</p>)}
        </>}</main>}
      </div>
    </>}
  </section>;
}
