"""Reviewed note → F-8 proposal → exact approval → local delivery → human result.

The synthetic effect and its receipt commit together in Postgres. There is no
network sender, inferred patient acceptance, or independent feature queue.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.application import core_note_review
from cosmas_os.application import note_review as notes
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    ActionRevision,
    AuditEvent,
    Decision,
    FollowUpReceipt,
    FollowUpSource,
    Operation,
    Ticket,
    WorkspaceNote,
    WorkspaceNoteReview,
)
from cosmas_os.ports.core_notes import CoreDraftReceipt

LANE = "encounter_follow_up"
ACTION = "follow_up.synthetic_delivery"
ADAPTER = "workspace_synthetic"


def _local(s):
    url = s.get_bind().engine.url
    if (not settings.workspace_available or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith("w1a_")):
        raise ws.WorkspaceError("follow_up_connection_required", 403)


def _response(s, w):
    return {"entry_revision": w.revision, "workspace": ws.read(s, w.box_id, w.owner_id, w.id)}


def _current(s, w, note_id, core_checked: CoreDraftReceipt | None = None):
    n = notes._latest(s, w.id)
    if (not n or n.id != note_id or n.source_fingerprint != notes.source_fingerprint(s, w.id, w.revision)
            or not s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == n.id))):
        raise ws.WorkspaceError("follow_up_needs_current_review")
    core_note_review.require_current(s, n, core_checked)
    return n


def propose(s: Session, box: str, actor: str, wid: str, *, expected: int, key: str,
            note_id: str, body: str, due_date: date, expected_outcome: str, share: bool,
            core_checked: CoreDraftReceipt | None = None):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    if (share is not True or not body.strip() or len(body) > 4000 or not expected_outcome.strip()
            or len(expected_outcome) > 500 or type(due_date) is not date):
        raise ws.WorkspaceError("invalid_follow_up", 400)
    request_hash = payload_hash({"expected": expected, "note": note_id, "body": body,
                                 "due": due_date.isoformat(), "outcome": expected_outcome, "share": share})
    prior = s.scalar(select(FollowUpSource).where(FollowUpSource.workspace_id == wid, FollowUpSource.idempotency_key == key))
    if prior:
        if prior.source_kind != "reviewed_note" or prior.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        prior_note = s.get(WorkspaceNote, prior.note_id)
        assert prior_note is not None
        core_note_review.require_current(s, prior_note, core_checked)
        return _response(s, w)
    if key.startswith("vendor-origin:"):
        raise ws.WorkspaceError("invalid_follow_up", 400)
    n = _current(s, w, note_id, core_checked)
    count = s.scalar(select(func.count()).select_from(FollowUpSource).where(
        FollowUpSource.workspace_id == wid, FollowUpSource.source_kind == "reviewed_note"))
    if count is not None and count >= 50:
        raise ws.WorkspaceError("follow_up_history_limit")
    notes._advance(w, expected)
    # These fields are explicitly shared. Private provenance lives only in FollowUpSource.
    payload = {"action": ACTION, "channel": "local_synthetic", "body": body,
               "target_ref": f"patient_link:{w.patient_link_id}", "owner_id": actor,
               "due_date": due_date.isoformat(), "expected_outcome": expected_outcome}
    t = Ticket(box_id=box, lane=LANE, state="pending_approval", created_by_principal_id=actor,
               appointment_id=w.appointment_id, patient_link_id=w.patient_link_id)
    s.add(t)
    s.flush()
    r = ActionRevision(ticket_id=t.id, box_id=box, revision_number=1, action_type=ACTION,
                       target_ref=payload["target_ref"], content=body, payload=payload,
                       payload_hash=payload_hash(payload), automation_class="hitl_required",
                       policy_version="follow-up-synth-v1", charter_version="human-selected-v1",
                       config_version="local-only-v1", created_by_principal_id=actor)
    s.add(r)
    s.flush()
    t.current_revision_id = r.id
    s.add(FollowUpSource(ticket_id=t.id, box_id=box, workspace_id=wid, owner_id=actor,
                         note_id=n.id, content_hash=n.content_hash, source_fingerprint=n.source_fingerprint,
                         action_revision_id=r.id, payload_hash=r.payload_hash,
                         workspace_revision=w.revision, idempotency_key=key, request_hash=request_hash))
    _event(s, w, t, r, "follow_up.proposed", "pending_approval")
    s.commit()
    return _response(s, w)


def _bound(s, w, tid, revision_id, digest, *, writing=True):
    b = s.scalar(select(FollowUpSource).where(FollowUpSource.ticket_id == tid,
        FollowUpSource.workspace_id == w.id, FollowUpSource.box_id == w.box_id, FollowUpSource.owner_id == w.owner_id))
    if not b or b.source_kind != "reviewed_note":
        raise ws.WorkspaceError("follow_up_unavailable", 404)
    t = s.scalar(select(Ticket).where(Ticket.id == tid).with_for_update(read=not writing).execution_options(populate_existing=True))
    r = s.get(ActionRevision, b.action_revision_id)
    if (not t or not r or b.action_revision_id != revision_id or b.payload_hash != digest
            or t.current_revision_id != r.id or r.invalidated or t.lane != LANE
            or t.box_id != w.box_id or t.appointment_id != w.appointment_id or t.patient_link_id != w.patient_link_id
            or r.payload_hash != digest or payload_hash(r.payload) != digest
            or r.content != r.payload.get("body") or r.target_ref != f"patient_link:{w.patient_link_id}"
            or r.target_ref != r.payload.get("target_ref") or r.payload.get("owner_id") != w.owner_id
            or r.action_type != ACTION or r.payload.get("action") != ACTION
            or r.payload.get("channel") != "local_synthetic" or r.automation_class != "hitl_required"):
        raise ws.WorkspaceError("follow_up_approval_changed")
    return b, t, r


def _operation(s, t, r):
    op = s.scalar(select(Operation).where(Operation.action_revision_id == r.id).with_for_update().execution_options(populate_existing=True))
    if op and (op.ticket_id != t.id or op.box_id != t.box_id or op.adapter != ADAPTER):
        raise ws.WorkspaceError("follow_up_approval_changed")
    return op


def _event(s, w, t, r, kind, outcome, *, approved=False, actor=None):
    s.add(AuditEvent(box_id=w.box_id, aggregate_type="ticket", aggregate_id=t.id,
        event_type=kind, actor_principal_id=actor or w.owner_id,
        approved_by_principal_id=w.owner_id if approved else None,
        action_revision_id=r.id, payload_hash=r.payload_hash, policy_version=r.policy_version,
        charter_version=r.charter_version, config_version=r.config_version, outcome=outcome,
        detail={"channel": "local_synthetic"}))


def decide(s: Session, box: str, actor: str, wid: str, tid: str, *, revision_id: str, digest: str, choice: str,
           core_checked: CoreDraftReceipt | None = None, defer_delivery: bool = False):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    b, t, r = _bound(s, w, tid, revision_id, digest)
    op = _operation(s, t, r)
    if choice == "reject":
        if t.state == "rejected":
            return _response(s, w)
        if t.state not in {"pending_approval", "approved"} or (op and op.status != "pending"):
            raise ws.WorkspaceError("follow_up_already_delivered")
        # Existing F-8 work must remain resolvable after the notebook fills up.
        w.revision += 1
        t.state = "rejected"
        t.version += 1
        if op:
            op.status = "failed"
            op.error_message = "cancelled_before_local_delivery"
        s.add(Decision(box_id=box, ticket_id=tid, action_revision_id=r.id,
                       actor_principal_id=actor, kind="reject"))
        _event(s, w, t, r, "decision.rejected", "rejected")
        s.commit()
        return _response(s, w)
    if choice != "approve":
        raise ws.WorkspaceError("invalid_follow_up", 400)
    if op and op.status == "succeeded":
        return _response(s, w)
    note = _current(s, w, b.note_id, core_checked)
    needs_core_check = core_note_review.source_for(s, note) is not None
    if op is None:
        if t.state != "pending_approval":
            raise ws.WorkspaceError("follow_up_not_pending")
        w.revision += 1
        s.add(Decision(box_id=box, ticket_id=tid, action_revision_id=r.id,
                       actor_principal_id=actor, kind="approve"))
        op = Operation(box_id=box, ticket_id=tid, action_revision_id=r.id,
                       idempotency_key=f"op:{r.id}", adapter=ADAPTER, status="pending")
        s.add(op)
        t.state = "approved"
        t.version += 1
        _event(s, w, t, r, "decision.approved", "approved", approved=True)
        s.commit()  # durable intent survives failure before the local effect
    # Core-backed delivery needs a second signed request after durable intent.
    # Never reuse a receipt across this commit or perform I/O with local locks.
    if defer_delivery or needs_core_check:
        return _response(s, w)
    return deliver(s, box, actor, wid, tid, revision_id=revision_id, digest=digest)


def deliver(s: Session, box: str, actor: str, wid: str, tid: str, *, revision_id: str, digest: str,
            core_checked: CoreDraftReceipt | None = None):
    _local(s)
    # All commands lock human → workspace → target → ticket → operation.
    # Note/source changes and revocation serialize against this local DB effect.
    w = ws._workspace(s, box, actor, wid, writing=True)
    b, t, r = _bound(s, w, tid, revision_id, digest)
    op = _operation(s, t, r)
    if not op:
        raise ws.WorkspaceError("follow_up_approval_required")
    if op.status == "succeeded":
        return _response(s, w)
    _current(s, w, b.note_id, core_checked)
    decision = s.scalar(select(Decision.id).where(Decision.ticket_id == tid,
        Decision.box_id == box, Decision.action_revision_id == r.id,
        Decision.actor_principal_id == actor, Decision.kind == "approve"))
    audit = s.scalar(select(AuditEvent.id).where(AuditEvent.aggregate_id == tid,
        AuditEvent.box_id == box, AuditEvent.event_type == "decision.approved",
        AuditEvent.action_revision_id == r.id, AuditEvent.payload_hash == digest,
        AuditEvent.approved_by_principal_id == actor))
    if t.state != "approved" or op.status != "pending" or not decision or not audit:
        raise ws.WorkspaceError("follow_up_approval_required")
    w.revision += 1
    receipt = FollowUpReceipt(ticket_id=tid, box_id=box, operation_id=op.id,
        actor_id=actor, kind="local_delivery", content="Recorded in the local synthetic destination.",
        request_hash=payload_hash({"operation_id": op.id, "payload_hash": digest}),
        idempotency_key=op.idempotency_key)
    s.add(receipt)
    s.flush()
    op.status = "succeeded"
    op.attempt_count += 1
    op.started_at = receipt.created_at
    op.completed_at = receipt.created_at
    op.external_reference = "local:" + receipt.id
    op.result_receipt_hash = payload_hash({"receipt_id": receipt.id, "request_hash": receipt.request_hash})
    t.state = "sent"
    t.version += 1
    _event(s, w, t, r, "follow_up.local_delivery", "local_delivery")
    s.commit()  # local effect, evidence and F-8 status are one atomic commit
    return _response(s, w)


def complete(s: Session, box: str, actor: str, wid: str, tid: str, *, revision_id: str, digest: str,
             key: str, evidence: str):
    _local(s)
    w = ws._workspace(s, box, actor, wid, writing=True)
    _, t, r = _bound(s, w, tid, revision_id, digest)
    _record_completion(s, w, t, r, actor=actor, key=key, evidence=evidence)
    s.commit()
    return _response(s, w)


def _record_completion(s, w, t, r, *, actor, key, evidence):
    from cosmas_os.application.shared_work import responsible

    op = _operation(s, t, r)
    if not evidence.strip() or len(evidence) > 2000:
        raise ws.WorkspaceError("invalid_follow_up", 400)
    request_hash = payload_hash({"revision": r.id, "payload_hash": r.payload_hash, "evidence": evidence})
    prior = s.scalar(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == t.id, FollowUpReceipt.kind == "human_completion"))
    if prior:
        if prior.actor_id != actor or prior.request_hash != request_hash or prior.idempotency_key != key:
            raise ws.WorkspaceError("idempotency_conflict")
        return
    if responsible(s, t) != actor:
        raise ws.WorkspaceError("shared_work_responsibility_required")
    delivery = s.scalar(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == t.id, FollowUpReceipt.kind == "local_delivery"))
    if not op or op.status != "succeeded" or not delivery or t.state != "sent":
        raise ws.WorkspaceError("follow_up_delivery_required")
    w.revision += 1
    receipt = FollowUpReceipt(ticket_id=t.id, box_id=t.box_id, operation_id=op.id, actor_id=actor,
        kind="human_completion", content=evidence, request_hash=request_hash, idempotency_key=key)
    s.add(receipt)
    s.flush()
    t.state = "closed"
    t.closed_at = receipt.created_at
    t.version += 1
    _event(s, w, t, r, "follow_up.human_completion", "closed", actor=actor)


def read(s, w, revision):
    from cosmas_os.application.shared_work import responsible
    rows = s.scalars(select(FollowUpSource).where(FollowUpSource.workspace_id == w.id,
        FollowUpSource.box_id == w.box_id, FollowUpSource.owner_id == w.owner_id,
        FollowUpSource.source_kind == "reviewed_note",
        FollowUpSource.workspace_revision <= revision).order_by(FollowUpSource.workspace_revision.desc()))
    latest = notes._latest(s, w.id)
    fingerprint = notes.source_fingerprint(s, w.id, w.revision)
    result = []
    for b in rows:
        t, r, n = s.get(Ticket, b.ticket_id), s.get(ActionRevision, b.action_revision_id), s.get(WorkspaceNote, b.note_id)
        op = s.scalar(select(Operation).where(Operation.action_revision_id == r.id))
        receipts = list(s.scalars(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == t.id).order_by(
            FollowUpReceipt.created_at, FollowUpReceipt.kind.desc(), FollowUpReceipt.id)))
        result.append({"ticket_id": t.id, "revision_id": r.id, "payload_hash": r.payload_hash,
            "create_key": b.idempotency_key,
            "state": t.state, "body": r.content, "due_date": r.payload["due_date"],
            "expected_outcome": r.payload["expected_outcome"], "owner_id": w.owner_id,
            "responsible_id": responsible(s, t),
            "note_version": n.version, "source_changed": latest.id != b.note_id or fingerprint != b.source_fingerprint,
            "core_check_required": core_note_review.source_for(s, n) is not None,
            "operation_status": op.status if op else None,
            "receipts": [{"id": receipt.id, "kind": receipt.kind, "content": receipt.content,
                "actor_id": receipt.actor_id, "created_at": receipt.created_at.isoformat()} for receipt in receipts]})
    return result
