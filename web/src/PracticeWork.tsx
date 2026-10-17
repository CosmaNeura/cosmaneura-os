import { useContext, useEffect, useRef, useState } from "react";
import { useUnsavedWork } from "./unsaved-work";
import { AccountRecoveryContext } from "./account-recovery";
import { DraftStoreError } from "./draft-store";
import {accountEditorDraft,AccountEditorRecoveryNotice,useAccountEditorRecovery} from "./account-editor-recovery";
import {editorData} from "./editor-recovery";
import type {AccountEditorDraft} from "./draft-journal";
import { validPracticeOperation, type PracticeWorkOperation as Pending } from "./practice-work-request";
import { VendorPracticeMount } from "./VendorWorkMount";
import { workspaceApi, WorkspaceApiError, type PracticeWorkItem,
  type PracticeWorkEntry, type WorkHandoffKind, type WorkPerson, type WorkspaceIdentity } from "./workspace-api";

const ADDRESS = "account:practice-work";
function requirePreparationVersion(operation: Pending, item: PracticeWorkItem) {
  if (operation.type === "complete" && item.work_kind === "visit_preparation" &&
      (!Number.isSafeInteger(operation.body.expected_version) || Number(operation.body.expected_version) < 1)) {
    throw new DraftStoreError("integrity");
  }
}

