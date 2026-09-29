import {useEffect,useRef,useState} from "react";
import {EditorRecoveryNotice,editorData,editorDraft,useEditorRecovery} from "./editor-recovery";
import {DraftStoreError} from "./draft-store";
import type {EditorDraft} from "./draft-journal";
import type {EncounterPrep} from "./encounter-prep-api";
import {prepWorkApi,type PrepWorkItem,type PrepWorkResult} from "./prep-work-api";
import {prepDate,prepUuid,prepWorkRequestKey,validPrepWorkRequest,type PrepWorkRequest} from "./prep-work-request";
import {validAppointmentBot} from "./appointment-request";
import {useUnsavedWork} from "./unsaved-work";
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type CaptureBotSelection,type Workspace} from "./workspace-api";

type Form={bot:CaptureBotSelection;body:string;dueDate:string;outcome:string;lastTicket:string|null;pending:PrepWorkRequest|null};
function restoreForm(draft:EditorDraft):Form {
  const d=draft.data;editorData(d,"bot,body,dueDate,outcome,lastTicket,pending");
  if(!validAppointmentBot(d.bot)||typeof d.body!=="string"||d.body.length>4000||typeof d.outcome!=="string"||d.outcome.length>500||
    !(d.dueDate===""||prepDate(d.dueDate))||!(d.lastTicket===null||prepUuid(d.lastTicket))||
    !(d.pending===null||validPrepWorkRequest(d.pending))||draft.pending!==(d.pending?prepWorkRequestKey(d.pending):null))throw new DraftStoreError("integrity");
  if(d.pending?.kind==="create"&&(d.pending.body.body!==d.body||d.pending.body.due_date!==d.dueDate||d.pending.body.expected_outcome!==d.outcome||
      JSON.stringify(d.pending.body.bot)!==JSON.stringify(d.bot))||
    d.pending&&d.pending.kind!=="create"&&d.pending.ticket!==d.lastTicket)throw new DraftStoreError("integrity");
  return d as Form;
}
const status=(item:PrepWorkItem)=>item.state==="closed"?"Provider verified":item.state==="rejected"?"Withdrawn":
  item.ready_for_review?"Ready for provider review":item.state==="approved"?"Open with the practice":"Awaiting approval";

