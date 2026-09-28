import { useEffect, useRef, useState } from "react";
import { useUnsavedWork } from "./unsaved-work";
import { EditorRecoveryNotice, editorData, editorDraft, useEditorRecovery } from "./editor-recovery";
import { DraftStoreError } from "./draft-store";
import type { FollowUp, FollowUpOperation, Workspace } from "./workspace-api";
import { hostedWorkspaceRequested } from "./hosted-workspace";

function isoDate(value: string) {
  const parts = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
  if (!parts) return null;
  const [, month, day, year] = parts;
  const parsed = new Date(Number(year), Number(month) - 1, Number(day));
  return Number(year) >= 2000 && parsed.getFullYear() === Number(year) && parsed.getMonth() === Number(month) - 1 && parsed.getDate() === Number(day)
    ? `${year}-${month}-${day}` : null;
}

function relativeDate(days: number) {
  const date = new Date(); date.setDate(date.getDate() + days);
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}/${date.getFullYear()}`;
}

export function FollowUpWork({ workspace, locked: parentLocked, onSave, onReview }: {
  workspace: Workspace; locked: boolean; onSave: (operation: FollowUpOperation) => void; onReview: () => void;
}) {
  const rehearsal = !hostedWorkspaceRequested();
  const note = workspace.note?.latest;
  const [body, setBody] = useState("");
  const [due, setDue] = useState("");
  const [outcome, setOutcome] = useState("");
  const [share, setShare] = useState(false);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const sending = useRef(false);
  const [baseNoteId, setBaseNoteId] = useState(note?.id ?? null);
  const hasText = !!body || !!due || !!outcome;
  const recovery = useEditorRecovery(workspace.id, "follow-up-proposal", hasText ? editorDraft(workspace.id, "follow-up-proposal",
    {body, due, outcome, baseNoteId, submitted}) : null, parentLocked || submitting);
  const locked = parentLocked || recovery.blocked || submitting;
  const changedNote = hasText && baseNoteId !== (note?.id ?? null);
  useUnsavedWork(!!body || !!due || !!outcome);
  const dueDate = isoDate(due);
  const saved = workspace.follow_ups?.some(item => item.create_key === submitted);
  useEffect(() => {
    if (saved) {
      setBody(""); setDue(""); setOutcome(""); setShare(false); setSubmitted(null);
    }
  }, [saved]);
  useEffect(() => { setShare(false); }, [note?.id, note?.sources_changed]);
  useEffect(() => { if (!hasText) setBaseNoteId(note?.id ?? null); }, [hasText, note?.id]);
  async function propose() {
    if (!rehearsal || locked || sending.current || changedNote || !note?.review || note.sources_changed || !share || !body.trim() || !outcome.trim() || !dueDate) return;
    sending.current = true; setSubmitting(true);
    const key = crypto.randomUUID(); setSubmitted(key);
    try {
      // Retain the link to this submission before the parent journals and sends
      // the exact request. A recovered form can then recognize its saved work.
      await recovery.commit(editorDraft(workspace.id, "follow-up-proposal", {body,due,outcome,baseNoteId,submitted:key}));
      onSave({type:"followUpPropose",body:{expected_revision:workspace.revision,idempotency_key:key,
        note_id:note.id,body,due_date:dueDate,expected_outcome:outcome,share:true}});
    } catch { /* The recovery notice retains the failure; no request was sent. */ }
    finally { sending.current=false; setSubmitting(false); }
  }
  return <section aria-label="Encounter follow-ups" className="team-follow-ups">
    <h2>Follow-ups</h2>
    <p className="team-fine">{rehearsal
      ? "Turn a reviewed plan into work with an owner, due date and result. Delivery currently runs only in the local synthetic rehearsal."
      : "Use Messages and referrals below to prepare a follow-up from your reviewed note, choose a connected recipient, and review and approve delivery."}</p>
    <EditorRecoveryNotice recovery={recovery} label="Follow-up proposal" onRestore={async draft => {
      const data = draft.data; editorData(data, "body,due,outcome,baseNoteId,submitted");
      if (draft.pending !== null || typeof data.body !== "string" || data.body.length > 4000 ||
          typeof data.due !== "string" || data.due.length > 10 || typeof data.outcome !== "string" || data.outcome.length > 500 ||
          data.baseNoteId !== null && (typeof data.baseNoteId !== "string" || !data.baseNoteId || data.baseNoteId.length > 200) ||
          data.submitted !== null && (typeof data.submitted !== "string" || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(data.submitted))) throw new DraftStoreError("integrity");
      setBody(data.body); setDue(data.due); setOutcome(data.outcome); setBaseNoteId(data.baseNoteId as string | null);
      setShare(false); setSubmitted(data.submitted as string | null);
    }} />
    {hasText && (!rehearsal || changedNote || !note?.review || note.sources_changed) && <aside className="team-note-notice"><p>{rehearsal
      ? "Your follow-up text belongs to an earlier note or source snapshot. Compare it with the current reviewed plan before sharing."
      : "Your earlier rehearsal draft is retained. You can copy the text into Messages and referrals and review it for the current note and recipient."}</p>
      <label>Earlier follow-up message<textarea readOnly value={body} /></label>
      <p>Due date: {due || "Not entered"} · Expected result: {outcome || "Not entered"}</p>
      {rehearsal ? <button disabled={locked || !note?.review || note.sources_changed} onClick={() => { setBaseNoteId(note!.id); setShare(false); }}>Use this text with the current reviewed note</button>
        : <button disabled={locked} onClick={() => void recovery.commit(null).then(() => {
          setBody(""); setDue(""); setOutcome(""); setShare(false); setSubmitted(null);
        }).catch(() => {})}>Discard rehearsal draft</button>}
    </aside>}
    {rehearsal && (!note?.review || note.sources_changed ? <p>Review the current note and its sources before proposing work. <button className="team-subtle" onClick={onReview}>Open note review</button></p> :
      <details className="team-follow-up-create"><summary>Propose a follow-up</summary>
        <form onSubmit={e => { e.preventDefault(); void propose(); }}>
          <p className="team-fine">Based on reviewed note version {note.version}. Owner: you. Target: {workspace.label} · local synthetic destination.</p>
          {note.core_source && <p className="team-fine">The saved Core note and recording must still match this reviewed version before the proposal is accepted.</p>}
          <label>Follow-up message<textarea rows={4} maxLength={4000} disabled={locked} value={body} onChange={e => { setBody(e.target.value); setShare(false); setSubmitted(null); }} /></label>
          <label>Due date<input type="text" inputMode="numeric" placeholder="MM/DD/YYYY" maxLength={10}
            aria-describedby="follow-up-date-hint" aria-invalid={!!due && !dueDate} required disabled={locked} value={due}
            onChange={e => { setDue(e.target.value); setShare(false); setSubmitted(null); }} /></label>
          <p id="follow-up-date-hint" className="team-fine">{due && !dueDate ? "Enter a valid date as MM/DD/YYYY." : "MM/DD/YYYY · your local calendar date"}</p>
          <div className="team-follow-up-date-options"><button type="button" disabled={locked} onClick={() => { setDue(relativeDate(1)); setShare(false); setSubmitted(null); }}>Tomorrow</button>
            <button type="button" disabled={locked} onClick={() => { setDue(relativeDate(7)); setShare(false); setSubmitted(null); }}>In one week</button></div>
          <label>Expected result<textarea rows={2} maxLength={500} disabled={locked} value={outcome} onChange={e => { setOutcome(e.target.value); setShare(false); setSubmitted(null); }} /></label>
          <label className="team-check"><input type="checkbox" disabled={locked || changedNote} checked={share} onChange={e => setShare(e.target.checked)} />Share this message, due date and expected result with the practice work record.</label>
          <p className="team-fine">Your private note stays private. Saving a proposal does not authorize delivery.</p>
          <button className="team-primary" disabled={locked || changedNote || !share || !body.trim() || !outcome.trim() || !dueDate}>Save follow-up proposal</button>
        </form>
      </details>)}
    {workspace.follow_ups?.map(item => <FollowUpCard key={item.ticket_id} item={item} workspaceId={workspace.id} label={workspace.label} locked={locked} readOnly={!rehearsal} onSave={onSave} />)}
  </section>;
}

function FollowUpCard({ item, workspaceId, label, locked: parentLocked, readOnly, onSave }: {
  item: FollowUp; workspaceId: string; label: string; locked: boolean; readOnly: boolean; onSave: (operation: FollowUpOperation) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [resultChecked, setResultChecked] = useState(false);
  const [base, setBase] = useState({revisionId: item.revision_id, payloadHash: item.payload_hash});
  const editor = `follow-up-result:${item.ticket_id}` as const;
  const recovery = useEditorRecovery(workspaceId, editor, evidence ? editorDraft(workspaceId, editor, {evidence, ...base}) : null, parentLocked);
  const locked = parentLocked || recovery.blocked;
  const changedWork = base.revisionId !== item.revision_id || base.payloadHash !== item.payload_hash;
  useEffect(() => { setConfirmed(false); }, [item.payload_hash, item.state, item.source_changed]);
  useEffect(() => { setResultChecked(false); }, [item.revision_id, item.payload_hash, item.state, item.responsible_id]);
  useEffect(() => { if (!evidence) setBase({revisionId:item.revision_id,payloadHash:item.payload_hash}); }, [evidence,item.revision_id,item.payload_hash]);
  useEffect(() => {
    if (evidence && !changedWork && item.state === "closed" && item.receipts.some(receipt =>
      receipt.kind === "human_completion" && receipt.actor_id === item.owner_id && receipt.content === evidence)) {
      setEvidence(""); setResultChecked(false);
    }
  }, [evidence, changedWork, item.state, item.receipts, item.owner_id]);
  const awaiting = ["pending_approval", "approved"].includes(item.state);
  const responsible = !item.responsible_id || item.responsible_id === item.owner_id;
  useUnsavedWork(!!evidence);
  const status = item.state === "closed" ? "Completed · human recorded" : item.state === "sent" ? "Local delivery recorded" :
    item.state === "rejected" ? "Dismissed" : item.source_changed ? "Source changed" : item.state === "approved" ? "Approved · delivery pending" : "Awaiting your approval";
  const dateParts = item.due_date.split("-").map(Number);
  const dueDate = new Date(dateParts[0], dateParts[1] - 1, dateParts[2], 23, 59, 59);
  const overdue = !["closed", "rejected"].includes(item.state) && dueDate < new Date();
  const decision = (choice: "approve" | "reject") => onSave({ type: "followUpDecision", ticketId: item.ticket_id,
    body: { revision_id: item.revision_id, payload_hash: item.payload_hash, choice } });
  return <article className="team-work-card team-follow-up-card" aria-label="Follow-up proposal">
    <span className="team-kicker">FOLLOW-UP · NOTE VERSION {item.note_version}</span>
    {readOnly && <p className="team-fine">Saved read-only rehearsal record. Connected delivery is tracked separately in Messages and referrals.</p>}
    <p className="team-pill">{status}</p>
    <p className="team-follow-up-body">{item.body}</p>
    <p><strong>Expected result:</strong> {item.expected_outcome}</p>
    <EditorRecoveryNotice recovery={recovery} label="Follow-up result" onRestore={async draft => {
      const data = draft.data; editorData(data, "evidence,revisionId,payloadHash");
      if (draft.pending !== null || typeof data.evidence !== "string" || data.evidence.length > 2000 ||
          typeof data.revisionId !== "string" || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(data.revisionId) ||
          typeof data.payloadHash !== "string" || !/^[a-f0-9]{64}$/.test(data.payloadHash)) throw new DraftStoreError("integrity");
      setEvidence(data.evidence); setBase({revisionId:data.revisionId,payloadHash:data.payloadHash});
      setResultChecked(false); setConfirmed(false);
    }} />
    {evidence && (readOnly || changedWork || item.state !== "sent" || !responsible) && <aside className="team-note-notice">
      <p>{readOnly ? "Your rehearsal result draft is retained for reference. It has not completed connected delivery work."
        : "Your earlier result text is retained. The work revision, status or responsibility differs; this text has not completed the current work."}</p>
      <label>Earlier completion evidence<textarea readOnly value={evidence} /></label>
      {!readOnly && item.state === "sent" && responsible && <button disabled={locked} onClick={() => {
        setBase({revisionId:item.revision_id,payloadHash:item.payload_hash}); setResultChecked(false);
      }}>Use this text for the current result</button>}
      <button disabled={locked} onClick={() => void recovery.commit(null).then(() => {setEvidence("");setResultChecked(false);}).catch(() => {})}>Discard earlier result draft</button>
    </aside>}
    <p className="team-fine">Responsible: {responsible ? "you" : "a practice colleague · see Practice work"} · Due {dueDate.toLocaleDateString()}{overdue ? " · Overdue" : ""}<br />Target: {label} · local synthetic destination</p>
    {item.source_changed && <p className="team-note-notice">The source note or evidence changed. {awaiting && !readOnly ? "Dismiss this proposal and create a new one from the current reviewed note." : "This record keeps the earlier note version as its source."}</p>}
    {awaiting && !readOnly && <div className="team-follow-up-actions">
      {item.core_check_required && <p className="team-fine">Core will be checked again before approval and local delivery. Changed or unavailable notes leave delivery pending.</p>}
      {!item.source_changed && <><label className="team-check"><input type="checkbox" disabled={locked} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I approve this exact message, target, owner, due date and expected result for local rehearsal.</label>
        <button className="team-primary" disabled={locked || !confirmed} onClick={() => decision("approve")}>{item.state === "approved" ? "Resume local delivery" : "Approve local delivery"}</button></>}
      <button disabled={locked} onClick={() => decision("reject")}>Dismiss proposal</button>
    </div>}
    {item.receipts.map(receipt => <div className="team-follow-up-receipt" key={receipt.id}>
      <strong>{receipt.kind === "local_delivery" ? "Local delivery receipt" : receipt.actor_id === item.owner_id ? "Result recorded by you" : "Result recorded by your colleague"}</strong>
      <p>{receipt.content}</p><small>{new Date(receipt.created_at).toLocaleString()}</small>
    </div>)}
    {!readOnly && item.state === "sent" && responsible && <details><summary>Record the result</summary>
      <p className="team-fine">Local delivery does not prove that the intended result occurred. Record the evidence you checked. This result joins the shared work record.</p>
      <label>Completion evidence<textarea disabled={locked} rows={3} maxLength={2000} value={evidence} onChange={e => { setEvidence(e.target.value); setResultChecked(false); }} /></label>
      <label className="team-check"><input type="checkbox" disabled={locked || changedWork} checked={resultChecked} onChange={e => setResultChecked(e.target.checked)} />I checked that the expected result occurred.</label>
      <button disabled={locked || changedWork || !resultChecked || !evidence.trim()} onClick={() => onSave({ type: "followUpComplete", ticketId: item.ticket_id,
        body: { revision_id: item.revision_id, payload_hash: item.payload_hash, idempotency_key: crypto.randomUUID(), evidence } })}>Record completion</button>
    </details>}
  </article>;
}
