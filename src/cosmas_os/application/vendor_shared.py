"""Revision-scoped publication/responsibility; no owner connector or PDF powers."""

from sqlalchemy import func, or_, select

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.models import EncounterWorkspace, Principal, Ticket, WorkHandoff
from cosmas_os.vendor_models import (
    VendorCommandReceipt,
    VendorConnectionVersion,
    VendorWork,
    VendorWorkRevision,
)


def _records(s, r):
    return list(
        s.scalars(
            select(WorkHandoff)
            .where(
                WorkHandoff.ticket_id == r.ticket_id,
                WorkHandoff.action_revision_id == r.action_revision_id,
                WorkHandoff.payload_hash == r.payload_hash,
            )
            .order_by(WorkHandoff.sequence)
        )
    )


def _entitled(s, actor, r):
    publication = work._publication(s, r)
    return publication is not None and (
        actor == r.owner_id
        or s.scalar(
            select(WorkHandoff.id).where(
                WorkHandoff.action_revision_id == r.action_revision_id,
                WorkHandoff.payload_hash == r.payload_hash,
                WorkHandoff.vendor_publication_receipt_id == publication.id,
                or_(WorkHandoff.from_id == actor, WorkHandoff.to_id == actor),
            )
        )
        is not None
    )


def _target(s, box, actor, tid, *, writing=False, revision_id=None, recipient=None):
    binding = s.get(VendorWork, tid)
    if binding is None or binding.box_id != box:
        work.error("vendor_work_unavailable", 404)
    for pid in sorted({actor, binding.owner_id, recipient} - {None}):
        if pid == binding.owner_id and actor != binding.owner_id:
            p = s.scalar(
                select(Principal)
                .where(
                    Principal.id == pid,
                    Principal.box_id == box,
                    Principal.principal_type == "human",
                )
                .with_for_update(read=not writing)
            )
            if p is None:
                work.error("vendor_work_unavailable", 404)
        else:
            ws._human(s, box, pid, creating=writing)
    w = s.scalar(
        select(EncounterWorkspace)
        .where(
            EncounterWorkspace.id == binding.workspace_id,
            EncounterWorkspace.box_id == box,
            EncounterWorkspace.owner_id == binding.owner_id,
        )
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    if w is None:
        work.error("vendor_work_unavailable", 404)
    ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=w.owner_id)
    t = s.scalar(
        select(Ticket)
        .where(Ticket.id == tid)
        .with_for_update(read=not writing)
        .execution_options(populate_existing=True)
    )
    candidates = list(
        s.scalars(
            select(VendorWorkRevision)
            .where(VendorWorkRevision.ticket_id == tid)
            .order_by(VendorWorkRevision.revision_number.desc())
        )
    )
    r = next(
        (
            r
            for r in candidates
            if (revision_id is None or r.action_revision_id == revision_id)
            and _entitled(s, actor, r)
        ),
        None,
    )
    if r is None:
        work.error("vendor_work_unavailable", 404)
    return w, t, r, _records(s, r)


def view(s, actor, t, r, records, *, detail=True):
    publication = work._publication(s, r)
    projection = publication.publication_projection
    historical = r.action_revision_id != t.current_revision_id
    summary = work._summary(s, t, r)
    item = {
        "work_kind": "vendor_delivery",
        "ticket_id": t.id,
        "version": t.version,
        "revision_id": r.action_revision_id,
        "payload_hash": r.payload_hash,
        "state": "superseded" if historical else t.state,
        "ready_for_review": not historical
        and summary["result"] != "none"
        and summary["verification"] != "verified",
        "historical": historical,
        "publication_receipt_id": publication.id,
        "body": projection["body"],
        "due_date": projection["due_date"],
        "expected_outcome": projection["expected_outcome"],
        "viewer_id": actor,
        "originator": work._person(s, r.owner_id),
        "responsible": work._person(s, work._responsible(s, r)),
        "vendor_work": {
            "action": r.action,
            "operation_id": r.intended_operation_id,
            **{
                key: summary[key]
                for key in (
                    "submit_claimed",
                    "acceptance",
                    "transport",
                    "conflicting_evidence",
                    "result",
                    "verification",
                    "observation_head",
                    "evidence_sha256",
                )
            },
        },
    }
    if detail:
        pending = (
            records[-1]
            if records and records[-1].kind == "offer" and not historical and t.state == "approved"
            else None
        )
        result = work._latest_result(s, r)
        item.update(
            pending_offer=None
            if pending is None
            else {
                "id": pending.id,
                "from": work._person(s, pending.from_id),
                "to": work._person(s, pending.to_id),
            },
            handoffs=[
                {
                    "id": row.id,
                    "kind": row.kind,
                    "actor": work._person(s, row.actor_id),
                    "from": work._person(s, row.from_id),
                    "to": work._person(s, row.to_id),
                    "offer_id": row.offer_id,
                    "created_at": public.timestamp(row.created_at),
                }
                for row in records
            ],
            latest_result=None
            if result is None
            else {
                "receipt_id": result.id,
                "receipt_sha256": result.receipt_sha256,
                "actor": work._person(s, result.actor_id),
                **result.result_payload,
                "recorded_at": public.timestamp(result.recorded_at),
            },
        )
    schema = public.SharedVendorDetail if detail else public.SharedVendorWork
    return public.bounded(schema.model_validate(item).public(), 262144 if detail else 16384)


def read(s, box, actor, tid):
    _, t, r, records = _target(s, box, actor, tid)
    return view(s, actor, t, r, records)


