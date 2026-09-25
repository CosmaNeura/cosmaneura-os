import {useEffect,useRef,useState} from 'react';
import {WorkspaceApiError,type WorkspaceIdentity,type WorkPerson} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import {inboxHandoffApi} from './inbox-handoff-api';
import {prepareInboxHandoffOperation,type InboxHandoffKind,type InboxHandoffRequests} from './inbox-handoff-contract';
import type {Catalog,Detail,Scope,Handoff} from './inbox-handoff-schema';
import {inboxHandoffDraftKey,inboxHandoffTarget,keepInboxHandoffProof,parkInboxHandoffCommand,resumeInboxHandoffCommand,validInboxHandoffActor,unknownOwnedHandoffSource,withInboxHandoffCommand,withInboxHandoffDraft,type InboxHandoffActor,type InboxHandoffDraft,type InboxHandoffRecoveryAccess} from './inbox-handoff-recovery';
import {useInboxHandoffRecovery} from './inbox-handoff-recovery-ui';
import {readInboxHandoffPreparation,readInboxHandoffSource,validateInboxHandoffPeople,type InboxHandoffSource} from './inbox-handoff-preparation';
import {isInboxCalendarDate} from './inbox-contract';
import {InboxDueDateInput} from './InboxDueDateInput';
import './inbox-handoff.css';

const labels={pending_approval:'Needs owner approval',approved:'Active internal follow-up',closed:'Local handoff completed',rejected:'Proposal rejected',source_unavailable:'Owner attention required'};
const commandLabels={propose:'follow-up proposal',decide:'publication decision',handoff:'responsibility change',result:'human result',verify:'local completion'};
const reasons:Record<string,string>={feature_disabled:'New handoff work is disabled.',source_changed:'The incoming source changed or needs human attention.',review_changed:'The patient or thread review changed.',authority_changed:'The reviewed connection or patient authority changed.',work_changed:'This follow-up changed.',publication_required:'Current owner publication approval is required.',result_already_recorded:'A human result is already recorded.',responsibility_required:'Current responsibility is required.',responsibility_changed:'Responsibility changed.',result_changed:'The human result changed.'};
type Page='list'|'proposal'|'proposal-review'|'ticket'|'publication'|'responsibility'|'result'|'verify'|'history';
const emptyChecks=()=>({minimum:false,publication:false,responsibility:false,result:false,source:false,reviewedResult:false,local:false});
const detailBasis=(d:Detail)=>vendorCanonical(d);
const scopeFor=(actor:InboxHandoffActor,d:Pick<Detail,'originator_id'|'ticket_id'>):Scope=>({...actor,owner_id:d.originator_id,kind:'ticket',id:d.ticket_id});
const bound=(d:Detail)=>({idempotency_key:`inbox-handoff-${crypto.randomUUID()}`,ticket_id:d.ticket_id,expected_version:d.version,revision_id:d.revision_id,payload_hash:d.payload_hash});
const current=(d:Detail)=>d.state!=='source_unavailable'&&!d.requires_owner_attention;

