import {useEffect, useRef, useState} from "react";
import {EditorRecoveryNotice, editorData, editorDraft, useEditorRecovery} from "./editor-recovery";
import {DraftStoreError} from "./draft-store";
import type {EditorDraft} from "./draft-journal";
import {appointmentRequestKey, validAppointmentBot, validAppointmentRequest, validAppointmentSlot, type AppointmentRequest} from "./appointment-request";
import {useUnsavedWork} from "./unsaved-work";
import {appointmentApi, type AppointmentAction, type AppointmentCatalog, type ExecuteAppointment,
  type AppointmentItem, type CurrentAppointment} from "./appointment-api";
import type {AvailabilityWindow} from "./scheduling-api";
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity, type CaptureBotSelection} from "./workspace-api";

type Pending = AppointmentRequest;
type AppointmentDraft = {bot:CaptureBotSelection;action:AppointmentAction;slot:AvailabilityWindow|null;lastTicket:string|null;pending:Pending|null};
function restoredData(draft:EditorDraft):AppointmentDraft {
  const data=draft.data;editorData(data,"bot,action,slot,lastTicket,pending");
  if(!validAppointmentBot(data.bot)||typeof data.action!=="string"||!["book","reschedule","cancel"].includes(data.action)||
    !(data.slot===null||validAppointmentSlot(data.slot))||
    !(data.lastTicket===null||typeof data.lastTicket==="string"&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(data.lastTicket))||
    !(data.pending===null||validAppointmentRequest(data.pending))||
    draft.pending!==(data.pending?appointmentRequestKey(data.pending):null))throw new DraftStoreError("integrity");
  if(data.pending?.kind==="prepare"&&(JSON.stringify(data.pending.body.bot)!==JSON.stringify(data.bot)||
      data.pending.body.action!==data.action||JSON.stringify(data.pending.body.slot)!==JSON.stringify(data.slot))||
    data.pending&&data.pending.kind!=="prepare"&&data.pending.ticket!==data.lastTicket)throw new DraftStoreError("integrity");
  return data as AppointmentDraft;
}
const when = (value: string) => new Date(value).toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
const title = (action: AppointmentAction) => ({book: "Book another visit", reschedule: "Reschedule linked visit", cancel: "Cancel linked visit"})[action];
const status = (state: AppointmentItem["state"]) => ({pending_approval:"Awaiting review", approved:"Approved", rejected:"Withdrawn", sent:"Appointment saved"})[state];