export function PracticeWork({ identity, onChanged, onAccessLost }: {
  identity: WorkspaceIdentity; onChanged: () => void; onAccessLost: (cause: WorkspaceApiError) => void;
}) {
  const [query,setQuery]=useState(''),[filter,setFilter]=useState<'all'|'mine'|'offers'|'overdue'|'complete'>('all');
  const [items, setItems] = useState<PracticeWorkEntry[]>([]);
  const [people, setPeople] = useState<WorkPerson[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const recovery = useContext(AccountRecoveryContext);
  const authenticated = "mode" in identity;
  const [offer, setOffer] = useState<Pending | null>(null);
  const [recoveryReady, setRecoveryReady] = useState(!authenticated);
  const [recoveryError, setRecoveryError] = useState(false);
  const [recoveryEpoch, setRecoveryEpoch] = useState(0);
  const [rejected, setRejected] = useState(false);
  const [checkedRejected, setCheckedRejected] = useState(false);
  const currentRecovery = useRef(recovery); currentRecovery.current = recovery;
  const recoveryBlocked = authenticated && (!recovery || !recoveryReady || recoveryError || !!offer);
  useUnsavedWork(pending !== null || !!offer || recoveryError);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const generation = useRef(0);

  function failure(cause: unknown) {
    if (cause instanceof WorkspaceApiError && [401, 403, 404].includes(cause.status)) {
      setItems([]); setPeople([]); setCursor(null); setPending(null);
      setError("This work is no longer available to your account.");
      if (cause.status !== 404) onAccessLost(cause);
    } else if (cause instanceof WorkspaceApiError && [400, 409, 422].includes(cause.status)) {
      if (!authenticated) setPending(null);
      setRejected(authenticated); setCheckedRejected(false); setConflict(true);
      setError("This action was not accepted. Refresh the work and review its current responsibility before trying again.");
    } else {
      setError("The result could not be confirmed. Retry the same action before making another change.");
    }
  }

  async function load(after?: string) {
    const current = generation.current;
    setBusy(true); setError("");
    try {
      const page = await workspaceApi.practiceWork(identity, after);
      if (current !== generation.current) return;
      setItems(previous => after ? [...previous, ...page.items.filter(item => !previous.some(old => old.ticket_id === item.ticket_id))] : page.items);
      setPeople(page.people); setCursor(page.next_cursor); setLoaded(true); setConflict(false);
    } catch (cause) { if (current === generation.current) failure(cause); }
    finally { if (current === generation.current) setBusy(false); }
  }

  useEffect(() => {
    generation.current++;
    setItems([]); setPeople([]); setPending(null); setLoaded(false); setConflict(false);
    void load();
    return () => { generation.current++; };
  }, [identity]);

  useEffect(() => {
    let cancelled=false;
    const current=generation.current;
    setRecoveryReady(!authenticated); setRecoveryError(false); setOffer(null);
    if (authenticated && recovery) {
      void recovery.journal.load(ADDRESS).then(draft => {
        if (cancelled || current!==generation.current) return;
        if (draft && draft.kind!=="account-operation") throw new DraftStoreError("integrity");
        setOffer(draft?.pending ?? null); setRecoveryReady(true);
      }).catch(() => { if (!cancelled && current===generation.current) setRecoveryError(true); });
    }
    return () => {cancelled=true;};
  }, [identity,recovery,recoveryEpoch]);

  function show(item: PracticeWorkEntry) {
    setItems(previous => previous.some(old=>old.ticket_id===item.ticket_id)
      ? previous.map(old=>old.ticket_id===item.ticket_id?item:old) : [item,...previous]);
  }
  async function restore() {
    if (!recovery || !offer || busy || recoveryError) return;
    const current=generation.current; setBusy(true); setError("");
    try {
      await recovery.authorize();
      const item=await workspaceApi.practiceWorkItem(identity,offer.ticketId);
      if (current!==generation.current || currentRecovery.current!==recovery) return;
      if (!validPracticeOperation(offer)) throw new DraftStoreError("integrity");
      requirePreparationVersion(offer,item);
      show(item); setPending(offer); setOffer(null); setRejected(false); setCheckedRejected(false);
      setError("The exact request is restored. Nothing was sent. Review current work, then choose Retry same action.");
    } catch(cause) {if(current===generation.current) {
      if(cause instanceof DraftStoreError) setRecoveryError(true); else failure(cause);
    }}
    finally {if(current===generation.current) setBusy(false);}
  }
  async function inspectRejected() {
    if (!pending || !recovery || busy) return;
    const current=generation.current;setBusy(true);
    try {
      await recovery.authorize();
      const item=await workspaceApi.practiceWorkItem(identity,pending.ticketId);
      if(current!==generation.current || currentRecovery.current!==recovery)return;
      show(item);setCheckedRejected(true);
    } catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }
  async function setAsideRejected() {
    if(!recovery || !rejected || !checkedRejected || busy)return;
    const current=generation.current;setBusy(true);
    try {
      await recovery.journal.persist(ADDRESS,null);
      if(current!==generation.current || currentRecovery.current!==recovery)return;
      setPending(null);setRejected(false);setCheckedRejected(false);setConflict(false);setError("");
    } catch{if(current===generation.current)setRecoveryError(true);}
    finally{if(current===generation.current)setBusy(false);}
  }

  async function save(operation: Pending) {
    if (busy || recoveryBlocked) return;
    const current = generation.current;
    setBusy(true); setPending(operation); setError(""); setRejected(false); setCheckedRejected(false);
    let transmitted=false;
    try {
      const currentItem=items.find(value=>value.ticket_id===operation.ticketId);
      if (currentItem?.work_kind === "vendor_delivery") throw new DraftStoreError("integrity");
      if(currentItem) requirePreparationVersion(operation,currentItem);
      if (authenticated) {
        if (!recovery) throw new DraftStoreError("unavailable");
        await recovery.journal.persist(ADDRESS,{kind:"account-operation",lane:"practice-work",pending:operation});
        if(current!==generation.current || currentRecovery.current!==recovery)return;
      }
      transmitted=true;
      const item = operation.type === "handoff"
        ? await workspaceApi.workHandoff(identity, operation.ticketId, operation.body)
        : await workspaceApi.completeWork(identity, operation.ticketId, operation.body);
      if (current !== generation.current) return;
      if (authenticated) await recovery!.journal.persist(ADDRESS,null);
      if (current!==generation.current || currentRecovery.current!==recovery) return;
      show(item);
      setPending(null); onChanged();
    } catch (cause) { if (current === generation.current) {
      if (!transmitted || cause instanceof DraftStoreError) {
        if (!transmitted && !pending) setPending(null);
        setRecoveryError(true);setError(transmitted ? "The result could not be saved on this device. Recheck recovery before retrying." : "The request was not sent. Recheck device recovery before trying again.");
      } else failure(cause);
    } }
    finally { if (current === generation.current) setBusy(false); }
  }

  const locked = busy || pending !== null || conflict || recoveryBlocked;
  const today=new Date().toLocaleDateString('en-CA');
  const visible=items.filter(item=>pending?.ticketId===item.ticket_id||
    (filter==='all'||filter==='mine'&&item.responsible.id===item.viewer_id||filter==='offers'&&(item.work_kind!=='vendor_delivery'&&!!item.pending_offer)||filter==='overdue'&&item.due_date<today&&!['closed','superseded','withdrawn'].includes(item.state)||filter==='complete'&&(item.work_kind==='vendor_delivery'?item.vendor_work.verification==='verified':item.receipts.some(receipt=>receipt.kind==='human_completion')))&&
    [item.body,item.expected_outcome,item.responsible.name,item.due_date,item.work_kind??'follow-up'].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="practice-work" aria-label="Practice work">
    <div className="practice-work-heading"><div><p className="team-kicker">SHARED RESPONSIBILITY</p><h1>Practice work</h1></div>
      <button disabled={busy || pending !== null} onClick={() => void load()}>Refresh work</button></div>
    <p>Follow through on the work shared with you. An offer stays with its current owner until the recipient accepts.</p>
    {authenticated && !recoveryReady && !recoveryError && <p role="status">Checking private work recovery…</p>}
    {offer && <div className="team-recovery"><p>An unconfirmed practice-work request is saved on this device. Restore it with current access before continuing. Restoration does not send or accept work.</p>
      <button disabled={busy || recoveryError} onClick={()=>void restore()}>Restore practice-work request</button></div>}
    {recoveryError && <div className="team-recovery" role="alert"><p>Device recovery is unavailable. Existing requests are retained.</p>
      <button disabled={busy} onClick={()=>setRecoveryEpoch(value=>value+1)}>Recheck practice-work recovery</button></div>}
    {error && <p role="alert" className="team-note-notice">{error}</p>}
    {pending && !busy && <button className="team-primary" disabled={recoveryBlocked} onClick={() => void save(pending)}>Retry same action</button>}
    {pending && rejected && <div className="team-recovery"><p>The service rejected this request. Check current work before setting it aside; saved history stays intact. An unconfirmed response cannot be set aside here.</p>
      <button disabled={busy || recoveryBlocked} onClick={()=>void inspectRejected()}>Check current work</button>
      {checkedRejected && <button disabled={busy || recoveryBlocked} onClick={()=>void setAsideRejected()}>Set aside rejected request</button>}</div>}
    {!loaded && busy && <p role="status">Loading practice work…</p>}
    {loaded && !items.length && <p>No shared work is available for your account.</p>}
    {loaded&&items.length>0&&<div className="practice-work-filters"><label>Search work<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Task, owner or due date"/></label><label>Show work<select value={filter} onChange={event=>setFilter(event.target.value as typeof filter)}><option value="all">All work</option><option value="mine">Assigned to me</option><option value="offers">Awaiting acceptance</option><option value="overdue">Overdue</option><option value="complete">Result checked</option></select></label></div>}
    {loaded&&items.length>0&&visible.length===0&&<p>No work matches these filters.</p>}
    {visible.map(item => item.work_kind === "vendor_delivery"
      ? <VendorPracticeMount key={item.ticket_id} identity={identity} item={item} people={people} locked={locked} onDenied={failure} onChanged={() => { void load(); onChanged(); }} />
      : <WorkCard key={item.ticket_id} identity={identity} item={item} people={people} locked={locked} onCurrent={show} onDenied={failure} onSave={operation => void save(operation)} />)}
    {cursor && <button disabled={locked} onClick={() => void load(cursor)}>Load more work</button>}
  </section>;
}

function WorkCard({ identity,item, people, locked, onSave,onCurrent,onDenied }: {
  identity:WorkspaceIdentity;item: PracticeWorkItem; people: WorkPerson[]; locked: boolean; onSave: (value: Pending) => void;
  onCurrent:(item:PracticeWorkItem)=>void;onDenied:(cause:unknown)=>void;
}) {
  const [recipient, setRecipient] = useState("");
  const [evidence, setEvidence] = useState("");
  const [checked, setChecked] = useState(false);
  const owner = item.responsible.id === item.viewer_id;
  const offer = item.pending_offer;
  const preparation = item.work_kind === "visit_preparation";
  const ready = preparation && item.ready_for_review === true;
  const active = preparation ? item.state === "approved" : item.state === "sent";
  const open = active && !ready;
  const basisFor=(value:PracticeWorkItem)=>({revisionId:value.revision_id,payloadHash:value.payload_hash,version:value.version,responsibleId:value.responsible.id});
  const [basis,setBasis]=useState(()=>basisFor(item));
  const sameRevision=basis.revisionId===item.revision_id&&basis.payloadHash===item.payload_hash;
  const recorded=sameRevision&&!!evidence&&item.receipts.some(receipt=>receipt.kind===(preparation?"ready_for_review":"human_completion")&&receipt.actor.id===item.viewer_id&&receipt.content===evidence.trim());
  const offered=sameRevision&&!!recipient&&item.pending_offer?.from.id===item.viewer_id&&item.pending_offer.to.id===recipient;
  const retainedEvidence=recorded?"":evidence,retainedRecipient=offered?"":recipient;
  const hasDraft=!!retainedEvidence||!!retainedRecipient;
  const earlier=hasDraft&&(!sameRevision||basis.version!==item.version||basis.responsibleId!==item.responsible.id||!open||!owner);
  const kind=`practice-result:${item.ticket_id}` as const;
  const recovery=useAccountEditorRecovery("mode" in identity,kind,hasDraft?accountEditorDraft(kind,{...basis,evidence:retainedEvidence,recipient:retainedRecipient}):null,locked,onDenied,identity);
  const formLocked=locked||recovery.blocked||earlier;
  useEffect(()=>{if(recorded)setEvidence("");if(offered)setRecipient("");},[recorded,offered]);
  async function restore(draft:AccountEditorDraft,isCurrent:()=>boolean) {
    const data=draft.data;editorData(data,"revisionId,payloadHash,version,responsibleId,evidence,recipient");
    const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
    if(draft.pending!==null||typeof data.revisionId!=="string"||!uuid.test(data.revisionId)||
        typeof data.payloadHash!=="string"||!/^[a-f0-9]{64}$/.test(data.payloadHash)||!Number.isSafeInteger(data.version)||Number(data.version)<1||
        typeof data.responsibleId!=="string"||!uuid.test(data.responsibleId)||typeof data.evidence!=="string"||data.evidence.length>2000||
        typeof data.recipient!=="string"||data.recipient!==""&&!uuid.test(data.recipient))throw new DraftStoreError("integrity");
    const latest=await workspaceApi.practiceWorkItem(identity,item.ticket_id);if(!isCurrent())return;
    onCurrent(latest);setBasis({revisionId:data.revisionId,payloadHash:data.payloadHash,version:Number(data.version),responsibleId:data.responsibleId});
    setEvidence(data.evidence);setRecipient(data.recipient);setChecked(false);
  }
  useUnsavedWork(open && owner && (!!evidence || !offer && !!recipient));
  const overdue = active && new Date(item.due_date + "T23:59:59") < new Date();
  useEffect(() => { setChecked(false); }, [item.version, item.work_kind, item.ready_for_review, recipient]);
  function handoff(kind: WorkHandoffKind) {
    onSave({ type: "handoff", ticketId: item.ticket_id, body: {
      expected_version: item.version, revision_id: item.revision_id, payload_hash: item.payload_hash,
      idempotency_key: crypto.randomUUID(), kind,
      ...(kind === "offer" ? { recipient_id: recipient } : {}),
      ...(["accept", "decline", "recall"].includes(kind) && offer ? { offer_id: offer.id } : {}),
    } });
  }
  const status = preparation
    ? item.state === "closed"
      ? item.receipts.some(receipt=>receipt.kind==="provider_verification") ? "Completed · provider verified" : "Completion unverified"
      : ready ? "Ready for provider review" : open ? "Preparation in progress" : "Preparation unavailable"
    : open ? "Awaiting verified result" : "Completed · human recorded";
  const receiptLabel = (receipt: PracticeWorkItem["receipts"][number]) => ({
    local_delivery: "Local delivery",
    human_completion: "Result checked by " + receipt.actor.name,
    internal_publication: "Shared internally by " + receipt.actor.name,
    ready_for_review: "Ready for review · " + receipt.actor.name,
    provider_verification: "Provider verification · " + receipt.actor.name,
  })[receipt.kind];
  return <article className="team-work-card practice-work-card" aria-label={preparation ? "Shared visit preparation" : "Shared follow-up"}>
    <p className="team-pill">{status}{overdue ? " · Overdue" : ""}</p>
    <h2>{item.body}</h2>
    <p><strong>Expected result:</strong> {item.expected_outcome}</p>
    <p>Responsible: <strong>{owner ? "You" : item.responsible.name}</strong>{!item.responsible.available ? " · Account unavailable" : ""}<br />Due {item.due_date} · Started by {item.originator.name}</p>
    <p className="team-fine">{preparation ? "Shared internally for visit preparation. Provider verification is required before completion." : "Delivery receipt: local synthetic destination."}</p>
    <AccountEditorRecoveryNotice recovery={recovery} label="Practice work form" onRestore={restore}/>
    {earlier&&<div className="team-recovery"><p>This unfinished form belongs to an earlier responsibility or work version. Compare current work before using it.</p>
      {retainedEvidence&&<label>{preparation ? "Earlier preparation evidence" : "Earlier completion evidence"}<textarea readOnly value={retainedEvidence}/></label>}
      {retainedRecipient&&<p>An earlier colleague selection is retained; choose the recipient again if you use this form.</p>}
      {open&&owner&&<button disabled={locked||recovery.blocked} onClick={()=>{setBasis(basisFor(item));setRecipient("");setChecked(false);}}>Use this text for current work</button>}
      <button disabled={locked||recovery.blocked} onClick={()=>{setEvidence("");setRecipient("");setChecked(false);setBasis(basisFor(item));}}>Discard earlier work form</button>
    </div>}
    {offer && <div className="team-note-notice"><p>{offer.from.name} offered this work to {offer.to.name}. {offer.from.name} remains responsible until acceptance.</p>
      {!offer.to.available&&<p>The proposed recipient's account is unavailable.</p>}
      {open && offer.to.id === item.viewer_id && <><label className="team-check"><input type="checkbox" checked={checked} disabled={locked}
        onChange={event => setChecked(event.target.checked)} />I accept responsibility for checking this result.</label>
        <button disabled={locked || !checked} onClick={() => handoff("accept")}>Accept responsibility</button>
        <button disabled={locked} onClick={() => handoff("decline")}>Decline offer</button></>}
      {open && offer.from.id === item.viewer_id && <button disabled={locked} onClick={() => handoff("recall")}>Recall offer</button>}
    </div>}
    {open && owner && !offer && <details><summary>Offer to a colleague</summary>
      <label>Colleague<select disabled={formLocked} value={recipient} onChange={event => {setRecipient(event.target.value);if(!hasDraft)setBasis(basisFor(item));}}>
        <option value="">Choose a colleague</option>{people.filter(person => person.available && person.id !== item.viewer_id)
          .map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <p className="team-fine">You remain responsible until this colleague accepts the shared work.</p>
      <button disabled={formLocked || !people.some(person=>person.id===recipient&&person.available)} onClick={() => handoff("offer")}>Send responsibility offer</button>
    </details>}
    {active && !owner && item.originator.id === item.viewer_id && <details><summary>Take responsibility back</summary>
      <p>You will become responsible again. Any pending offer will close.</p>
      <button disabled={locked} onClick={() => handoff("reclaim")}>Reclaim responsibility</button></details>}
    {open && owner && <details><summary>{preparation ? "Prepare for provider review" : "Record verified result"}</summary>
      <p>{preparation ? "Describe the preparation you completed and any unresolved questions for the provider." : "Record what you checked. Delivery alone does not confirm the expected result."}</p>
      <label>{preparation ? "Preparation evidence" : "Completion evidence"}<textarea rows={3} maxLength={2000} disabled={formLocked} value={evidence}
        onChange={event => { setEvidence(event.target.value); setChecked(false);if(!hasDraft)setBasis(basisFor(item)); }} /></label>
      <label className="team-check"><input type="checkbox" checked={checked} disabled={formLocked}
        onChange={event => setChecked(event.target.checked)} />{preparation ? "I checked this preparation and it is ready for provider review." : "I checked that the expected result occurred."}</label>
      <button disabled={formLocked || !checked || !evidence.trim()} onClick={() => onSave({ type: "complete", ticketId: item.ticket_id,
        body: { ...(preparation ? {expected_version:item.version} : {}), revision_id: item.revision_id, payload_hash: item.payload_hash, idempotency_key: crypto.randomUUID(), evidence } })}>{preparation ? "Mark ready for review" : "Record completion"}</button>
    </details>}
    {item.receipts.map(receipt => <div className="team-follow-up-receipt" key={receipt.id}><strong>{receiptLabel(receipt)}</strong><p>{receipt.content}</p></div>)}
    {!!item.handoffs.length && <details><summary>Responsibility history</summary><ol>{item.handoffs.map(record => <li key={record.id}>
      {record.actor.name} · {({offer: "offered to", accept: "accepted from", decline: "declined an offer from", recall: "recalled an offer to", reclaim: "reclaimed from"})[record.kind]} {record.kind === "offer" || record.kind === "recall" ? record.to.name : record.from.name}
    </li>)}</ol></details>}
  </article>;
}
