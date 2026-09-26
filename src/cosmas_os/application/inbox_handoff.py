"""Private Inbox provenance on F8, with explicit minimal publication and accountability.

The receipt table only resolves exact HTTP commands. Ticket, Decision, Operation,
FollowUpReceipt and WorkHandoff remain the effect and responsibility authorities.
There is no sender, worker queue, automatic reply or new clinical decision engine.
"""

from dataclasses import dataclass
from typing import NoReturn
from uuid import uuid4

from sqlalchemy import func, or_, select

from cosmas_os.api import inbox_handoff_schemas as p
from cosmas_os.api.vendor_work_schemas import bounded, public_digest, timestamp
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import prep_work, shared_work, vendor_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.inbox_handoff_models import InboxHandoffReceipt
from cosmas_os.inbox_models import InboxItem
from cosmas_os.models import (
    ActionRevision,
    Decision,
    EncounterWorkspace,
    FollowUpReceipt,
    FollowUpSource,
    Operation,
    Principal,
    Ticket,
    WorkHandoff,
)

LANE = "encounter_inbox_handoff"
ACTION = "incoming_message.internal_publication"
ADAPTER = "workspace_internal_inbox"


@dataclass(frozen=True)
class Policy:
    enabled: bool = False


DEFAULT_POLICY = Policy()


