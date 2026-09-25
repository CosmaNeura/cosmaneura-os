"""Explicit human responsibility on deliberately published F-8 follow-ups.

Offers do not transfer responsibility. Acceptance is bound to the same immutable
action and current ticket version. This surface never returns private provenance.
"""

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from cosmas_os.application import follow_up as follow
from cosmas_os.application import prep_work as prep
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    EncounterWorkspace,
    FollowUpReceipt,
    FollowUpSource,
    Principal,
    Ticket,
    WorkHandoff,
)


def history(s, ticket):
    return list(s.scalars(select(WorkHandoff).where(WorkHandoff.ticket_id == ticket.id,
        WorkHandoff.box_id == ticket.box_id).order_by(WorkHandoff.sequence)))


def responsible(s, ticket, records=None):
    records = history(s, ticket) if records is None else records
    return next((row.to_id for row in reversed(records) if row.kind in {"accept", "reclaim"}),
                ticket.created_by_principal_id)


def _pending(ticket, records):
    opened = ticket.state == ("approved" if ticket.lane == prep.LANE else "sent")
    return records[-1] if opened and records and records[-1].kind == "offer" else None


def _visible(actor, source, records):
    return source.owner_id == actor or any(actor in {row.from_id, row.to_id} for row in records)


def _read_connection(s, routine):
    if routine:
        # Only the private report reader opts in; delivery keeps its own gate.
        from cosmas_os.application.routines import _local

        _local(s)
    else:
        follow._local(s)


def _target(s, box, actor, tid, *, writing=False, recipient=None, _routine_read=False):
    if _routine_read and (writing or recipient is not None):
        raise ws.WorkspaceError("routine_read_only", 403)
    _read_connection(s, _routine_read)
    for pid in sorted({actor, recipient} - {None}):
        try:
            ws._human(s, box, pid)
        except ws.WorkspaceError:
            if pid == actor:
                raise
            raise ws.WorkspaceError("shared_work_recipient_unavailable") from None
    source = s.scalar(select(FollowUpSource).where(FollowUpSource.ticket_id == tid, FollowUpSource.box_id == box))
    ticket = s.get(Ticket, tid) if source else None
    if not source or not ticket or not _visible(actor, source, history(s, ticket)):
        raise ws.WorkspaceError("shared_work_unavailable", 404)
    if source.source_kind == "incoming_message":
        raise ws.WorkspaceError("inbox_handoff_contract_required", 426)
    flow = prep if source.source_kind == "core_prep" else follow
    if flow is prep:
        prep.available()
    # Use private binding metadata to serialize with the original provider's
    # commands. Staff never acquire a read of that provider's private workspace.
    w = s.scalar(select(EncounterWorkspace).where(EncounterWorkspace.id == source.workspace_id,
        EncounterWorkspace.box_id == box, EncounterWorkspace.owner_id == source.owner_id)
        .with_for_update(read=not writing).execution_options(populate_existing=True))
    if not w:
        raise ws.WorkspaceError("shared_work_unavailable", 404)
    ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    _, ticket, revision = flow._bound(s, w, tid, source.action_revision_id, source.payload_hash, writing=writing)
    if ticket.created_by_principal_id != source.owner_id:
        raise ws.WorkspaceError("shared_work_unavailable", 404)
    records = history(s, ticket)
    if not _visible(actor, source, records):
        raise ws.WorkspaceError("shared_work_unavailable", 404)
    return w, ticket, revision, records


def _person(s, box, pid):
    p = s.get(Principal, pid)
    if not p or p.box_id != box or p.principal_type != "human":
        raise ws.WorkspaceError("shared_work_unavailable", 404)
    return {"id": p.id, "name": p.display_name,
            "available": p.state == "active" and p.tombstoned_at is None}


