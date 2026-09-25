"""Private local membership review on F8; no membership writer, sender or processor."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NoReturn
from uuid import uuid4

from sqlalchemy import func, select

from cosmas_os.api import membership_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_work, note_review
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.finance_models import FinanceReceipt
from cosmas_os.membership_models import (
    MembershipCommandRetirement,
    MembershipReceipt,
    MembershipWork,
)
from cosmas_os.models import (
    ActionRevision,
    AuditEvent,
    Decision,
    Operation,
    Ticket,
    WorkspaceNoteReview,
)
from cosmas_os.vendor_models import VendorArtifact

LANE = "encounter_membership_work"
ACTION = "membership.local_review"
CONTENT = "Membership work — private human review"


@dataclass(frozen=True)
class MembershipPolicy:
    enabled: bool = False
    private_selectors_ready: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.private_selectors_ready) is not bool:
            raise ValueError("Explicit membership policy required")


DEFAULT_POLICY = MembershipPolicy()


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def final_authority(s):
    callback = s.info.get("membership_final_authority")
    if callback is not None:
        callback()


def owner(s, box, actor, wid, *, policy=DEFAULT_POLICY, writing=False):
    if not policy.private_selectors_ready:
        error("membership_work_unavailable", 404)
    try:
        return common._owner(s, box, actor, wid, writing=writing)
    except ws.WorkspaceError:
        error("membership_work_unavailable", 404)


def scope(w):
    return {"box_id": w.box_id, "owner_id": w.owner_id, "workspace_id": w.id}


def source(s, w, selected, checked=None):
    try:
        return common._source(s, w, selected, checked)
    except ws.WorkspaceError:
        error("membership_source_changed")


def saved(s, w, kind, request):
    digest = schema.request_digest(kind, scope(w), request)
    row = s.scalar(
        select(MembershipReceipt).where(
            MembershipReceipt.workspace_id == w.id,
            MembershipReceipt.owner_id == w.owner_id,
            MembershipReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row is None:
        row = s.scalar(
            select(MembershipCommandRetirement).where(
                MembershipCommandRetirement.workspace_id == w.id,
                MembershipCommandRetirement.owner_id == w.owner_id,
                MembershipCommandRetirement.idempotency_key == request.idempotency_key,
            )
        )
    if row and (row.command_kind != kind or row.request_sha256 != digest):
        error("membership_idempotency_conflict")
    return row, digest


def response(row):
    if isinstance(row, MembershipCommandRetirement):
        from cosmas_os.application.membership_retirement import response as retired_response

        return retired_response(row)
    value = dict(row.response)
    expected = public.public_digest("cosmas-membership-receipt.v1", value)
    if expected != row.receipt_sha256:
        error("membership_unavailable", 503)
    return public.bounded(
        schema.Response.model_validate({**value, "receipt_sha256": expected}).public(), 8192
    )


def bound(s, w, tid):
    t = s.scalar(
        select(Ticket)
        .where(
            Ticket.id == tid,
            Ticket.box_id == w.box_id,
            Ticket.created_by_principal_id == w.owner_id,
            Ticket.lane == LANE,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    r = s.get(MembershipWork, tid)
    a = s.get(ActionRevision, r.revision_id) if r else None
    if (
        t is None
        or r is None
        or a is None
        or r.workspace_id != w.id
        or r.owner_id != w.owner_id
        or r.patient_link_id != w.patient_link_id
        or t.patient_link_id != w.patient_link_id
        or t.appointment_id != w.appointment_id
        or t.current_revision_id != r.revision_id
        or a.invalidated
        or a.payload_hash != r.payload_hash
        or payload_hash(a.payload) != r.payload_hash
        or a.action_type != ACTION
        or a.content != CONTENT
        or a.automation_class != "hitl_required"
        or a.target_ref != "membership_work:" + tid
        or a.created_by_principal_id != w.owner_id
        or public.public_digest("cosmas-membership-review.v1", r.review) != r.review_sha256
        or s.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is not None
    ):
        error("membership_work_unavailable", 404)
    schema.Review.model_validate(r.review)
    return t, r


def check_bound(t, r, request):
    if (t.id, t.version, r.revision_id, r.payload_hash) != (
        request.ticket_id,
        request.expected_version,
        request.revision_id,
        request.payload_hash,
    ):
        error("membership_revision_changed")


def latest_result(s, tid):
    return s.scalar(
        select(MembershipReceipt)
        .where(MembershipReceipt.ticket_id == tid, MembershipReceipt.command_kind == "result")
        .order_by(MembershipReceipt.version.desc())
        .limit(1)
    )


def classification(result):
    if result is None or "ledger" not in result.request:
        return "local_unreconciled"
    return (
        "manual_ledger_and_finance_review"
        if "finance" in result.request["ledger"]
        else "manual_ledger_record"
    )


def proof(s, w, ledger):
    document = ledger.document
    artifact = s.scalar(
        select(VendorArtifact)
        .where(
            VendorArtifact.artifact_id == document.artifact_id,
            VendorArtifact.workspace_id == w.id,
            VendorArtifact.box_id == w.box_id,
            VendorArtifact.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        artifact is None
        or artifact.state != "ready"
        or (artifact.sha256, artifact.byte_length, artifact.media_type)
        != (document.sha256, document.byte_length, document.media_type)
    ):
        error("membership_evidence_changed")
    if datetime.fromisoformat(ledger.observed_at.replace("Z", "+00:00")) > common._clock(
        s
    ) + timedelta(minutes=5):
        error("membership_evidence_changed")
    if ledger.finance is not None:
        p = ledger.finance
        receipt = s.get(FinanceReceipt, p.verification_receipt_id)
        if receipt is None or (
            receipt.ticket_id,
            receipt.workspace_id,
            receipt.box_id,
            receipt.owner_id,
            receipt.command_kind,
            receipt.receipt_sha256,
        ) != (p.ticket_id, w.id, w.box_id, w.owner_id, "verify", p.verification_receipt_sha256):
            error("membership_evidence_changed")
        try:
            t, r, _ = finance_work.bound(s, w, p.ticket_id)
            financial = finance_work.summary(s, t, r)
            finance_work.response(s, receipt)
        except ws.WorkspaceError:
            error("membership_evidence_changed")
        if (
            t.state != "closed"
            or financial["conflicting_evidence"]
            or financial["evidence_sha256"] != p.evidence_sha256
        ):
            error("membership_evidence_changed")
    # This validates identity/custody and a human financial review. It does not
    # promote an owner-entered ledger claim into independent vendor acceptance.


def record(s, w, t, r, kind, request, digest, effect, *, result=None):
    s.flush()
    final_authority(s)
    rid, now = str(uuid4()), common._clock(s)
    prior_result = result if result is not None else latest_result(s, t.id)
    category = classification(prior_result)
    if kind == "result":
        category = (
            "manual_ledger_and_finance_review"
            if request.ledger and request.ledger.finance
            else "manual_ledger_record"
            if request.ledger
            else "local_unreconciled"
        )
    value = {
        "contract_version": 1,
        "scope": scope(w),
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": digest,
        "outcome": "recorded",
        "effect": {
            "ticket_id": t.id,
            "revision_id": r.revision_id,
            "payload_hash": r.payload_hash,
            "version": t.version,
            "receipt_id": rid,
            "recorded_at": public.timestamp(now),
            "effect": effect,
            "state": t.state,
            "evidence_classification": category,
            "external_service_verified": False,
        },
    }
    row = MembershipReceipt(
        id=rid,
        ticket_id=t.id,
        box_id=w.box_id,
        owner_id=w.owner_id,
        workspace_id=w.id,
        version=t.version,
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        request=request.public(),
        request_sha256=digest,
        response=value,
        receipt_sha256=public.public_digest("cosmas-membership-receipt.v1", value),
        result_receipt_id=result.id if result else None,
        recorded_at=now,
    )
    s.add(row)
    s.add(
        AuditEvent(
            box_id=w.box_id,
            aggregate_type="ticket",
            aggregate_id=t.id,
            event_type="membership_work." + kind,
            actor_principal_id=w.owner_id,
            action_revision_id=r.revision_id,
            payload_hash=r.payload_hash,
            outcome=effect,
            detail={"receipt_id": rid},
        )
    )
    s.flush()
    final_authority(s)
    return row


def propose(s, box, actor, wid, request, *, policy=DEFAULT_POLICY, core_checked=None):
    w = owner(s, box, actor, wid, policy=policy, writing=True)
    old, digest = saved(s, w, "propose", request)
    if old:
        final_authority(s)
        return response(old)
    if not policy.enabled:
        error("membership_feature_disabled", 403)
    if (w.revision, w.patient_link_id) != (
        request.expected_workspace_revision,
        request.patient_link_id,
    ):
        error("membership_source_changed")
    n = source(s, w, request.source, core_checked)
    if (
        s.scalar(
            select(func.count())
            .select_from(MembershipWork)
            .where(MembershipWork.workspace_id == wid)
        )
        >= 100
    ):
        error("membership_history_limit")
    tid, rid, now = str(uuid4()), str(uuid4()), common._clock(s)
    t = Ticket(
        id=tid,
        box_id=box,
        lane=LANE,
        state="pending_approval",
        version=1,
        created_by_principal_id=actor,
        appointment_id=w.appointment_id,
        patient_link_id=w.patient_link_id,
    )
    s.add(t)
    s.flush()
    review = schema.Review(
        ticket_id=tid,
        revision_id=rid,
        patient_link_id=w.patient_link_id,
        proposal=request,
        authority="local_human_review_only",
        automatic_membership_changes=False,
        automatic_messages_or_money_movement=False,
    ).public()
    rh = public.public_digest("cosmas-membership-review.v1", review)
    payload = {"action": ACTION, "review_sha256": rh, "request_sha256": digest}
    a = ActionRevision(
        id=rid,
        ticket_id=tid,
        box_id=box,
        revision_number=1,
        action_type=ACTION,
        target_ref="membership_work:" + tid,
        content=CONTENT,
        payload=payload,
        payload_hash=payload_hash(payload),
        automation_class="hitl_required",
        policy_version="membership-human-review-v1",
        charter_version="private-membership-v1",
        config_version="membership-v1",
        created_by_principal_id=actor,
    )
    s.add(a)
    s.flush()
    t.current_revision_id = rid
    r = MembershipWork(
        ticket_id=tid,
        revision_id=rid,
        box_id=box,
        owner_id=actor,
        workspace_id=wid,
        patient_link_id=w.patient_link_id,
        source_workspace_revision=w.revision,
        note_id=n.id,
        content_hash=n.content_hash,
        source_fingerprint=n.source_fingerprint,
        payload_hash=a.payload_hash,
        request_sha256=digest,
        review_sha256=rh,
        proposal=request.public(),
        review=review,
        created_at=now,
    )
    s.add(r)
    s.flush()
    row = record(s, w, t, r, "propose", request, digest, "proposed")
    s.commit()
    return response(row)


def command(s, box, actor, wid, tid, kind, request, *, policy=DEFAULT_POLICY, core_checked=None):
    if (
        kind not in {"decide", "result", "verify", "withdraw"}
        or type(request) is not schema.COMMANDS[kind]
    ):
        error("invalid_membership_request", 400)
    if tid != request.ticket_id:
        error("membership_revision_changed")
    w = owner(s, box, actor, wid, policy=policy, writing=True)
    old, digest = saved(s, w, kind, request)
    if old:
        final_authority(s)
        return response(old)
    t, r = bound(s, w, tid)
    check_bound(t, r, request)
    result = None
    if kind == "withdraw":
        if t.state not in {"pending_approval", "approved"}:
            error("membership_revision_changed")
        t.state, effect = "withdrawn", "withdrawn"
    else:
        if not policy.enabled:
            error("membership_feature_disabled", 403)
        proposal = schema.Proposal.model_validate(r.proposal)
        source(s, w, proposal.source, core_checked)
        if w.revision != r.source_workspace_revision:
            error("membership_source_changed")
        if kind == "decide":
            if t.state != "pending_approval" or request.review_sha256 != r.review_sha256:
                error("membership_revision_changed")
            t.state = "approved" if request.choice == "approve" else "rejected"
            s.add(
                Decision(
                    box_id=box,
                    ticket_id=tid,
                    action_revision_id=r.revision_id,
                    actor_principal_id=actor,
                    kind=request.choice,
                )
            )
            effect = t.state
        elif kind == "result":
            if t.state != "approved" or t.version >= 98:
                error(
                    "membership_revision_changed"
                    if t.state != "approved"
                    else "membership_history_limit"
                )
            if request.ledger is not None:
                proof(s, w, request.ledger)
            effect = "result_recorded"
        else:
            result = latest_result(s, tid)
            if (
                t.state != "approved"
                or result is None
                or (result.id, result.receipt_sha256)
                != (request.result_receipt_id, request.result_receipt_sha256)
            ):
                error("membership_result_changed")
            previous = schema.Result.model_validate(result.request)
            if (
                previous.disposition == "needs_human"
                or request.evidence_classification != classification(result)
            ):
                error("membership_exception_unresolved")
            if previous.ledger is not None:
                proof(s, w, previous.ledger)
            t.state, t.closed_at, effect = "closed", common._clock(s), "review_verified"
    if t.version >= 100:
        error("membership_history_limit")
    t.version += 1
    row = record(s, w, t, r, kind, request, digest, effect, result=result)
    s.commit()
    return response(row)


def summary(s, w, t, r, *, policy=DEFAULT_POLICY):
    latest = latest_result(s, t.id)
    current = "none"
    if latest and "ledger" in latest.request:
        try:
            proof(s, w, schema.Result.model_validate(latest.request).ledger)
            current = "available"
        except ws.WorkspaceError:
            current = "changed"
    disposition = latest.request["disposition"] if latest else "none"
    note = note_review._latest(s, w.id)
    source_current = (
        w.revision == r.source_workspace_revision
        and note is not None
        and (note.id, note.content_hash, note.source_fingerprint)
        == (r.note_id, r.content_hash, r.source_fingerprint)
        and note_review.source_fingerprint(s, w.id, w.revision) == r.source_fingerprint
    )
    return schema.Summary(
        ticket_id=t.id,
        version=t.version,
        revision_id=r.revision_id,
        payload_hash=r.payload_hash,
        purpose=r.proposal["purpose"],
        due_date=r.proposal["due_date"],
        state=t.state,
        evidence_classification=classification(latest),
        evidence_current=current,
        result=disposition,
        verification="review_verified" if t.state == "closed" else "pending",
        external_service_verified=False,
        membership_authority="not_established",
        source_current=source_current,
        can_verify=policy.enabled
        and source_current
        and t.state == "approved"
        and disposition in {"local_preparation_ready", "record_reviewed"}
        and current != "changed",
    ).public()


def detail(s, box, actor, wid, tid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid, policy=policy)
    t, r = bound(s, w, tid)
    latest = latest_result(s, tid)
    value = schema.Detail.model_validate(
        {
            "contract_version": 1,
            "scope": scope(w),
            "summary": summary(s, w, t, r, policy=policy),
            "review": r.review,
            "review_sha256": r.review_sha256,
            "latest_result": {
                "receipt_id": latest.id,
                "receipt_sha256": latest.receipt_sha256,
                "request": latest.request,
            }
            if latest
            else None,
        }
    ).public()
    final_authority(s)
    return public.bounded(value, 32768)


def options(s, box, actor, wid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid, policy=policy)
    n = note_review._latest(s, wid)
    selected = (
        {
            "kind": "reviewed_note",
            "note_id": n.id,
            "content_sha256": n.content_hash,
            "source_fingerprint": n.source_fingerprint,
        }
        if n
        and n.source_fingerprint == note_review.source_fingerprint(s, wid, w.revision)
        and s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == n.id))
        else None
    )
    value = schema.Options.model_validate(
        {
            "contract_version": 1,
            "scope": scope(w),
            "patient_link_id": w.patient_link_id,
            "expected_workspace_revision": w.revision,
            "source": selected,
            "enabled": policy.enabled,
            "installed_membership_service": "not_selected",
        }
    ).public()
    final_authority(s)
    return public.bounded(value, 8192)


def catalog(s, box, actor, wid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid, policy=policy)
    ids = list(
        s.scalars(
            select(MembershipWork.ticket_id)
            .where(MembershipWork.workspace_id == wid, MembershipWork.owner_id == actor)
            .order_by(MembershipWork.created_at, MembershipWork.ticket_id)
            .limit(101)
        )
    )
    if len(ids) > 100:
        error("membership_history_limit")
    items = [summary(s, w, *bound(s, w, tid), policy=policy) for tid in ids]
    final_authority(s)
    return public.bounded(
        schema.Catalog.model_validate(
            {"contract_version": 1, "scope": scope(w), "items": items}
        ).public(),
        131072,
    )


def resolve(s, box, actor, wid, request, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid, policy=policy)
    row = s.scalar(
        select(MembershipReceipt).where(
            MembershipReceipt.workspace_id == wid,
            MembershipReceipt.owner_id == actor,
            MembershipReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row is None:
        row = s.scalar(
            select(MembershipCommandRetirement).where(
                MembershipCommandRetirement.workspace_id == wid,
                MembershipCommandRetirement.owner_id == actor,
                MembershipCommandRetirement.idempotency_key == request.idempotency_key,
            )
        )
    if row and (
        row.command_kind != request.command_kind or row.request_sha256 != request.request_sha256
    ):
        error("membership_idempotency_conflict")
    final_authority(s)
    return (
        response(row)
        if row
        else schema.Response.model_validate(
            {
                "contract_version": 1,
                "scope": scope(w),
                **request.public(),
                "outcome": "not_found",
                "effect": None,
                "receipt_sha256": None,
            }
        ).public()
    )


def history(s, box, actor, wid, tid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid, policy=policy)
    bound(s, w, tid)
    rows = list(
        s.scalars(
            select(MembershipReceipt)
            .where(MembershipReceipt.ticket_id == tid)
            .order_by(MembershipReceipt.version)
            .limit(101)
        )
    )
    if len(rows) > 100:
        error("membership_history_limit")
    value = schema.History.model_validate(
        {
            "contract_version": 1,
            "scope": scope(w),
            "ticket_id": tid,
            "items": [{"request": r.request, "receipt": response(r)} for r in rows],
        }
    ).public()
    final_authority(s)
    return public.bounded(value, 1048576)