def _resolve_row(s, w, actor, tid, request):
    row = s.scalar(
        select(VendorCommandReceipt).where(
            VendorCommandReceipt.workspace_id == w.id,
            VendorCommandReceipt.actor_id == actor,
            VendorCommandReceipt.origin == "user",
            VendorCommandReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row and (
        row.scope_kind != "practice_work"
        or row.scope_id != tid
        or row.command_kind != request.command_kind
        or row.request_sha256 != request.request_sha256
    ):
        work.error("vendor_idempotency_conflict")
    return row


def resolve(s, box, actor, tid, request):
    # Discover only immutable scope, then authorize the exact historical revision.
    binding = s.get(VendorWork, tid)
    if binding is None or binding.box_id != box:
        work.error("vendor_work_unavailable", 404)
    row = s.scalar(
        select(VendorCommandReceipt).where(
            VendorCommandReceipt.workspace_id == binding.workspace_id,
            VendorCommandReceipt.actor_id == actor,
            VendorCommandReceipt.origin == "user",
            VendorCommandReceipt.idempotency_key == request.idempotency_key,
        )
    )
    w, _, _, _ = _target(s, box, actor, tid, revision_id=row.action_revision_id if row else None)
    row = _resolve_row(s, w, actor, tid, request)
    if row:
        return work.command_response(s, row)
    return {
        "contract_version": 1,
        "scope": {"kind": "practice_work", "id": tid},
        **request.public(),
        "outcome": "not_found",
        "effect": None,
        "summary": None,
        "observed_at": public.timestamp(work._clock(s)),
    }


def record_result(s, box, actor, tid, request):
    w, t, r, _ = _target(s, box, actor, tid, writing=True, revision_id=request.revision_id)
    old, digest = work._receipt(
        s, w, actor, "result", request, scope=work._scope(w, "practice_work", tid)
    )
    if old:
        return work.command_response(s, old)
    work._check_bound(t, r, request)
    if t.state != "approved" or work._responsible(s, r) != actor or actor == r.owner_id:
        work.error("vendor_revision_changed")
    if work._evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
        work.error("vendor_evidence_changed")
    work._guard_text(
        s, w, s.get(VendorConnectionVersion, r.connection_version_id), request.evidence
    )
    t.version += 1
    receipt = work._record(
        s,
        w,
        actor,
        "result",
        request,
        digest,
        t,
        r,
        "result_recorded",
        result={
            "disposition": request.disposition,
            "evidence": request.evidence,
            "observation_head": request.observation_head.public(),
        },
        scope=work._scope(w, "practice_work", tid),
    )
    s.commit()
    return work.command_response(s, receipt)


def handoff(s, box, actor, tid, request):
    # Historical receipt recovery must not depend on a still-active recipient.
    w, t, r, records = _target(s, box, actor, tid, writing=True, revision_id=request.revision_id)
    old, digest = work._receipt(
        s, w, actor, "handoff", request, scope=work._scope(w, "practice_work", tid)
    )
    if old:
        return work.command_response(s, old)
    if request.recipient_id:
        # Release all lower locks before taking the full, ordered people set.
        s.rollback()
        w, t, r, records = _target(
            s,
            box,
            actor,
            tid,
            writing=True,
            revision_id=request.revision_id,
            recipient=request.recipient_id,
        )
        old, digest = work._receipt(
            s, w, actor, "handoff", request, scope=work._scope(w, "practice_work", tid)
        )
        if old:
            return work.command_response(s, old)
    if (request.expected_version, request.revision_id, request.payload_hash) != (
        t.version,
        t.current_revision_id,
        r.payload_hash,
    ) or t.state != "approved":
        work.error("vendor_revision_changed")
    sequence = (
        s.scalar(select(func.max(WorkHandoff.sequence)).where(WorkHandoff.ticket_id == tid)) or 0
    ) + 1
    if sequence > 201:
        work.error("vendor_history_limit")
    responsible = work._responsible(s, r)
    pending = records[-1] if records and records[-1].kind == "offer" else None
    if request.kind == "offer":
        if actor != responsible or pending or request.recipient_id == responsible:
            work.error("vendor_revision_changed")
        sender, recipient = actor, request.recipient_id
    elif request.kind in {"accept", "decline", "recall"}:
        if (
            pending is None
            or request.offer_id != pending.id
            or actor != (pending.from_id if request.kind == "recall" else pending.to_id)
        ):
            work.error("vendor_revision_changed")
        sender, recipient = pending.from_id, pending.to_id
    else:
        if actor != r.owner_id or responsible == actor:
            work.error("vendor_revision_changed")
        sender, recipient = responsible, actor
    t.version += 1
    s.add(
        WorkHandoff(
            ticket_id=tid,
            box_id=box,
            action_revision_id=r.action_revision_id,
            payload_hash=r.payload_hash,
            sequence=sequence,
            expected_version=request.expected_version,
            kind=request.kind,
            actor_id=actor,
            from_id=sender,
            to_id=recipient,
            offer_id=request.offer_id,
            vendor_publication_receipt_id=work._publication(s, r).id,
            idempotency_key=request.idempotency_key,
            request_hash=digest,
        )
    )
    receipt = work._record(
        s,
        w,
        actor,
        "handoff",
        request,
        digest,
        t,
        r,
        "handoff_recorded",
        scope=work._scope(w, "practice_work", tid),
    )
    s.commit()
    return work.command_response(s, receipt)