def error(code="inbox_handoff_unavailable", status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def _fence(s):
    callback = s.info.get("inbox_handoff_final_authority")
    if callback:
        callback()


def _scope(w, actor, kind, q):
    return {
        "box_id": w.box_id,
        "owner_id": w.owner_id,
        "actor_id": actor,
        "kind": "workspace" if kind == "propose" else "ticket",
        "id": w.id if kind == "propose" else q.ticket_id,
    }


def request_hash(w, actor, kind, q):
    return public_digest(
        "cosmas-inbox-handoff-request.v1",
        {"scope": _scope(w, actor, kind, q), "command_kind": kind, "request": q.public()},
    )


def _prior(s, w, actor, kind, key, digest):
    row = s.scalar(
        select(InboxHandoffReceipt).where(
            InboxHandoffReceipt.workspace_id == w.id,
            InboxHandoffReceipt.actor_id == actor,
            InboxHandoffReceipt.idempotency_key == key,
        )
    )
    if row and (row.command_kind != kind or row.request_sha256 != digest):
        error("inbox_handoff_idempotency_conflict")
    return row


def response(row):
    if public_digest("cosmas-inbox-handoff-receipt.v1", row.response) != row.receipt_sha256:
        error("inbox_handoff_integrity", 503)
    return bounded(
        p.Response.model_validate({**row.response, "receipt_sha256": row.receipt_sha256}).public(),
        16384,
    )


def _record(s, w, actor, kind, q, digest, t, effect, reason=None):
    rid, now = str(uuid4()), vendor_work._clock(s)
    value = {
        "contract_version": 1,
        "scope": _scope(w, actor, kind, q),
        "command_kind": kind,
        "idempotency_key": q.idempotency_key,
        "request_sha256": digest,
        "outcome": "rejected" if reason else "recorded",
        "effect": effect,
        "rejection": reason,
        "receipt_id": rid,
        "recorded_at": timestamp(now),
    }
    row = InboxHandoffReceipt(
        id=rid,
        box_id=w.box_id,
        owner_id=w.owner_id,
        workspace_id=w.id,
        actor_id=actor,
        ticket_id=t.id if t else None,
        command_kind=kind,
        idempotency_key=q.idempotency_key,
        request=q.public(),
        request_sha256=digest,
        response=value,
        receipt_sha256=public_digest("cosmas-inbox-handoff-receipt.v1", value),
        recorded_at=now,
    )
    s.add(row)
    return row


def _workspace(s, box, owner, wid, *, writing):
    w = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == wid,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == owner,
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if w is None:
        error(status=404)
    ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    return w


def _owned(s, box, actor, wid, iid, *, writing=True):
    row = inbox.item(s, box, actor, iid, writing=writing)
    w = _workspace(s, box, actor, wid, writing=writing)
    if w.patient_link_id != row.patient_link_id:
        error(status=404)
    return w, row


def _bound(s, box, actor, tid, *, writing=False, recipient=None):
    b = s.get(FollowUpSource, tid)
    if b is None or b.box_id != box or b.source_kind != "incoming_message":
        error(status=404)
    # Do not disclose a ticket's existence before caller participation is checked.
    records = shared_work.history(s, s.get(Ticket, tid))
    if actor != b.owner_id and not any(actor in {x.from_id, x.to_id} for x in records):
        error(status=404)
    for pid in sorted({actor, b.owner_id, recipient} - {None}):
        if pid == actor:
            ws._human(s, box, pid, creating=writing)
        else:
            # Lock the complete ordered people set before item/workspace/ticket.
            # Inactive source owners still permit a minimal escalation signal;
            # a new recipient's active authority is checked before the transition.
            s.scalar(
                select(Principal)
                .where(Principal.id == pid, Principal.box_id == box)
                .with_for_update(read=not writing)
            )
    row = s.scalar(
        select(InboxItem)
        .where(InboxItem.id == b.inbox_item_id)
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if row is None or (row.box_id, row.owner_id) != (box, b.owner_id):
        error(status=404)
    w = _workspace(s, box, b.owner_id, b.workspace_id, writing=writing)
    if w.patient_link_id != row.patient_link_id:
        error(status=404)
    t = s.scalar(
        select(Ticket)
        .where(Ticket.id == tid)
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    r = s.get(ActionRevision, b.action_revision_id)
    if (
        t is None
        or r is None
        or t.lane != LANE
        or t.created_by_principal_id != b.owner_id
        or t.box_id != box
        or t.patient_link_id != w.patient_link_id
        or t.appointment_id != w.appointment_id
        or t.current_revision_id != r.id
        or r.action_type != ACTION
        or r.payload_hash != b.payload_hash
        or payload_hash(r.payload) != r.payload_hash
        or r.content != r.payload.get("body")
        or r.payload.get("action") != ACTION
        or r.payload.get("channel") != "internal_work"
        or r.target_ref != f"patient_link:{w.patient_link_id}"
        or r.invalidated
    ):
        error("inbox_handoff_integrity", 503)
    return w, row, b, t, r, shared_work.history(s, t)


def _reason(s, w, row, source_id, source_hash, review_id, review_hash, registry, policy):
    if not policy.enabled:
        return "feature_disabled"
    if row.read_issue or row.source_conflict or row.current_source_id != source_id:
        return "source_changed"
    source = inbox.head(s, row)
    if (
        source is None
        or source.source_sha256 != source_hash
        or inbox.source_snapshot(source).incomplete_content
    ):
        return "source_changed"
    review = inbox.latest(s, row, "review")
    if (
        review is None
        or (review.id, review.receipt_sha256) != (review_id, review_hash)
        or review.request["workspace_id"] != w.id
        or not inbox.workspace_current(s, row, review)
    ):
        return "review_changed"
    inbox.response(review)  # Recompute the retained review receipt before admission.
    try:
        inbox.grant_current(
            s, w.box_id, w.owner_id, inbox.InboxReadGrant.model_validate(row.grant), registry
        )
    except ws.WorkspaceError:
        return "authority_changed"
    return None


def _current(s, w, row, b, registry, policy):
    return _reason(
        s,
        w,
        row,
        b.inbox_source_id,
        b.inbox_source_sha256,
        b.inbox_review_receipt_id,
        b.inbox_review_sha256,
        registry,
        policy,
    )


def _receipt(s, t, kind):
    return prep_work.receipt(s, t, kind)


def _effect(t, r, effect_id):
    return {
        "ticket_id": t.id,
        "version": t.version,
        "revision_id": r.id,
        "payload_hash": r.payload_hash,
        "effect_id": effect_id,
        "state": t.state,
    }


def _append_receipt(s, t, op, actor, kind, q, digest, content):
    receipt = FollowUpReceipt(
        ticket_id=t.id,
        box_id=t.box_id,
        operation_id=op.id,
        actor_id=actor,
        kind=kind,
        content=content,
        request_hash=digest,
        idempotency_key=q.idempotency_key,
    )
    s.add(receipt)
    s.flush()
    return receipt


def propose(s, box, actor, wid, q, *, registry=inbox.no_registry, policy=DEFAULT_POLICY):
    if type(q) is not p.Propose:
        error("invalid_inbox_handoff", 400)
    w, row = _owned(s, box, actor, wid, q.item_id)
    digest = request_hash(w, actor, "propose", q)
    old = _prior(s, w, actor, "propose", q.idempotency_key, digest)
    if old:
        _fence(s)
        return response(old)
    if (
        s.scalar(
            select(func.count())
            .select_from(InboxHandoffReceipt)
            .where(InboxHandoffReceipt.workspace_id == wid)
        )
        or 0
    ) >= 1000:
        error("inbox_handoff_history_limit")
    if (
        s.scalar(
            select(func.count())
            .select_from(FollowUpSource)
            .where(
                FollowUpSource.owner_id == actor,
                FollowUpSource.box_id == box,
                FollowUpSource.source_kind == "incoming_message",
            )
        )
        or 0
    ) >= 100:
        error("inbox_handoff_history_limit")
    reason = _reason(
        s,
        w,
        row,
        q.source_id,
        q.source_sha256,
        q.review_receipt_id,
        q.review_receipt_sha256,
        registry,
        policy,
    )
    if w.revision != q.expected_workspace_revision:
        reason = "review_changed"
    t = r = None
    if not reason:
        payload = {
            "action": ACTION,
            "channel": "internal_work",
            "body": q.instructions,
            "selected_context": q.selected_context,
            "due_date": q.due_date,
            "expected_outcome": q.expected_outcome,
        }
        t = Ticket(
            box_id=box,
            lane=LANE,
            state="pending_approval",
            created_by_principal_id=actor,
            appointment_id=w.appointment_id,
            patient_link_id=w.patient_link_id,
        )
        s.add(t)
        s.flush()
        r = ActionRevision(
            ticket_id=t.id,
            box_id=box,
            revision_number=1,
            action_type=ACTION,
            target_ref=f"patient_link:{w.patient_link_id}",
            content=q.instructions,
            payload=payload,
            payload_hash=payload_hash(payload),
            automation_class="hitl_required",
            policy_version="incoming-internal-v1",
            charter_version="human-selected-v1",
            config_version="local-only-v1",
            created_by_principal_id=actor,
        )
        s.add(r)
        s.flush()
        t.current_revision_id = r.id
        s.add(
            FollowUpSource(
                ticket_id=t.id,
                box_id=box,
                workspace_id=wid,
                owner_id=actor,
                source_kind="incoming_message",
                inbox_item_id=row.id,
                inbox_source_id=q.source_id,
                inbox_source_sha256=q.source_sha256,
                inbox_review_receipt_id=q.review_receipt_id,
                inbox_review_sha256=q.review_receipt_sha256,
                action_revision_id=r.id,
                payload_hash=r.payload_hash,
                workspace_revision=w.revision,
                idempotency_key=q.idempotency_key,
                request_hash=digest,
            )
        )
        s.flush()
    receipt = _record(
        s, w, actor, "propose", q, digest, t, _effect(t, r, r.id) if t and r else None, reason
    )
    s.flush()
    _fence(s)
    if not reason and _reason(
        s,
        w,
        row,
        q.source_id,
        q.source_sha256,
        q.review_receipt_id,
        q.review_receipt_sha256,
        registry,
        policy,
    ):
        error("inbox_handoff_changed")
    s.commit()
    return response(receipt)


def command(s, box, actor, tid, kind, q, *, registry=inbox.no_registry, policy=DEFAULT_POLICY):
    if (
        kind not in {"decide", "handoff", "result", "verify"}
        or type(q) is not p.COMMANDS[kind]
        or q.ticket_id != tid
    ):
        error("invalid_inbox_handoff", 400)
    # Recovery never requires the former recipient to remain active.
    w, row, b, t, r, records = _bound(s, box, actor, tid)
    digest = request_hash(w, actor, kind, q)
    old = _prior(s, w, actor, kind, q.idempotency_key, digest)
    if old:
        _fence(s)
        return response(old)
    s.rollback()  # Release read locks before the complete ordered write-lock set.
    w, row, b, t, r, records = _bound(
        s, box, actor, tid, writing=True, recipient=q.recipient_id if kind == "handoff" else None
    )
    old = _prior(s, w, actor, kind, q.idempotency_key, digest)
    if old:
        _fence(s)
        return response(old)
    if actor != w.owner_id and kind in {"decide", "verify"}:
        error(status=404)
    if (
        len(
            list(
                s.scalars(
                    select(InboxHandoffReceipt.id).where(InboxHandoffReceipt.ticket_id == tid)
                )
            )
        )
        >= 250
    ):
        error("inbox_handoff_history_limit")
    reason = _current(s, w, row, b, registry, policy)
    if (q.expected_version, q.revision_id, q.payload_hash) != (t.version, r.id, r.payload_hash):
        reason = "work_changed"
    effect_id = None
    # Known-scope denied commands receive inert exact receipts; they cannot later act.
    if not reason:
        if kind == "decide":
            if t.state != "pending_approval":
                reason = "work_changed"
            else:
                decision = Decision(
                    box_id=box,
                    ticket_id=tid,
                    action_revision_id=r.id,
                    actor_principal_id=actor,
                    kind=q.choice,
                )
                s.add(decision)
                t.state = "approved" if q.choice == "approve" else "rejected"
                t.version += 1
                if q.choice == "approve":
                    op = Operation(
                        box_id=box,
                        ticket_id=tid,
                        action_revision_id=r.id,
                        idempotency_key=f"inbox:{r.id}",
                        adapter=ADAPTER,
                        status="succeeded",
                        attempt_count=1,
                    )
                    s.add(op)
                    s.flush()
                    published = _append_receipt(
                        s,
                        t,
                        op,
                        actor,
                        "internal_publication",
                        q,
                        digest,
                        "Owner published only the selected internal context. No external message was sent.",
                    )
                    op.started_at = op.completed_at = published.created_at
                    op.result_receipt_hash = payload_hash(
                        {"receipt_id": published.id, "request_hash": digest}
                    )
                    effect_id = published.id
                else:
                    s.flush()
                    effect_id = decision.id
        else:
            published, ready = (
                _receipt(s, t, "internal_publication"),
                _receipt(s, t, "ready_for_review"),
            )
            op = s.scalar(select(Operation).where(Operation.action_revision_id == r.id))
            if t.state != "approved" or published is None or op is None or op.status != "succeeded":
                reason = "publication_required"
            elif kind == "handoff":
                if ready and q.kind != "reclaim":
                    reason = "result_already_recorded"
                else:
                    try:
                        if q.recipient_id:
                            ws._human(s, box, q.recipient_id, creating=True)
                        h = shared_work.append_responsibility(
                            s,
                            t,
                            r,
                            records,
                            actor=actor,
                            expected=q.expected_version,
                            key=q.idempotency_key,
                            kind=q.kind,
                            digest_request=digest,
                            recipient=q.recipient_id,
                            offer_id=q.offer_id,
                        )
                    except ws.WorkspaceError:
                        reason = "responsibility_changed"
                    else:
                        s.flush()
                        effect_id = h.id
            elif kind == "result":
                if ready or shared_work.responsible(s, t, records) != actor:
                    reason = "responsibility_required"
                elif actor != w.owner_id and not any(
                    x.kind == "accept" and x.to_id == actor for x in records
                ):
                    reason = "responsibility_required"
                else:
                    result = _append_receipt(
                        s, t, op, actor, "ready_for_review", q, digest, q.evidence
                    )
                    t.version += 1
                    effect_id = result.id
            else:
                if ready is None or (ready.id, ready.request_hash) != (
                    q.result_receipt_id,
                    q.result_request_sha256,
                ):
                    reason = "result_changed"
                else:
                    verified = _append_receipt(
                        s,
                        t,
                        op,
                        actor,
                        "incoming_verification",
                        q,
                        digest,
                        "Owner reviewed the current incoming source and accountable local handoff result.",
                    )
                    t.state = "closed"
                    t.closed_at = verified.created_at
                    t.version += 1
                    effect_id = verified.id
    s.flush()
    receipt = _record(
        s, w, actor, kind, q, digest, t, None if reason else _effect(t, r, effect_id), reason
    )
    s.flush()
    _fence(s)
    if not reason and _current(s, w, row, b, registry, policy):
        error("inbox_handoff_changed")
    s.commit()
    return response(receipt)


def _view(s, actor, w, row, b, t, r, records, registry, policy):
    published = _receipt(s, t, "internal_publication")
    if actor != w.owner_id and published is None:
        error(status=404)
    _fence(s)
    reason = _current(s, w, row, b, registry, policy)
    visible = reason is None and published is not None
    owner_review = reason is None and actor == w.owner_id and t.state == "pending_approval"
    ready, verified = _receipt(s, t, "ready_for_review"), _receipt(s, t, "incoming_verification")
    owner = s.get(Principal, w.owner_id)
    value = {
        "contract_version": 1,
        "work_kind": "incoming_message",
        "ticket_id": t.id,
        "version": t.version,
        "revision_id": r.id,
        "payload_hash": r.payload_hash,
        "state": "source_unavailable" if reason else t.state,
        "publication_active": visible,
        "requires_owner_attention": reason is not None,
        "originator_id": w.owner_id,
        "originator_available": bool(owner and owner.state == "active" and not owner.tombstoned_at),
        "responsible_id": shared_work.responsible(s, t, records),
        "publication_receipt_id": published.id if published else None,
        "instructions": r.content if visible or actor == w.owner_id else None,
        "selected_context": r.payload["selected_context"]
        if visible or actor == w.owner_id
        else None,
        "due_date": r.payload["due_date"] if visible or owner_review else None,
        "expected_outcome": r.payload["expected_outcome"] if visible or owner_review else None,
        "result": {
            "receipt_id": ready.id,
            "request_sha256": ready.request_hash,
            "actor_id": ready.actor_id,
            "evidence": ready.content,
        }
        if visible and ready
        else None,
        "verified_current": bool(visible and verified and t.state == "closed"),
        "handoffs": [
            {
                "id": x.id,
                "kind": x.kind,
                "from_id": x.from_id,
                "to_id": x.to_id,
                "offer_id": x.offer_id,
            }
            for x in records
        ],
        "external_action_performed": False,
    }
    if actor == w.owner_id:
        value["private_source"] = {
            "item_id": row.id,
            "source_id": b.inbox_source_id,
            "source_sha256": b.inbox_source_sha256,
            "review_receipt_id": b.inbox_review_receipt_id,
            "review_receipt_sha256": b.inbox_review_sha256,
            "unavailability": reason,
        }
    return bounded(p.Detail.model_validate(value).public(), 65536)


def read(s, box, actor, tid, *, registry=inbox.no_registry, policy=DEFAULT_POLICY):
    w, row, b, t, r, records = _bound(s, box, actor, tid)
    if actor == w.owner_id:
        inbox.owner(s, box, actor)
    return _view(s, actor, w, row, b, t, r, records, registry, policy)


def resolve(s, box, actor, wid, q):
    ws._human(s, box, actor)
    row = s.scalar(
        select(InboxHandoffReceipt).where(
            InboxHandoffReceipt.workspace_id == wid,
            InboxHandoffReceipt.actor_id == actor,
            InboxHandoffReceipt.idempotency_key == q.idempotency_key,
        )
    )
    if row and row.ticket_id:
        w, _, _, _, _, _ = _bound(s, box, actor, row.ticket_id)
    else:
        inbox.owner(s, box, actor)
        w = _workspace(s, box, actor, wid, writing=False)
    row = _prior(s, w, actor, q.command_kind, q.idempotency_key, q.request_sha256)
    _fence(s)
    if row:
        return response(row)
    return {
        "contract_version": 1,
        "outcome": "not_found",
        "effect": None,
        "scope": None,
        **q.public(),
    }


def resolve_ticket(s, box, actor, tid, q):
    w, _, _, _, _, _ = _bound(s, box, actor, tid)
    row = _prior(s, w, actor, q.command_kind, q.idempotency_key, q.request_sha256)
    if row and row.ticket_id != tid:
        error("inbox_handoff_idempotency_conflict")
    _fence(s)
    return (
        response(row)
        if row
        else {
            "contract_version": 1,
            "outcome": "not_found",
            "effect": None,
            "scope": None,
            **q.public(),
        }
    )


def catalog(s, box, actor, *, registry=inbox.no_registry, policy=DEFAULT_POLICY):
    ws._human(s, box, actor)
    participation = (
        select(WorkHandoff.id)
        .where(
            WorkHandoff.ticket_id == Ticket.id,
            or_(WorkHandoff.from_id == actor, WorkHandoff.to_id == actor),
        )
        .exists()
    )
    ids = list(
        s.scalars(
            select(Ticket.id)
            .where(
                Ticket.box_id == box,
                Ticket.lane == LANE,
                or_(Ticket.created_by_principal_id == actor, participation),
            )
            .order_by(Ticket.id)
            .limit(101)
        )
    )
    if len(ids) > 100:
        error("inbox_handoff_history_limit")
    items = []
    for tid in ids:
        detail = read(s, box, actor, tid, registry=registry, policy=policy)
        items.append({key: detail[key] for key in p.Summary.model_fields})
    return bounded(
        p.Catalog.model_validate({"contract_version": 1, "items": items}).public(), 131072
    )