export function PreparationWorkPanel({workspaceId,identity,bot,entryRevision,receipt,enabled,locked,onChanged,onAccessLost}: {
  workspaceId:string;identity:AuthenticatedWorkspaceIdentity;bot:CaptureBotSelection;entryRevision:number;receipt:EncounterPrep|null;
  enabled:boolean;locked:boolean;onChanged?:(revision:number)=>void;onAccessLost?:(cause:WorkspaceApiError)=>void;
}) {
  const [items,setItems]=useState<PrepWorkItem[]>([]),[item,setItem]=useState<PrepWorkItem|null>(null);
  const [body,setBody]=useState(""),[dueDate,setDueDate]=useState(""),[outcome,setOutcome]=useState("");
  const [draftBot,setDraftBot]=useState(bot),[pending,setPending]=useState<PrepWorkRequest|null>(null);
  const [freshForItem,setFreshForItem]=useState<string|null>(null);
  const [share,setShare]=useState(false),[reviewed,setReviewed]=useState(false),[busy,setBusy]=useState(false);
  const [message,setMessage]=useState(""),[rejected,setRejected]=useState(false),[checkedRejected,setCheckedRejected]=useState(false);
  const generation=useRef(0),active=useRef<AbortController|null>(null);
  const form:Form={bot:draftBot,body,dueDate,outcome,lastTicket:item?.ticket_id??null,pending};
  const recovery=useEditorRecovery(workspaceId,"prep-work",pending||body||dueDate||outcome?
    editorDraft(workspaceId,"prep-work",form,pending?prepWorkRequestKey(pending):null):null,busy||pending!==null,
    {required:true,scopeKey:`${bot.address}:${bot.team_revision}`,identity});
  useUnsavedWork(!!pending||!!body||!!dueDate||!!outcome);
  function failure(cause:unknown) {
    if(cause instanceof WorkspaceApiError&&[401,403,404].includes(cause.status)) {
      recovery.suspend();setItems([]);setItem(null);setBody("");setDueDate("");setOutcome("");setPending(null);setShare(false);setReviewed(false);
      onAccessLost?.(cause);setMessage("Preparation work is unavailable with your current access. Saved local work is retained.");
    } else if(cause instanceof WorkspaceApiError&&[400,409,422].includes(cause.status)) {
      setRejected(true);setCheckedRejected(false);
      setMessage("This request was not accepted. Check the current work and visit context before choosing another action.");
    } else if(cause instanceof DraftStoreError) setMessage("This editor could not be saved on this device. Recheck recovery before continuing.");
    else {setRejected(false);setCheckedRejected(false);setMessage("The result could not be confirmed. Retry the same request if one is pending.");}
  }
  useEffect(()=>{
    const version=++generation.current,controller=new AbortController();active.current?.abort();active.current=controller;
    setItems([]);setItem(null);setBody("");setDueDate("");setOutcome("");setDraftBot(bot);setPending(null);
    setShare(false);setReviewed(false);setMessage("");setRejected(false);setCheckedRejected(false);setBusy(true);
    void prepWorkApi.catalog(workspaceId,identity,controller.signal).then(result=>{
      if(version===generation.current&&!controller.signal.aborted)setItems(result.items);
    }).catch(cause=>{if(version===generation.current&&!controller.signal.aborted)failure(cause);})
      .finally(()=>{if(version===generation.current&&!controller.signal.aborted)setBusy(false);});
    return()=>{generation.current++;controller.abort();active.current?.abort();};
  },[workspaceId,identity,bot.address,bot.team_revision]);
  useEffect(()=>{setShare(false);setReviewed(false);setFreshForItem(item?.ready_for_review&&receipt?`${item.ticket_id}:${item.version}`:null);},[receipt]);
  useEffect(()=>{setReviewed(false);setFreshForItem(null);},[item?.ticket_id,item?.version]);
  const disabled=locked||busy||!!pending||recovery.blocked;
  function show(result:PrepWorkResult) {
    setItem(result.item);setItems(old=>[result.item,...old.filter(i=>i.ticket_id!==result.item.ticket_id)]);setReviewed(false);
  }
  async function read(ticket?:string) {
    if(disabled)return;
    const version=generation.current,controller=new AbortController();active.current=controller;setBusy(true);setMessage("");
    try {
      if(ticket){const result=await prepWorkApi.read(workspaceId,identity,ticket,controller.signal);if(version===generation.current&&!controller.signal.aborted)show(result);}
      else {const result=await prepWorkApi.catalog(workspaceId,identity,controller.signal);if(version===generation.current&&!controller.signal.aborted){setItems(result.items);setItem(old=>old?result.items.find(i=>i.ticket_id===old.ticket_id)??null:null);setReviewed(false);}}
    }catch(cause){if(version===generation.current&&!controller.signal.aborted)failure(cause);}
    finally{if(version===generation.current&&!controller.signal.aborted)setBusy(false);}
  }
  async function save(command:PrepWorkRequest) {
    if(busy||locked||recovery.blocked)return;
    const version=generation.current,controller=new AbortController();active.current=controller;
    const submitted:Form={...form,bot:command.kind==="create"?command.body.bot:draftBot,
      ...(command.kind==="create"?{body:command.body.body,dueDate:command.body.due_date,outcome:command.body.expected_outcome}:{}),
      lastTicket:command.kind==="create"?form.lastTicket:command.ticket,pending:command};
    setPending(command);setDraftBot(submitted.bot);setBody(submitted.body);setDueDate(submitted.dueDate);setOutcome(submitted.outcome);setBusy(true);setMessage("");setRejected(false);setCheckedRejected(false);
    try {
      await recovery.commit(editorDraft(workspaceId,"prep-work",submitted,prepWorkRequestKey(command)));
      if(version!==generation.current||controller.signal.aborted)return;
      const result=await prepWorkApi.save(workspaceId,identity,command,controller.signal);
      if(version!==generation.current||controller.signal.aborted)return;
      // A decision must preserve a separately started, unsent proposal form.
      const retained=command.kind==="create"?null:{...submitted,pending:null};
      await recovery.commit(retained&&(body||dueDate||outcome)?editorDraft(workspaceId,"prep-work",retained):null);
      if(version!==generation.current||controller.signal.aborted)return;
      show(result);setPending(null);setShare(false);setReviewed(false);
      if(command.kind==="create"){setBody("");setDueDate("");setOutcome("");}
      setMessage(command.kind==="create"?(result.item.state==="pending_approval"?"Proposal saved. Review the exact shared brief before approving it.":`Earlier proposal recovered: ${status(result.item)}.`):
        command.kind==="verify"?"The current saved intake summary was reviewed. Preparation work is closed.":
        command.body.choice==="reject"?"Proposal withdrawn.":result.item.state==="closed"?"Earlier approval recovered. This work has already been verified and closed.":"Approved for internal practice work. Assign it from Practice work.");
      onChanged?.(result.entry_revision);
    }catch(cause){if(version===generation.current&&!controller.signal.aborted)failure(cause);}
    finally{if(version===generation.current&&!controller.signal.aborted)setBusy(false);}
  }
  async function restore(draft:EditorDraft,_workspace:Workspace,isCurrent:()=>boolean) {
    const saved=restoreForm(draft),version=generation.current;
    const list=await prepWorkApi.catalog(workspaceId,identity);
    const current=saved.lastTicket?await prepWorkApi.read(workspaceId,identity,saved.lastTicket):null;
    if(version!==generation.current||!isCurrent())return;
    setItems(list.items);setItem(current?.item??null);setBody(saved.body);setDueDate(saved.dueDate);setOutcome(saved.outcome);
    setDraftBot(saved.bot);setPending(saved.pending);setShare(false);setReviewed(false);setRejected(false);setCheckedRejected(false);
    setMessage(saved.pending?"The exact earlier request is retained. Nothing was submitted. Review it before retrying.":
      "Draft restored. Refresh visit context and review the shared text before creating a proposal.");
  }
  async function inspectRejected() {
    if(!pending||!rejected||busy||locked||recovery.blocked||!recovery.access)return;
    const version=generation.current,controller=new AbortController();active.current=controller;setBusy(true);setCheckedRejected(false);
    try {
      await recovery.access.authorize();
      if(version!==generation.current||controller.signal.aborted)return;
      const list=await prepWorkApi.catalog(workspaceId,identity,controller.signal);
      const current=pending.kind==="create"?null:await prepWorkApi.read(workspaceId,identity,pending.ticket,controller.signal);
      if(version!==generation.current||controller.signal.aborted)return;
      setItems(list.items);if(current)show(current);setCheckedRejected(true);
    }catch(cause){if(version===generation.current&&!controller.signal.aborted)failure(cause);}
    finally{if(version===generation.current&&!controller.signal.aborted)setBusy(false);}
  }
  async function discard(rejectedRequest=false) {
    if(busy||locked||recovery.blocked||pending&&!(rejectedRequest&&rejected&&checkedRejected))return;
    const version=generation.current;setBusy(true);
    try {
      const retained=rejectedRequest?{...form,pending:null}:null;
      await recovery.commit(retained&&(body||dueDate||outcome)?editorDraft(workspaceId,"prep-work",retained):null);
      if(version!==generation.current)return;
      setPending(null);setShare(false);setReviewed(false);setRejected(false);setCheckedRejected(false);
      if(!rejectedRequest){setBody("");setDueDate("");setOutcome("");}
      setMessage(rejectedRequest?"Rejected request set aside. Draft text is retained; saved history is unchanged.":"Local proposal draft discarded.");
    }catch(cause){if(version===generation.current)failure(cause);}
    finally{if(version===generation.current)setBusy(false);}
  }
  const summary=receipt?.sources.find(s=>s.kind==="patient_intake_summary");
  const canVerify=!!summary&&!summary.truncated&&!summary.content_redacted&&!!summary.content.trim()&&freshForItem===`${item?.ticket_id}:${item?.version}`;
  return <section className="team-follow-up preparation-work" aria-label="Visit preparation work">
    <h3>Preparation follow-through</h3>
    <p>Share a specific preparation task with your practice. Staff report when it is ready; you review the current saved intake summary before closing it.</p>
    <EditorRecoveryNotice recovery={recovery} label="Preparation work" onRestore={restore}/>
    {pending&&<div className="team-recovery"><p>Unconfirmed request: {pending.kind==="create"?"create this proposal":pending.kind==="verify"?"verify the reviewed summary":pending.body.choice==="approve"?"approve this shared brief":"withdraw this proposal"}.</p>
      {pending.kind==="create"&&<><p>{pending.body.body}</p><p>Expected result: {pending.body.expected_outcome} · Due {pending.body.due_date}</p></>}
      {(draftBot.address!==bot.address||draftBot.team_revision!==bot.team_revision)&&<p>The retained request uses an earlier bot selection.</p>}
      <button disabled={busy||locked||recovery.blocked} onClick={()=>void save(pending)}>Retry same preparation request</button>
      {rejected&&<button disabled={busy||locked||recovery.blocked} onClick={()=>void inspectRejected()}>Check rejected preparation request</button>}
      {checkedRejected&&<button disabled={busy||locked||recovery.blocked} onClick={()=>void discard(true)}>Set aside rejected preparation request</button>}
    </div>}
    <details className="team-optional-settings"><summary>Assign a preparation task</summary><div className="preparation-form">
      <label>Shared preparation brief<textarea value={body} maxLength={4000} disabled={disabled||!enabled} onChange={e=>{setBody(e.target.value);setShare(false);}}/></label>
      <label>Due date<input type="date" value={dueDate} disabled={disabled||!enabled} onChange={e=>{setDueDate(e.target.value);setShare(false);}}/></label>
      <label>Expected result<textarea value={outcome} maxLength={500} disabled={disabled||!enabled} onChange={e=>{setOutcome(e.target.value);setShare(false);}}/></label>
      <label className="appointment-consent"><input type="checkbox" checked={share} disabled={disabled||!enabled||!receipt} onChange={e=>setShare(e.target.checked)}/>
        Share this brief, deadline and expected result with the practice.</label>
      {!receipt&&<p className="team-fine">Review visit context above before creating a proposal.</p>}
      <button disabled={disabled||!enabled||!receipt||!share||!body.trim()||!outcome.trim()||!prepDate(dueDate)} onClick={()=>receipt&&void save({kind:"create",body:{
        bot:{...bot},expected_entry_revision:entryRevision,snapshot_sha256:receipt.snapshot_sha256,body:body.trim(),due_date:dueDate,
        expected_outcome:outcome.trim(),share_context:true,idempotency_key:crypto.randomUUID()}})}>Create preparation proposal</button>
      {!pending&&(body||dueDate||outcome)&&<button disabled={disabled} onClick={()=>void discard()}>Discard preparation draft</button>}
    </div></details>
    {message&&<p role="status">{message}</p>}
    <button disabled={disabled} onClick={()=>void read()}>Refresh preparation work</button>
    {items.length>0&&<ul>{items.map(saved=><li key={saved.ticket_id}><button disabled={disabled} onClick={()=>void read(saved.ticket_id)}>{saved.body} · {status(saved)}</button></li>)}</ul>}
    {item&&<article className="team-follow-up">
      <h4>{status(item)}</h4><p>{item.body}</p><p>Expected result: {item.expected_outcome}</p><p>Due {item.due_date} · Responsible: {item.responsible.name}</p>
      {item.receipts.map(r=><div key={r.id}><strong>{r.kind==="ready_for_review"?"Staff readiness":r.kind==="provider_verification"?"Provider verification":"Shared internally"}</strong><p>{r.content}</p><small>{r.actor.name}</small></div>)}
      {item.state==="pending_approval"&&receipt&&receipt.snapshot_sha256!==item.proposed_snapshot_sha256&&<p role="status">Saved visit context changed since this proposal. Withdraw it and create a new proposal from the current context.</p>}
      {item.state==="pending_approval"&&<div className="capture-actions">
        <button disabled={disabled||!enabled||!receipt||receipt.snapshot_sha256!==item.proposed_snapshot_sha256} onClick={()=>receipt&&void save({kind:"decide",ticket:item.ticket_id,body:{expected_version:item.version,
          revision_id:item.revision_id,payload_hash:item.payload_hash,choice:"approve",bot:{...bot},expected_snapshot_sha256:receipt.snapshot_sha256}})}>Approve shared preparation brief</button>
        <button disabled={disabled} onClick={()=>void save({kind:"decide",ticket:item.ticket_id,body:{expected_version:item.version,
          revision_id:item.revision_id,payload_hash:item.payload_hash,choice:"reject"}})}>Withdraw preparation proposal</button>
      </div>}
      {item.state==="approved"&&item.ready_for_review&&<>
        <p>Staff reported readiness. Review the current saved intake summary above before closing this task.</p>
        {!canVerify&&<p className="team-fine">A full saved intake summary is required. Refresh visit context; an absent summary does not establish intake status.</p>}
        <label className="appointment-consent"><input type="checkbox" checked={reviewed} disabled={disabled||!enabled||!canVerify} onChange={e=>setReviewed(e.target.checked)}/>
          I reviewed the current saved intake summary for this preparation task.</label>
        <button disabled={disabled||!enabled||!canVerify||!reviewed} onClick={()=>receipt&&void save({kind:"verify",ticket:item.ticket_id,body:{bot:{...bot},
          expected_version:item.version,revision_id:item.revision_id,payload_hash:item.payload_hash,current_snapshot_sha256:receipt.snapshot_sha256,
          reviewed_summary:true,idempotency_key:crypto.randomUUID()}})}>Verify preparation and close</button>
      </>}
      <p className="team-fine">This records internal preparation and review of the saved summary. Questionnaire completion, consent and patient delivery are separate outcomes.</p>
    </article>}
  </section>;
}