def _view(s, actor, ticket, revision, records):
    owner = responsible(s, ticket, records)
    is_prep = ticket.lane == prep.LANE
    ready = is_prep and prep.ready(s, ticket)
    pending = None if ready else _pending(ticket, records)
    return {"ticket_id": ticket.id, "version": ticket.version,
        "work_kind": "visit_preparation" if is_prep else "follow_up", "ready_for_review": ready,
        "revision_id": revision.id, "payload_hash": revision.payload_hash,
        "state": ticket.state, "body": revision.content, "due_date": revision.payload["due_date"],
        "expected_outcome": revision.payload["expected_outcome"], "viewer_id": actor,
        "originator": _person(s, ticket.box_id, ticket.created_by_principal_id),
        "responsible": _person(s, ticket.box_id, owner),
        "pending_offer": {"id": pending.id, "from": _person(s, ticket.box_id, pending.from_id),
            "to": _person(s, ticket.box_id, pending.to_id)} if pending else None,
        "handoffs": [{"id": row.id, "kind": row.kind, "actor": _person(s, ticket.box_id, row.actor_id),
            "from": _person(s, ticket.box_id, row.from_id), "to": _person(s, ticket.box_id, row.to_id),
            "offer_id": row.offer_id, "created_at": row.created_at.isoformat()} for row in records],
        "receipts": [{"id": row.id, "kind": row.kind, "content": row.content,
            "actor": _person(s, ticket.box_id, row.actor_id), "created_at": row.created_at.isoformat()}
            for row in s.scalars(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == ticket.id,
                FollowUpReceipt.box_id == ticket.box_id).order_by(
                    FollowUpReceipt.created_at, FollowUpReceipt.kind.desc(), FollowUpReceipt.id))]}


def read(s, box, actor, tid, *, vendor=False, _routine_read=False):
    if _routine_read:
        _read_connection(s, True)
    source = s.get(FollowUpSource, tid)
    if source is not None and source.source_kind == "incoming_message":
        raise ws.WorkspaceError("inbox_handoff_contract_required", 426)
    if source is not None and source.source_kind == "vendor_reviewed_note":
        if not vendor:
            raise ws.WorkspaceError("vendor_contract_required", 426)
        from cosmas_os.application import vendor_shared
        return vendor_shared.read(s, box, actor, tid)
    _, ticket, revision, records = _target(s, box, actor, tid, _routine_read=_routine_read)
    return _view(s, actor, ticket, revision, records)


def catalog(s, box, actor, *, after=None, vendor=False, _routine_read=False):
    _read_connection(s, _routine_read)
    ws._human(s, box, actor)
    participation = exists(select(WorkHandoff.id).where(WorkHandoff.ticket_id == Ticket.id,
        WorkHandoff.box_id == box, or_(WorkHandoff.from_id == actor, WorkHandoff.to_id == actor)))
    lanes = [(Ticket.lane == follow.LANE) & Ticket.state.in_({"sent", "closed"}),
        (Ticket.lane == prep.LANE) & Ticket.state.in_({"approved", "closed"})]
    if vendor:
        from cosmas_os.vendor_models import VendorCommandReceipt
        lanes.append((Ticket.lane == "encounter_vendor_delivery") & exists(select(VendorCommandReceipt.id).where(
            VendorCommandReceipt.ticket_id == Ticket.id, VendorCommandReceipt.publication_projection.is_not(None))))
    query = select(Ticket.id).where(Ticket.box_id == box, or_(*lanes),
        or_(Ticket.created_by_principal_id == actor, participation))
    if after is not None:
        query = query.where(Ticket.id > after)
    ids = list(s.scalars(query.order_by(Ticket.id).limit(51)))
    items = []
    for tid in ids[:50]:
        try:
            items.append(read(s, box, actor, tid, vendor=vendor, _routine_read=_routine_read))
        except ws.WorkspaceError as exc:
            if exc.status != 404:
                raise
    return {"items": items, "next_cursor": ids[49] if len(ids) > 50 else None,
        "people": [_person(s, box, p.id) for p in s.scalars(select(Principal).where(
            Principal.box_id == box, Principal.principal_type == "human", Principal.state == "active",
            Principal.tombstoned_at.is_(None)).order_by(Principal.display_name, Principal.id))]}