export type InboxHandoffPanelProps={
  identity:WorkspaceIdentity;actor:InboxHandoffActor;recovery:InboxHandoffRecoveryAccess|null;
  /** Selection hint only. Source/review/workspace authority is freshly read from the server. */
  sourceItemId?:string;sourceRequest?:number;selectedTicketId?:string;ticketRequest?:number;loadPeople?:()=>Promise<WorkPerson[]>;enabled?:boolean;onDone?:()=>void;onBusyChange?:(blocked:boolean)=>void;
};
export function InboxHandoffPanel(props:InboxHandoffPanelProps){
  const {identity,actor,recovery,enabled=false}=props,actorKey=vendorCanonical(actor);
  const [loaded,setLoaded]=useState<{identity:WorkspaceIdentity;recovery:InboxHandoffRecoveryAccess|null;actorKey:string;catalog:Catalog}|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),epoch=useRef(0);
  useEffect(()=>{const gen=++epoch.current,c=new AbortController();setLoaded(null);setError('');
    if(enabled&&validInboxHandoffActor(actor)&&recovery)void(async()=>{await recovery.authorize();const catalog=await inboxHandoffApi.catalog(identity,actor,c.signal);if(gen===epoch.current)setLoaded({identity,recovery,actorKey,catalog});})().catch(e=>{if(gen!==epoch.current)return;setError('Incoming follow-up is unavailable. Recheck your account access before reopening.');if(e instanceof WorkspaceApiError&&[401,403,404].includes(e.status))recovery?.denied?.(e);});
    return()=>{epoch.current++;c.abort();};
  },[identity,recovery,actorKey,enabled,attempt]);
  if(!enabled)return <p>Incoming follow-up is not enabled in this environment.</p>;
  if(!recovery||!validInboxHandoffActor(actor))return <p role="alert">Authorized private saved-work storage is required for incoming follow-up.</p>;
  if(!loaded||loaded.identity!==identity||loaded.recovery!==recovery||loaded.actorKey!==actorKey)return <section className="inbox-handoff"><h2>Incoming follow-up</h2><p role={error?'alert':'status'}>{error||'Loading incoming follow-up…'}</p>{error&&<button onClick={()=>setAttempt(n=>n+1)}>Recheck follow-up access</button>}</section>;
  return <Editor key={actorKey} {...props} initial={loaded.catalog} onDenied={()=>{epoch.current++;setLoaded(null);setError('Access to incoming follow-up is unavailable. Sign in and reopen.');}}/>;
}
function Editor({identity,actor,recovery,sourceItemId,sourceRequest,selectedTicketId,ticketRequest,loadPeople,onDone,onBusyChange,initial,onDenied}:InboxHandoffPanelProps&{initial:Catalog;onDenied:()=>void}){
  const state=useInboxHandoffRecovery(recovery,actor),[catalog,setCatalog]=useState(initial),[page,setPage]=useState<Page>('list'),[detail,setDetail]=useState<Detail|null>(null),[preparation,setPreparation]=useState<InboxHandoffSource|null>(null),[people,setPeople]=useState<WorkPerson[]>([]),[checks,setChecks]=useState(emptyChecks),epoch=useRef(0);
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  const navigationBlocked=state.busy||state.saving||state.saveFailed||state.unsavedInput;
  const seenTicketRequest=useRef(ticketRequest);
  useEffect(()=>{
    if(ticketRequest===seenTicketRequest.current||navigationBlocked)return;
    seenTicketRequest.current=ticketRequest;
    setPage('list');setChecks(emptyChecks());setDetail(null);setPreparation(null);
    // A brief selects a current catalog target, never a restored command or consent.
  },[ticketRequest,navigationBlocked]);
  const seenSourceRequest=useRef(sourceRequest);
  useEffect(()=>{
    if(sourceRequest===seenSourceRequest.current||navigationBlocked)return;
    seenSourceRequest.current=sourceRequest;
    if(sourceItemId){setPage('list');setChecks(emptyChecks());setDetail(null);setPreparation(null);}
    // Navigation retains drafts and exact pending requests; preparation remains a deliberate action.
  },[sourceRequest,sourceItemId,navigationBlocked]);
  useEffect(()=>{callback.current?.(navigationBlocked);},[navigationBlocked,onBusyChange]);
  useEffect(()=>()=>{epoch.current++;callback.current?.(false);},[]);
  useEffect(()=>{if(!navigationBlocked)return;const f=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',f);return()=>window.removeEventListener('beforeunload',f);},[navigationBlocked]);
  useEffect(()=>{setChecks(emptyChecks());},[state.offer,state.saveFailed,page]);
  useEffect(()=>{if(state.denied){setDetail(null);setPreparation(null);onDenied();}},[state.denied]);
  const io=async<T,>(promise:Promise<T>,scoped=false)=>{const gen=epoch.current;try{const value=await promise;if(gen!==epoch.current)throw Error('Actor changed');return value;}catch(e){
    if(gen===epoch.current&&scoped&&e instanceof WorkspaceApiError&&e.status===404){
      setDetail(null);setPreparation(null);setChecks(emptyChecks());
      try{await recovery!.authorize();const c=await inboxHandoffApi.catalog(identity,actor);if(gen!==epoch.current)throw Error('Actor changed');setCatalog(c);setDetail(null);setPreparation(null);setChecks(emptyChecks());state.setStatus('This item is unavailable. Its saved request remains unresolved; retain it for exact recovery.');throw Error('Scoped item unavailable');}catch(checkError){if(checkError instanceof WorkspaceApiError&&[401,403,404].includes(checkError.status)){state.rejectAccess(checkError);onDenied();}throw checkError;}
    }
    if(gen===epoch.current&&state.rejectAccess(e)){epoch.current++;setDetail(null);setPreparation(null);setPeople([]);onDenied();}throw e;
  }};
  const draft=state.record.drafts.find(d=>inboxHandoffDraftKey(d)===state.record.selected)??null;
  const pending=state.record.pending,receipt=state.record.receipt;
  const target=draft?.kind==='proposal'?`item:${draft.basis.item_id}`:draft?.kind==='ticket'?`ticket:${draft.ticket_id}`:null;
  const parked=target?state.record.parked.find(x=>inboxHandoffTarget(x.operation)===target||detail?.private_source&&x.operation.kind==='propose'&&x.operation.request.item_id===detail.private_source.item_id||draft?.kind==='proposal'&&x.operation.kind!=='propose'&&(unknownOwnedHandoffSource(state.record,x.operation)||state.record.drafts.some(t=>t.kind==='ticket'&&t.ticket_id===x.operation.scope.id&&t.source_item_id===draft.basis.item_id))):null;
  const inputBlocked=state.blocked||!!pending||!!parked;
  const blocked=inputBlocked||state.saving;
  const reset=()=>{setChecks(emptyChecks());setPreparation(null);};
  const edit=(patch:Partial<InboxHandoffDraft>)=>{if(inputBlocked||!draft)return;setChecks(emptyChecks());const latest=state.current.current.drafts.find(x=>inboxHandoffDraftKey(x)===inboxHandoffDraftKey(draft))??draft;try{void state.save(withInboxHandoffDraft(state.current.current,{...latest,...patch} as InboxHandoffDraft)).catch(()=>{});}catch{state.setStatus('This edit exceeds saved-work limits or contains unsupported text. Your previous input is retained.');}};
  const refresh=()=>state.run(async()=>{setCatalog(await io(inboxHandoffApi.catalog(identity,actor)));setDetail(null);setPreparation(null);setPage('list');setChecks(emptyChecks());});
  const selectTicket=(ticketId:string)=>state.run(async()=>{if(state.current.current.pending)return;const item=catalog.items.find(x=>x.ticket_id===ticketId);if(!item)return;
    const d=await io(inboxHandoffApi.detail(identity,scopeFor(actor,item)),true);const existing=state.current.current.drafts.find(x=>x.kind==='ticket'&&x.ticket_id===ticketId);
    await state.save(withInboxHandoffDraft(state.current.current,existing?{...existing,...(existing.kind==='ticket'?{source_item_id:d.private_source?.item_id??null}:{})}:{kind:'ticket',ticket_id:ticketId,owner_id:d.originator_id,source_item_id:d.private_source?.item_id??null,recipient_id:'',evidence:''}));setDetail(d);reset();setPage('ticket');
  });
  const prepare=(itemId:string)=>state.run(async()=>{if(state.current.current.pending)return;const p=await io(readInboxHandoffPreparation(identity,actor,itemId),true),value:InboxHandoffDraft={kind:'proposal',basis:p.basis,instructions:'',selected_context:'',due_date:'',expected_outcome:''};
    const saved=state.current.current.drafts.find(x=>inboxHandoffDraftKey(x)===inboxHandoffDraftKey(value));await state.save(withInboxHandoffDraft(state.current.current,saved??value));setDetail(null);setPreparation(p);setChecks(emptyChecks());setPage('proposal');
  });
  const resumeDraft=(value:InboxHandoffDraft)=>state.run(async()=>{if(state.current.current.pending)return;await state.save({...state.current.current,selected:inboxHandoffDraftKey(value)});setDetail(null);reset();setPage(value.kind==='proposal'?'proposal':'ticket');
    if(value.kind==='ticket')setDetail(await io(inboxHandoffApi.detail(identity,{...actor,owner_id:value.owner_id,kind:'ticket',id:value.ticket_id}),true));
    else {const p=await io(readInboxHandoffPreparation(identity,actor,value.basis.item_id),true);if(vendorCanonical(p.basis)===vendorCanonical(value.basis))setPreparation(p);else state.setStatus('The source or matching encounter changed. This earlier draft remains saved; return to Inbox for a fresh review before preparing a new proposal.');}
  });
  const freshTicket=async()=>{if(!detail)return null;const d=await io(inboxHandoffApi.detail(identity,scopeFor(actor,detail)),true);if(detailBasis(d)!==detailBasis(detail)){setDetail(d);reset();setPage('ticket');state.setStatus('This follow-up changed. Review its current state before a new action.');return null;}setDetail(d);return d;};
  const exactSource=async(d:Detail)=>{if(!d.private_source||d.originator_id!==actor.actor_id||!current(d))return false;const p=await io(readInboxHandoffSource(identity,actor,d.private_source.item_id),true),b=p.bundle.detail.summary,r=p.bundle.detail.latest_review!,s=d.private_source;
    if(b.source_id!==s.source_id||b.source_sha256!==s.source_sha256||r.receipt_id!==s.review_receipt_id||r.receipt_sha256!==s.review_receipt_sha256){reset();state.setStatus('The incoming source or patient review changed. Return to Inbox for current human review.');return false;}setPreparation(p);return true;
  };
  const open=(next:Page)=>state.run(async()=>{if(blocked)return;const d=await freshTicket();if(!d)return;reset();
    if((next==='publication'||next==='verify')&&!await exactSource(d))return;
    if(next==='responsibility'){if(loadPeople)setPeople(validateInboxHandoffPeople(await io(loadPeople())));else setPeople([]);}
    setPage(next);
  });
  const execute=async<K extends InboxHandoffKind>(scope:Scope,kind:K,request:InboxHandoffRequests[K],relatedItemId?:string)=>{const op=await prepareInboxHandoffOperation(scope,kind,request);await state.save(withInboxHandoffCommand(state.current.current,op,relatedItemId));const proof=await io(inboxHandoffApi.execute(identity,op),true);await state.save({...state.current.current,receipt:proof});setChecks(emptyChecks());state.setStatus(proof.outcome==='recorded'?'The exact internal action is recorded. Keep its proof before continuing.':`Permanently rejected: ${reasons[proof.rejection??'']??'Review the current item.'}`);};
  const reviewProposal=()=>{if(blocked||draft?.kind!=='proposal'||!preparation||!draft.instructions.trim()||!draft.expected_outcome.trim()||!isInboxCalendarDate(draft.due_date))return;setPage('proposal-review');};
  const propose=()=>state.run(async()=>{if(blocked||draft?.kind!=='proposal'||!checks.minimum||!preparation||!isInboxCalendarDate(draft.due_date))return;const p=await io(readInboxHandoffPreparation(identity,actor,draft.basis.item_id),true);if(vendorCanonical(p.basis)!==vendorCanonical(draft.basis)){reset();state.setStatus('The source or encounter changed. The saved proposal text is retained; return to Inbox for current review.');return;}
    const b=p.basis;await execute({...actor,owner_id:actor.actor_id,kind:'workspace',id:b.workspace_id},'propose',{idempotency_key:`inbox-handoff-${crypto.randomUUID()}`,item_id:b.item_id,source_id:b.source_id,source_sha256:b.source_sha256,review_receipt_id:b.review_receipt_id,review_receipt_sha256:b.review_receipt_sha256,expected_workspace_revision:b.expected_workspace_revision,instructions:draft.instructions,...(draft.selected_context.trim()?{selected_context:draft.selected_context}:{}),due_date:draft.due_date,expected_outcome:draft.expected_outcome,reviewed_minimum_context:true});
  });
  const decide=(choice:'approve'|'reject')=>state.run(async()=>{if(blocked||!checks.publication)return;const d=await freshTicket();if(!d||d.originator_id!==actor.actor_id||d.state!=='pending_approval'||!current(d)||!d.due_date||!d.expected_outcome||!preparation||!await exactSource(d))return;
    await execute(scopeFor(actor,d),'decide',{...bound(d),choice,publish_selected_context:true},d.private_source?.item_id);
  });
  const responsibility=(kind:Handoff['kind'])=>state.run(async()=>{if(blocked||!checks.responsibility||draft?.kind!=='ticket')return;const d=await freshTicket();if(!d||d.state!=='approved'||!d.publication_active||!current(d))return;const offer=d.handoffs.at(-1)?.kind==='offer'?d.handoffs.at(-1)!:null;
    if(kind==='offer'){if(!loadPeople||d.responsible_id!==actor.actor_id||offer||d.result||d.handoffs.length>=199)return;const fresh=validateInboxHandoffPeople(await io(loadPeople()));setPeople(fresh);const chosen=fresh.find(p=>p.id===draft.recipient_id&&p.available&&p.id!==d.responsible_id);if(!chosen||vendorCanonical(chosen)!==vendorCanonical(people.find(p=>p.id===chosen.id))){setChecks(emptyChecks());state.setStatus('The available colleague or their label changed. Review the current choice.');return;}}
    else if(kind==='reclaim'){if(d.originator_id!==actor.actor_id||d.responsible_id===actor.actor_id||d.handoffs.length>=201)return;}
    else if(!offer||d.result||actor.actor_id!==(kind==='recall'?offer.from_id:offer.to_id))return;
    await execute(scopeFor(actor,d),'handoff',{...bound(d),kind,...(kind==='offer'?{recipient_id:draft.recipient_id}:{}),...(['accept','decline','recall'].includes(kind)?{offer_id:offer!.id}:{})},d.private_source?.item_id);
  });
  const result=()=>state.run(async()=>{if(blocked||draft?.kind!=='ticket'||!checks.result||!draft.evidence.trim())return;const d=await freshTicket();if(!d||d.state!=='approved'||!d.publication_active||!current(d)||d.responsible_id!==actor.actor_id||d.result)return;await execute(scopeFor(actor,d),'result',{...bound(d),evidence:draft.evidence,no_external_action_claimed:true},d.private_source?.item_id);});
  const verify=()=>state.run(async()=>{if(blocked||!checks.source||!checks.reviewedResult||!checks.local||!preparation)return;const d=await freshTicket();if(!d||d.originator_id!==actor.actor_id||d.state!=='approved'||!d.publication_active||!current(d)||!d.result||!await exactSource(d))return;await execute(scopeFor(actor,d),'verify',{...bound(d),result_receipt_id:d.result.receipt_id,result_request_sha256:d.result.request_sha256,reviewed_current_source:true,reviewed_result:true,local_handoff_only:true},d.private_source?.item_id);});
  const recover=(retry=false)=>state.run(async()=>{const op=state.current.current.pending;if(!op||state.current.current.receipt&&state.current.current.receipt.outcome!=='not_found'||retry&&state.current.current.receipt?.outcome!=='not_found')return;const proof=await io(retry?inboxHandoffApi.execute(identity,op):inboxHandoffApi.recover(identity,op),true);await state.save({...state.current.current,receipt:proof});setChecks(emptyChecks());});
  const keep=()=>state.run(async()=>{await state.save(keepInboxHandoffProof(state.current.current));setCatalog(await io(inboxHandoffApi.catalog(identity,actor)));setDetail(null);reset();setPage('list');state.setStatus('Proof saved. Choose the next step.');});
  const park=()=>state.run(async()=>{await state.save(parkInboxHandoffCommand(state.current.current));setDetail(null);reset();setPage('list');});
  const resume=(target:string)=>state.run(async()=>{await state.save(resumeInboxHandoffCommand(state.current.current,target));setDetail(null);reset();});
  const checkbox=(name:keyof ReturnType<typeof emptyChecks>,label:string)=><label className="inbox-handoff-check"><input type="checkbox" checked={checks[name]} disabled={blocked} onChange={e=>setChecks(v=>({...v,[name]:e.target.checked}))}/>{label}</label>;
  const owner=detail?.originator_id===actor.actor_id,active=!!detail&&current(detail)&&detail.state==='approved'&&detail.publication_active;
  const offer=detail?.handoffs.at(-1)?.kind==='offer'?detail.handoffs.at(-1)!:null;
  const displayName=(id:string)=>people.find(p=>p.id===id)?.name??(id===actor.actor_id?'You':`Colleague ${id.slice(0,8)}`);
  const sourceView=preparation?.bundle.detail.source;
  const title=page==='proposal'?'Prepare follow-up':page==='proposal-review'?'Review proposal':page==='publication'?'Review shared context':page==='responsibility'?'Responsibility':page==='result'?'Record human result':page==='verify'?'Verify local completion':page==='history'?'Saved action history':'Incoming follow-up';
  return <section className="inbox-handoff" aria-label="Incoming follow-up">
    <header><h2>{title}</h2>{onDone&&<button onClick={onDone} disabled={navigationBlocked}>Done</button>}</header>
    <p>Accountable internal work. These actions do not send a reply, notify an external service or make a clinical decision.</p>
    {state.error&&<p role="alert">{state.error}</p>}{state.status&&<p role="status">{state.status}</p>}
    {state.loadFailed&&<button onClick={state.retryLoad}>Retry loading saved follow-up</button>}
    {state.saveFailed&&<button onClick={()=>void state.retrySave()} disabled={state.busy||state.saving}>Retry saving retained follow-up</button>}
    {state.offer&&<aside><p>Saved drafts and exact actions are available. Confirmations will be required again.</p><button onClick={()=>void state.restore()} disabled={state.busy}>Restore saved follow-up</button></aside>}
    {pending?<aside aria-label="Exact saved follow-up action"><h3>Saved {commandLabels[pending.kind]}</h3>
      {receipt&&receipt.outcome!=='not_found'?<><p>{receipt.outcome==='recorded'?'Recorded internal action.':`Permanently rejected: ${reasons[receipt.rejection??'']??'Review the current item.'}`}</p><button onClick={()=>void keep()} disabled={state.blocked||state.saving}>Keep proof and continue</button></>:<><p>{receipt?.outcome==='not_found'?'No receipt found. This exact request is still pending.':'The outcome is unknown. Recover the exact saved receipt.'}</p><button onClick={()=>void recover()} disabled={state.blocked||state.saving}>Recover exact receipt</button>{receipt?.outcome==='not_found'&&<button onClick={()=>void recover(true)} disabled={state.blocked||state.saving}>Retry exact saved action</button>}<button onClick={()=>void park()} disabled={state.blocked||state.saving}>Keep unresolved and return to list</button></>}
      <details><summary>Exact request and proof</summary><pre>{vendorCanonical({operation:pending,receipt})}</pre></details>
    </aside>:<>
      {state.record.parked.length>0&&<aside aria-label="Unresolved follow-up actions"><h3>Unresolved actions</h3><p>These requests remain saved. Parking does not cancel them.</p>{state.record.parked.map(p=><button key={inboxHandoffTarget(p.operation)} disabled={state.blocked||state.saving} onClick={()=>void resume(inboxHandoffTarget(p.operation))}>Resume {commandLabels[p.operation.kind]} · {inboxHandoffTarget(p.operation).slice(-8)}</button>)}</aside>}
      {page==='list'&&<>{selectedTicketId&&<div><p>Selected from a dated brief. Review the current follow-up before taking any action.</p>{catalog.items.some(x=>x.ticket_id===selectedTicketId)?<button disabled={state.blocked||state.saving||!!state.record.pending} onClick={()=>void selectTicket(selectedTicketId)}>Review selected incoming follow-up</button>:<p>This selected follow-up is unavailable in your current catalog.</p>}</div>}<button onClick={()=>void refresh()} disabled={state.blocked||state.saving}>Refresh follow-up</button>{sourceItemId&&<button onClick={()=>void prepare(sourceItemId)} disabled={state.blocked||state.saving}>Prepare from selected Inbox message</button>}
        <nav aria-label="Incoming follow-up items">{catalog.items.map(d=><button key={d.ticket_id} onClick={()=>void selectTicket(d.ticket_id)} disabled={state.blocked||state.saving}>{labels[d.state]} · {d.ticket_id.slice(0,8)}</button>)}</nav>{!catalog.items.length&&<p>No incoming follow-up is available.</p>}
        {state.record.drafts.length>0&&<details><summary>Saved drafts</summary>{state.record.drafts.map(d=><button key={inboxHandoffDraftKey(d)} disabled={state.blocked||state.saving} onClick={()=>void resumeDraft(d)}>Resume {d.kind==='proposal'?`proposal · ${d.basis.label}`:`work · ${d.ticket_id.slice(0,8)}`}</button>)}</details>}
        <button onClick={()=>setPage('history')} disabled={state.blocked||state.saving}>Saved action history</button>
      </>}
      {page!=='list'&&<button onClick={()=>{setPage(page==='proposal-review'?'proposal':'list');setChecks(emptyChecks());}} disabled={state.blocked||state.saving}>Back</button>}
      {parked&&<p role="alert">An exact request for this item is unresolved. Resume its recovery before another action.</p>}
      {(page==='proposal'||page==='proposal-review')&&draft?.kind==='proposal'&&<>
        <p>Reviewed encounter: {draft.basis.label}</p>{!preparation&&<p role="alert">Current source review is unavailable. Your earlier draft is retained.</p>}
        {page==='proposal'?<fieldset disabled={inputBlocked}><legend>What should a person do?</legend>
          <label>Follow-up instructions<textarea maxLength={4000} value={draft.instructions} onChange={e=>edit({instructions:e.target.value})}/></label>
          <label>Expected outcome<input maxLength={500} value={draft.expected_outcome} onChange={e=>edit({expected_outcome:e.target.value})}/></label>
          <InboxDueDateInput label="Due date" value={draft.due_date} onChange={value=>edit({due_date:value})} disabled={inputBlocked}/>
          <details><summary>Add minimum message context</summary><p>Only the text you choose here can be shared with the assigned colleague after approval.</p><label>Selected context<textarea maxLength={2000} value={draft.selected_context} onChange={e=>edit({selected_context:e.target.value})}/></label></details>
          <button disabled={blocked||!preparation||!draft.instructions.trim()||!draft.expected_outcome.trim()||!isInboxCalendarDate(draft.due_date)} onClick={reviewProposal}>Review proposal</button>
        </fieldset>:<><article aria-label="Exact proposal review"><h3>Proposed internal follow-up</h3><pre>{draft.instructions}</pre><p>{draft.expected_outcome} · due {draft.due_date}</p>{draft.selected_context.trim()?<pre>{draft.selected_context}</pre>:<p>No message context selected.</p>}</article>{checkbox('minimum','I reviewed this exact follow-up and selected only the necessary context')}<button disabled={blocked||!preparation||!checks.minimum||!isInboxCalendarDate(draft.due_date)} onClick={()=>void propose()}>Save proposal for approval</button><p>Saving the proposal does not publish it or transfer responsibility.</p></>}
      </>}
      {detail&&page!=='list'&&page!=='history'&&<><p>{labels[detail.state]}</p>{!current(detail)&&<p role="alert">{reasons[detail.private_source?.unavailability??'source_changed']} Existing results do not prove current completion. Return to the owner for review.</p>}
        {page==='ticket'&&<><h3>Follow-up</h3>{detail.instructions&&<pre>{detail.instructions}</pre>}{detail.expected_outcome&&<p>{detail.expected_outcome} · due {detail.due_date}</p>}{detail.selected_context&&<details><summary>Shared context</summary><pre>{detail.selected_context}</pre></details>}<p>Responsible: {displayName(detail.responsible_id)}</p>
          {owner&&detail.state==='pending_approval'&&current(detail)&&<button onClick={()=>void open('publication')} disabled={blocked}>Review publication</button>}
          {active&&<button onClick={()=>void open('responsibility')} disabled={blocked}>Review responsibility</button>}
          {active&&!detail.result&&detail.responsible_id===actor.actor_id&&<button onClick={()=>void open('result')} disabled={blocked}>Record human result</button>}
          {active&&detail.result&&owner&&<button onClick={()=>void open('verify')} disabled={blocked}>Review result for completion</button>}
          {detail.result&&<details><summary>Recorded human result</summary><pre>{detail.result.evidence}</pre><p>Reported by {displayName(detail.result.actor_id)}</p></details>}
          {detail.verified_current&&<p>Owner verified this local handoff against its current source. No external completion is claimed.</p>}
        </>}
        {page==='publication'&&owner&&<><article aria-label="Fresh publication review"><h3>Context to share internally</h3><pre>{detail.instructions}</pre>{detail.selected_context?<pre>{detail.selected_context}</pre>:<p>No message context selected.</p>}{detail.due_date&&detail.expected_outcome?<p>{detail.expected_outcome} · due {detail.due_date}</p>:<p role="alert">The server has not provided the complete current review. Approval is unavailable; saved local fields cannot replace a fresh review.</p>}</article>{checkbox('publication','I reviewed the exact instructions, outcome, due date and selected context')}<button disabled={blocked||!checks.publication||!detail.due_date||!detail.expected_outcome||!preparation} onClick={()=>void decide('approve')}>Approve internal publication</button><button disabled={blocked||!checks.publication||!detail.due_date||!detail.expected_outcome||!preparation} onClick={()=>void decide('reject')}>Reject proposal</button><p>Approval permits selected internal context only. Responsibility stays with the owner until a colleague accepts.</p></>}
        {page==='responsibility'&&draft?.kind==='ticket'&&<fieldset disabled={blocked||!active}><legend>Choose the next responsibility step</legend><p>Responsible now: {displayName(detail.responsible_id)}</p>
          {!detail.result&&detail.responsible_id===actor.actor_id&&!offer&&<>{loadPeople?<label>Colleague<select value={draft.recipient_id} onChange={e=>edit({recipient_id:e.target.value})}><option value="">Choose a colleague</option>{people.filter(p=>p.available&&p.id!==detail.responsible_id).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>:<p>Current practice colleague selection is unavailable.</p>}{draft.recipient_id&&<p>Selected colleague ID: <code>{draft.recipient_id}</code></p>}</>}
          {offer&&<p>{displayName(offer.from_id)} offered this work to {displayName(offer.to_id)}. An offer does not transfer responsibility.</p>}
          {checkbox('responsibility','I reviewed the exact responsibility change')}
          {!detail.result&&detail.responsible_id===actor.actor_id&&!offer&&<button disabled={!checks.responsibility||!draft.recipient_id||!loadPeople||detail.handoffs.length>=199} onClick={()=>void responsibility('offer')}>Offer responsibility</button>}
          {!detail.result&&offer?.to_id===actor.actor_id&&<><button disabled={!checks.responsibility} onClick={()=>void responsibility('accept')}>Accept responsibility</button><button disabled={!checks.responsibility} onClick={()=>void responsibility('decline')}>Decline offer</button></>}
          {!detail.result&&offer?.from_id===actor.actor_id&&<button disabled={!checks.responsibility} onClick={()=>void responsibility('recall')}>Recall offer</button>}
          {owner&&detail.responsible_id!==actor.actor_id&&<button disabled={!checks.responsibility||detail.handoffs.length>=201} onClick={()=>void responsibility('reclaim')}>Reclaim responsibility</button>}
        </fieldset>}
        {page==='result'&&draft?.kind==='ticket'&&<fieldset disabled={inputBlocked||!active}><legend>What did the responsible person do?</legend><label>Human result evidence<textarea maxLength={2000} value={draft.evidence} onChange={e=>edit({evidence:e.target.value})}/></label>{checkbox('result','This result claims no vendor action, reply or clinical completion')}<button disabled={blocked||!checks.result||!draft.evidence.trim()||!!detail.result||detail.responsible_id!==actor.actor_id} onClick={()=>void result()}>Save human result</button></fieldset>}
        {page==='verify'&&owner&&detail.result&&<><article aria-label="Exact human result"><pre>{detail.result.evidence}</pre><p>Reported by {displayName(detail.result.actor_id)}</p></article>{checkbox('source','I reviewed the current incoming source and patient review')}{checkbox('reviewedResult','I reviewed this exact recorded human result')}{checkbox('local','I confirm local handoff completion only')}<button disabled={blocked||!active||!preparation||!checks.source||!checks.reviewedResult||!checks.local} onClick={()=>void verify()}>Verify local completion</button></>}
        <details><summary>Responsibility history and identifiers</summary><p>Ticket: <code>{detail.ticket_id}</code></p><p>Owner: <code>{detail.originator_id}</code></p>{detail.handoffs.map(h=><p key={h.id}>{h.kind} · {displayName(h.from_id)} → {displayName(h.to_id)}</p>)}<pre>{vendorCanonical({revision_id:detail.revision_id,payload_hash:detail.payload_hash,private_source:detail.private_source??null})}</pre></details>
      </>}
      {sourceView&&['proposal','proposal-review','publication','verify'].includes(page)&&<details><summary>Reviewed incoming source</summary><p>Untrusted external message text, shown literally for human review.</p><pre>{sourceView.text}</pre></details>}
      {page==='history'&&<><p>Exact requests and terminal proofs retained on this device.</p>{state.record.history.length===0&&<p>No saved terminal actions.</p>}{state.record.history.map(h=><details key={h.receipt.outcome==='not_found'?h.operation.request_sha256:h.receipt.receipt_id}><summary>{commandLabels[h.operation.kind]} · {h.receipt.outcome}</summary><pre>{vendorCanonical(h)}</pre></details>)}</>}
    </>}
  </section>;
}