export function AppointmentPanel({workspaceId, identity, bot, enabled, locked, selectedSlot, selectionExpiresAt, onRefreshSelectedTime, refreshingSelection, selectionRefreshStatus, onAccessLost}: {
  workspaceId: string; identity: AuthenticatedWorkspaceIdentity; bot: CaptureBotSelection;
  enabled: boolean; locked: boolean; selectedSlot: AvailabilityWindow | null;
  selectionExpiresAt?: string;
  onRefreshSelectedTime?: () => void;
  refreshingSelection?: boolean;
  selectionRefreshStatus?: "failed" | "unavailable";
  onAccessLost?: (cause: WorkspaceApiError) => void;
}) {
  const [catalog, setCatalog] = useState<AppointmentCatalog | null>(null);
  const [current, setCurrent] = useState<CurrentAppointment | null>(null);
  const [item, setItem] = useState<AppointmentItem | null>(null);
  const [action, setAction] = useState<AppointmentAction>("book"), [share, setShare] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null), [busy, setBusy] = useState(false);
  const [earlier,setEarlier]=useState<AppointmentDraft|null>(null),[needsSelection,setNeedsSelection]=useState(false);
  const [rejected,setRejected]=useState(false),[checkedRejected,setCheckedRejected]=useState(false);
  const data:AppointmentDraft={bot:{...bot},action,slot:action==="cancel"?null:selectedSlot,lastTicket:item?.ticket_id??null,pending};
  const recovery=useEditorRecovery(workspaceId,"appointments",
    pending?editorDraft(workspaceId,"appointments",earlier??data,appointmentRequestKey(pending)):
    earlier?editorDraft(workspaceId,"appointments",earlier):
    null,
    busy||pending!==null,{required:true,scopeKey:`${bot.address}:${bot.team_revision}`,identity});
  useUnsavedWork(pending !== null || earlier!==null || !item && share);
  const [message, setMessage] = useState(""), [now, setNow] = useState(Date.now);
  const selectionExpired = selectionExpiresAt !== undefined && !(Date.now() < Date.parse(selectionExpiresAt));
  const selectionStatus = selectionRefreshStatus ?? (selectionExpired ? "expired" : "checked");
  const generation = useRef(0), active = useRef<AbortController | null>(null);
  const unavailable = (cause: unknown) => {
    if (cause instanceof WorkspaceApiError && [401, 403].includes(cause.status)) {
      recovery.suspend();
      setCatalog(null); setCurrent(null); setItem(null); setPending(null); setEarlier(null); setShare(false);
      onAccessLost?.(cause);
      setMessage("Appointment access is unavailable.");
    } else if (cause instanceof WorkspaceApiError && [400, 409, 422].includes(cause.status)) {
      setRejected(true);setCheckedRejected(false);
      setMessage("The request was rejected because the appointment or its permissions changed. Check current details before setting this request aside.");
    } else if(cause instanceof DraftStoreError) {
      setMessage("The appointment request could not be saved on this device. Recheck recovery before continuing.");
    } else {
      setRejected(false);setCheckedRejected(false);
      setMessage("The request could not be confirmed. Retry the same save if one is pending, or refresh the saved proposals.");
    }
  };
  useEffect(() => {
    const version = ++generation.current;
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setCatalog(null); setCurrent(null); setItem(null); setPending(null); setBusy(true);
    setAction("book"); setShare(false); setEarlier(null);setNeedsSelection(false);setRejected(false);setCheckedRejected(false);setMessage("");
    void appointmentApi.catalog(workspaceId, identity, undefined, controller.signal).then(result => {
      if (version === generation.current && !controller.signal.aborted) setCatalog(result);
    }).catch(cause => {if (version === generation.current && !controller.signal.aborted) unavailable(cause);})
      .finally(() => {if (version === generation.current && !controller.signal.aborted) setBusy(false);});
    return () => {generation.current++; active.current?.abort();};
  }, [workspaceId, identity, bot.address, bot.team_revision]);
  useEffect(()=>{
    setShare(false);setNeedsSelection(!selectedSlot);
    if(selectedSlot)setEarlier(old=>old?.pending?old:{...(old??data),slot:selectedSlot});
  },[selectedSlot]);
  useEffect(() => {if (selectionExpired && action !== "cancel") setShare(false);}, [selectionExpired, action]);
  useEffect(() => {if (refreshingSelection || selectionRefreshStatus) setShare(false);}, [refreshingSelection, selectionRefreshStatus]);
  useEffect(() => {
    setNow(Date.now());
    if (!item) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(1, Date.parse(item.intent.expires_at) - Date.now() + 1));
    return () => clearTimeout(timer);
  }, [item]);
  const disabled = locked || busy || refreshingSelection || pending !== null || recovery.blocked;
  async function read(kind: "catalog" | "current" | "item", ticket?: string, more = false) {
    if (disabled || (kind === "current" && !enabled)) return;
    const version = generation.current, controller = new AbortController(); active.current = controller;
    setBusy(true); setMessage("");
    try {
      if (kind === "catalog") {
        const result = await appointmentApi.catalog(workspaceId, identity, more ? catalog?.next_cursor ?? undefined : undefined, controller.signal);
        if (version === generation.current && !controller.signal.aborted) {
          if (more && catalog?.items.some(old => result.items.some(next => next.ticket_id === old.ticket_id))) throw new WorkspaceApiError(503);
          setCatalog(more && catalog ? {...result, items: [...catalog.items, ...result.items]} : result);
        }
      } else if (kind === "current") {
        const result = await appointmentApi.current(workspaceId, identity, bot, controller.signal);
        if (version === generation.current && !controller.signal.aborted) {setCurrent(result);setShare(false);}
      } else if (ticket) {
        const result = await appointmentApi.read(workspaceId, identity, ticket, controller.signal);
        if (version === generation.current && !controller.signal.aborted) {
          setItem(result);
          setCatalog(old => old && {...old, items: old.items.map(saved => saved.ticket_id === result.ticket_id ? {...saved, state: result.state} : saved)});
        }
      }
    } catch (cause) {if (version === generation.current && !controller.signal.aborted) unavailable(cause);}
    finally {if (version === generation.current && !controller.signal.aborted) setBusy(false);}
  }
  async function save(command: Pending) {
    if (busy || locked || recovery.blocked) return;
    const version = generation.current, controller = new AbortController(); active.current = controller;
    const submitted:AppointmentDraft=command.kind==="prepare"?{bot:{...command.body.bot},action:command.body.action,
      slot:command.body.slot,lastTicket:item?.ticket_id??null,pending:command}:
      {...(earlier??data),action:item?.intent.action??action,slot:item?.intent.slot??null,
        lastTicket:command.ticket,pending:command};
    setPending(command);setEarlier(submitted);setBusy(true);setMessage("");setRejected(false);setCheckedRejected(false);
    try {
      await recovery.commit(editorDraft(workspaceId,"appointments",submitted,appointmentRequestKey(command)));
      if(version!==generation.current||controller.signal.aborted)return;
      const result = command.kind === "prepare"
        ? await appointmentApi.prepare(workspaceId, identity, command.body, controller.signal)
        : command.kind === "decide" ? await appointmentApi.decide(workspaceId, identity, command.ticket, command.body, controller.signal)
        : await appointmentApi.execute(workspaceId, identity, command.ticket, command.body, controller.signal);
      if (version !== generation.current || controller.signal.aborted) return;
      await recovery.commit(null);
      if(version!==generation.current||controller.signal.aborted)return;
      setItem(result);setPending(null);setEarlier(null);setShare(false);setNeedsSelection(false);
      setMessage(command.kind === "prepare" ? "Proposal saved. Review the exact appointment below." :
        result.state === "rejected" ? "Proposal withdrawn." : result.state === "sent" ? "Scheduling saved the appointment change." :
        result.dispatch_started ? "The existing operation is retained. Its appointment result is not yet confirmed." :
        "Approval saved. Send the approved change when you are ready.");
      const appointment = result.intent.slot ?? result.intent.expected!;
      setCatalog(old => ({workspace_id: workspaceId, next_cursor: old?.next_cursor ?? null,
        items: [{ticket_id: result.ticket_id, state: result.state, action: result.intent.action,
          appointment_window: {starts_at: appointment.starts_at, ends_at: appointment.ends_at}, expires_at: result.intent.expires_at},
          ...(old?.items ?? []).filter(value => value.ticket_id !== result.ticket_id)]}));
    } catch (cause) {if (version === generation.current && !controller.signal.aborted) unavailable(cause);}
    finally {if (version === generation.current && !controller.signal.aborted) setBusy(false);}
  }
  async function restore(draft:EditorDraft,_workspace:unknown,isCurrent:()=>boolean) {
    const saved=restoredData(draft),version=generation.current;
    const freshCatalog=await appointmentApi.catalog(workspaceId,identity);
    if(version!==generation.current||!isCurrent())return;
    const freshItem=saved.lastTicket?await appointmentApi.read(workspaceId,identity,saved.lastTicket):null;
    if(version!==generation.current||!isCurrent())return;
    setCatalog(freshCatalog);setItem(freshItem);setCurrent(null);setAction(saved.action);setShare(false);
    setPending(saved.pending);setEarlier(saved);setNeedsSelection(true);setRejected(false);setCheckedRejected(false);
    setMessage(saved.pending?"The earlier request is retained exactly. Review its details and retry only that request.":
      "Earlier appointment choices are retained. Refresh the linked visit or availability and choose again before sharing a new proposal.");
  }
  async function checkRejected() {
    if(!pending||!rejected||busy||locked||recovery.blocked||!recovery.access)return;
    const version=generation.current,controller=new AbortController();active.current=controller;setBusy(true);setCheckedRejected(false);
    try {
      await recovery.access.authorize();
      if(version!==generation.current||controller.signal.aborted)return;
      const freshCatalog=await appointmentApi.catalog(workspaceId,identity,undefined,controller.signal);
      const freshItem=pending.kind!=="prepare"?await appointmentApi.read(workspaceId,identity,pending.ticket,controller.signal):null;
      if(version!==generation.current||controller.signal.aborted)return;
      setCatalog(freshCatalog);if(freshItem)setItem(freshItem);setCheckedRejected(true);
    }catch(cause){if(version===generation.current&&!controller.signal.aborted)unavailable(cause);}
    finally{if(version===generation.current&&!controller.signal.aborted)setBusy(false);}
  }
  async function setAside() {
    if(!pending||!checkedRejected||busy||locked||recovery.blocked)return;
    const version=generation.current;setBusy(true);
    try{await recovery.commit(null);if(version!==generation.current)return;
      setPending(null);setEarlier(null);setShare(false);setAction("book");setNeedsSelection(true);setRejected(false);setCheckedRejected(false);
      setMessage("Rejected request set aside on this device. This does not cancel an existing operation. Check any unconfirmed operation before preparing another proposal.");
    }catch(cause){if(version===generation.current)unavailable(cause);}
    finally{if(version===generation.current)setBusy(false);}
  }
  async function discardChoices() {
    if(pending||busy||locked||recovery.blocked)return;
    const version=generation.current;setBusy(true);
    try{await recovery.commit(null);if(version!==generation.current)return;
      setEarlier(null);setAction("book");setShare(false);setNeedsSelection(true);
    }catch(cause){if(version===generation.current)unavailable(cause);}
    finally{if(version===generation.current)setBusy(false);}
  }
  const linked = current?.appointment;
  const canChange = linked && ["booked", "confirmed"].includes(linked.status);
  const pendingExecution = pending?.kind === "execute";
  const unconfirmed = item?.dispatch_started && !item.appointment_saved;
  const canPrepare = enabled && !unconfirmed && share && (action === "book" || canChange) && (action === "cancel" || selectedSlot&&!needsSelection&&!selectionExpired&&!selectionRefreshStatus);
  const choose = (choice: "approve" | "reject") => item && void save({kind: "decide", ticket: item.ticket_id,
    body: {revision_id: item.revision_id, payload_hash: item.payload_hash, choice}});
  const execute = (mode: ExecuteAppointment["mode"]) => item?.operation_id && void save({kind:"execute",ticket:item.ticket_id,
    body:{operation_id:item.operation_id,revision_id:item.revision_id,payload_hash:item.payload_hash,mode}});
  return <section className="team-prep appointment-panel" aria-label="Appointments">
    <h3>Appointments</h3>
    <EditorRecoveryNotice recovery={recovery} label="Appointment" onRestore={restore}/>
    {earlier&&!recovery.blocked&&<div className="team-recovery">
      <p>Retained choice: {title(earlier.action)}{earlier.slot?` · ${when(earlier.slot.starts_at)}`:""}.</p>
      {earlier.bot.address!==bot.address||earlier.bot.team_revision!==bot.team_revision?<p>This request belongs to an earlier bot selection. Retrying preserves its original details.</p>:null}
      {pending?.kind==="decide"&&<p>Unconfirmed decision: {pending.body.choice==="approve"?"approve this appointment change":"withdraw this proposal"}.</p>}
      {pending?.kind==="execute"&&<p>Unconfirmed request: {pending.body.mode==="submit"?"send the approved change":
        pending.body.mode==="reconcile"?"check its saved result":"retry the same appointment change"}. Recovering keeps the same operation and approved details.</p>}
      {pending?.kind==="execute"&&pending.body.mode==="retry"&&<p>Recovering this retry may submit the same operation again. It cannot create a new operation.</p>}
      {!pending&&<><p>Retained choices do not reserve a time. Refresh availability before sharing a recovered proposal.</p>
        <button disabled={busy||locked} onClick={()=>void discardChoices()}>Discard retained appointment choices</button></>}
    </div>}
    <div className="capture-actions">
      <button disabled={disabled || !enabled} onClick={() => void read("current")}>Refresh linked visit</button>
      <button disabled={disabled} onClick={() => void read("catalog")}>Refresh saved proposals</button>
    </div>
    {current && <p>{linked ? `Linked visit: ${when(linked.starts_at)} · ${linked.status}.` : "No Scheduling appointment is linked to this encounter."}</p>}
    <label>Appointment action<select value={action} disabled={disabled || !enabled}
      onChange={event => {setAction(event.target.value as AppointmentAction);setShare(false);
        setEarlier(old=>({...data,...old,action:event.target.value as AppointmentAction,slot:event.target.value==="cancel"?null:old?.slot??selectedSlot}));}}>
      <option value="book">Book another visit</option>
      <option value="reschedule" disabled={!canChange}>Reschedule linked visit</option>
      <option value="cancel" disabled={!canChange}>Cancel linked visit</option>
    </select></label>
    {action !== "cancel" && <div className="capture-actions"><p>{selectedSlot ? `Selected time: ${when(selectedSlot.starts_at)} – ${new Date(selectedSlot.ends_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}.` :
      "Choose a time from the checked availability above."}</p>
      {onRefreshSelectedTime && <button disabled={disabled || !enabled || !selectedSlot} aria-busy={refreshingSelection || undefined}
        onClick={() => {if (disabled || !enabled || !selectedSlot) return; setShare(false); onRefreshSelectedTime();}}>Refresh this time</button>}
    </div>}
    {action !== "cancel" && (selectedSlot || selectionRefreshStatus) && selectionExpiresAt !== undefined && <p role="status" style={{display: "grid"}}>
      <span style={{gridArea: "1 / 1", visibility: selectionStatus === "checked" ? "visible" : "hidden"}} aria-hidden={selectionStatus !== "checked"}>This time has been checked; it is not reserved.</span>
      <span style={{gridArea: "1 / 1", visibility: selectionStatus === "expired" ? "visible" : "hidden"}} aria-hidden={selectionStatus !== "expired"}>This check expired. Refresh availability before preparing.</span>
      {onRefreshSelectedTime && <>
        <span style={{gridArea: "1 / 1", visibility: selectionStatus === "failed" ? "visible" : "hidden"}} aria-hidden={selectionStatus !== "failed"}>This time could not be confirmed. Your choice is retained; refresh it before preparing.</span>
        <span style={{gridArea: "1 / 1", visibility: selectionStatus === "unavailable" ? "visible" : "hidden"}} aria-hidden={selectionStatus !== "unavailable"}>This time is no longer available. Your retained choice is kept; choose another checked time.</span>
      </>}
    </p>}
    <label className="appointment-consent"><input type="checkbox" checked={share} disabled={disabled || !enabled}
      onChange={event => setShare(event.target.checked)} /> Share this appointment proposal with the practice work queue.</label>
    <button disabled={disabled || !canPrepare} onClick={() => {
      if (action !== "cancel" && (selectionRefreshStatus || selectionExpiresAt !== undefined && !(Date.now() < Date.parse(selectionExpiresAt)))) return;
      void save({kind: "prepare", body: {
      bot: {...bot}, action, slot: action === "cancel" ? null : selectedSlot,
      share: true, idempotency_key: crypto.randomUUID()}});
    }}>Prepare appointment proposal</button>
    {unconfirmed&&<p>Check the existing operation below before preparing another appointment change.</p>}
    {message && <p role="status">{message}</p>}
    {pending && !busy && <div className="capture-actions">
      <button disabled={locked||recovery.blocked} onClick={() => void save(pending)}>{pending.kind==="execute"?"Recover the same request":"Retry the same save"}</button>
      {rejected&&<button disabled={locked||recovery.blocked} onClick={()=>void checkRejected()}>Check rejected appointment request</button>}
      {checkedRejected&&<button disabled={locked||recovery.blocked} onClick={()=>void setAside()}>Set aside rejected appointment request</button>}
    </div>}
    {item && <article className="team-follow-up">
      <h4>{title(item.intent.action)}</h4>
      {item.intent.expected && <p>Current appointment: {when(item.intent.expected.starts_at)} – {new Date(item.intent.expected.ends_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}.</p>}
      {item.intent.slot && <p>Requested appointment: {when(item.intent.slot.starts_at)} – {new Date(item.intent.slot.ends_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}.</p>}
      <p>{pendingExecution ? `Last known proposal status: ${status(item.state)}. The retained request is unconfirmed.` :
        item.state === "pending_approval" ? "Awaiting your review." : item.state === "sent" ? "Scheduling saved this appointment change." :
        item.state === "rejected" ? "Withdrawn." : item.operation_status === "unknown" ? "The appointment result is unconfirmed." :
        item.dispatch_started ? "Scheduling is processing this appointment change. No saved appointment is confirmed yet." : "Approved. Send the approved change to Scheduling when you are ready."}</p>
      {item.result && <p>Calendar: {item.calendar_state === "synced" ? "synchronized" : item.calendar_state === "pending" ? "synchronization pending" :
        item.calendar_state === "failed" ? "synchronization failed" : "disconnected"}. Last verified {when(item.result.observed_at)}.</p>}
      {item.execution_error === "appointment_outcome_unconfirmed" && <p role="status">The latest check could not be confirmed. A saved receipt, if shown, remains the last verified result. Check the existing operation before attempting another change.</p>}
      <p className="team-fine">An appointment change is confirmed only after Scheduling reports it saved. Calendar synchronization and visit completion are separate results.</p>
      {item.state === "pending_approval" && <p>{Date.parse(item.intent.expires_at) <= now ? "This proposal expired. Withdraw it and prepare a fresh proposal." :
        `Review before ${new Date(item.intent.expires_at).toLocaleTimeString()}.`}</p>}
      {item.state==="approved"&&<p>{pendingExecution?
        Date.parse(item.intent.expires_at)<=now?"Approval expired while this request was unconfirmed. Recover the same request first; expiry does not show whether Scheduling received it.":
          "Recover the same request before taking another appointment action.":Date.parse(item.intent.expires_at)<=now?
        item.dispatch_started?"Approval expired. You can still check the existing operation; a new submission is unavailable.":
          "Approval expired before sending. Withdraw this proposal before preparing a fresh one.":
        item.dispatch_started?"Check the saved result first. If a retry is needed, it sends the same operation and approved details.":
          "Sending is a separate action from approval. It submits only the change shown here."}</p>}
      <div className="capture-actions">
        <button disabled={disabled} onClick={() => void read("item", item.ticket_id)}>Refresh saved proposal</button>
        {item.operation_id&&item.dispatch_started&&<button disabled={disabled||!enabled} onClick={()=>execute("reconcile")}>Check saved result</button>}
        {item.state==="approved"&&!item.dispatch_started&&<button disabled={disabled||!enabled||Date.parse(item.intent.expires_at)<=now}
          onClick={()=>execute("submit")}>Send approved appointment change</button>}
        {item.state==="approved"&&item.dispatch_started&&<button disabled={disabled||!enabled||Date.parse(item.intent.expires_at)<=now}
          onClick={()=>execute("retry")}>Retry the same appointment change</button>}
        {item.state === "pending_approval" && <button disabled={disabled || !enabled || Date.parse(item.intent.expires_at) <= now}
          onClick={() => choose("approve")}>Approve this appointment change</button>}
        {item.state !== "rejected" && !item.dispatch_started && !pendingExecution && <button disabled={disabled} onClick={() => choose("reject")}>Withdraw proposal</button>}
      </div>
    </article>}
    {catalog && <details><summary>Saved appointment proposals ({catalog.items.length}{catalog.next_cursor ? "+" : ""})</summary>
      {!catalog.items.length ? <p>No saved appointment proposals.</p> : <ul>{catalog.items.map(saved => <li key={saved.ticket_id}>
        <button disabled={disabled} onClick={() => void read("item", saved.ticket_id)}>{title(saved.action)} · {when(saved.appointment_window.starts_at)} · {status(saved.state)}</button>
      </li>)}</ul>}
      {catalog.next_cursor && <button disabled={disabled} onClick={() => void read("catalog", undefined, true)}>Show more proposals</button>}
    </details>}
  </section>;
}