def act(s: Session, box, actor, tid, *, expected, revision_id, digest, key, kind,
        recipient=None, offer_id=None):
    source = s.get(FollowUpSource, tid)
    if source is not None and source.source_kind == "incoming_message":
        raise ws.WorkspaceError("inbox_handoff_contract_required", 426)
    if source is not None and source.source_kind == "vendor_reviewed_note":
        raise ws.WorkspaceError("vendor_contract_required", 426)
    if (kind not in {"offer", "accept", "decline", "recall", "reclaim"}
            or (kind == "offer") != (recipient is not None)
            or (kind in {"accept", "decline", "recall"}) != (offer_id is not None)):
        raise ws.WorkspaceError("invalid_shared_work", 400)
    follow._local(s)
    digest_request = payload_hash({"expected": expected, "revision": revision_id, "digest": digest,
        "kind": kind, "recipient": recipient, "offer": offer_id})
    prior = s.scalar(select(WorkHandoff).where(WorkHandoff.box_id == box,
        WorkHandoff.ticket_id == tid, WorkHandoff.actor_id == actor, WorkHandoff.idempotency_key == key))
    if prior:
        # Recover an immutable historical effect with current caller/encounter
        # authority. A subsequently revoked recipient cannot receive new work,
        # but must not make an already-committed offer's reply unrecoverable.
        _, ticket, revision, records = _target(s, box, actor, tid)
        if revision.id != revision_id or revision.payload_hash != digest:
            raise ws.WorkspaceError("follow_up_approval_changed")
        if prior.request_hash != digest_request:
            raise ws.WorkspaceError("idempotency_conflict")
        return _view(s, actor, ticket, revision, records)
    w, ticket, revision, records = _target(s, box, actor, tid, writing=True, recipient=recipient)
    if revision.id != revision_id or revision.payload_hash != digest:
        raise ws.WorkspaceError("follow_up_approval_changed")
    # Recheck under the normal write locks if a concurrent request committed
    # after the initial lookup. New effects keep the original recipient locks.
    prior = next((row for row in records if row.actor_id == actor and row.idempotency_key == key), None)
    if prior:
        if prior.request_hash != digest_request:
            raise ws.WorkspaceError("idempotency_conflict")
        return _view(s, actor, ticket, revision, records)
    if ticket.version != expected:
        raise ws.WorkspaceError("shared_work_changed")
    is_prep = ticket.lane == prep.LANE
    if is_prep and not prep.is_open(s, ticket, revision):
        raise ws.WorkspaceError("prep_work_publication_required")
    if is_prep and prep.ready(s, ticket) and kind != "reclaim":
        raise ws.WorkspaceError("prep_work_ready_for_review")
    if not is_prep and ticket.state != "sent":
        raise ws.WorkspaceError("follow_up_delivery_required")
    append_responsibility(s, ticket, revision, records, actor=actor, expected=expected,
        key=key, kind=kind, digest_request=digest_request, recipient=recipient, offer_id=offer_id)
    if is_prep:
        prep._event(s, w, ticket, revision, "prep_work.responsibility_" + kind, kind, actor=actor)
    else:
        follow._event(s, w, ticket, revision, "follow_up.responsibility_" + kind, kind, actor=actor)
    s.commit()
    return read(s, box, actor, tid)


def complete(s, box, actor, tid, *, revision_id, digest, key, evidence, expected=None):
    w, ticket, revision, _ = _target(s, box, actor, tid, writing=True)
    if revision.id != revision_id or revision.payload_hash != digest:
        raise ws.WorkspaceError("follow_up_approval_changed")
    if ticket.lane == prep.LANE:
        prep.record_ready(s, w, ticket, revision, actor=actor, expected=expected, key=key, evidence=evidence)
    else:
        follow._record_completion(s, w, ticket, revision, actor=actor, key=key, evidence=evidence)
    s.commit()
    return read(s, box, actor, tid)


def append_responsibility(s, ticket, revision, records, *, actor, expected, key, kind,
                          digest_request, recipient=None, offer_id=None):
    """One F8 responsibility transition. Caller holds scope/ticket locks and admission."""
    if ticket.version != expected:
        raise ws.WorkspaceError("shared_work_changed")
    owner = responsible(s, ticket, records)
    pending = records[-1] if records and records[-1].kind == "offer" else None
    from_id, to_id = owner, recipient
    if kind == "offer":
        if actor != owner or recipient == owner or pending:
            raise ws.WorkspaceError("shared_work_offer_unavailable")
        if len(records) >= 199:
            raise ws.WorkspaceError("shared_work_history_limit")
    elif kind == "reclaim":
        if actor != ticket.created_by_principal_id or actor == owner:
            raise ws.WorkspaceError("shared_work_reclaim_unavailable")
        # The reserved final record allows the provider to recover responsibility
        # from a revoked staff member even when normal handoff history is full.
        if len(records) >= 201:
            raise ws.WorkspaceError("shared_work_history_limit")
        to_id = actor
    else:
        if not pending or pending.id != offer_id or pending.from_id != owner:
            raise ws.WorkspaceError("shared_work_offer_changed")
        if actor != (pending.from_id if kind == "recall" else pending.to_id):
            raise ws.WorkspaceError("shared_work_access_denied", 403)
        from_id, to_id = pending.from_id, pending.to_id
    row = WorkHandoff(ticket_id=ticket.id, box_id=ticket.box_id, action_revision_id=revision.id,
        payload_hash=revision.payload_hash, sequence=len(records) + 1, expected_version=expected,
        kind=kind, actor_id=actor, from_id=from_id, to_id=to_id, offer_id=offer_id,
        idempotency_key=key, request_hash=digest_request)
    s.add(row)
    ticket.version += 1
    return row
