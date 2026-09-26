"""Private human-reviewed payment requests on F8, with no connector I/O here."""

from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import func, select

from cosmas_os.api import finance_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_paging as paging
from cosmas_os.application import finance_setup as setup
from cosmas_os.application import note_review
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.finance_models import (
    FinanceConnectionVersion,
    FinanceCustomerVersion,
    FinanceObservation,
    FinanceReceipt,
    FinanceSubmitClaim,
    FinanceWorkRevision,
)
from cosmas_os.models import (
    ActionRevision,
    AuditEvent,
    Decision,
    Operation,
    Ticket,
    WorkspaceNoteReview,
)
from cosmas_os.ports import vendor_connectors as private

LANE = "encounter_payment_request"
ADAPTER = "workspace_finance"
CONTENT = "Payment request — private review"


@dataclass(frozen=True)
class FinancePolicy:
    enabled: bool = False
    io_enabled: bool = False
    events_enabled: bool = False

    def __post_init__(self):
        if any(
            type(value) is not bool
            for value in (self.enabled, self.io_enabled, self.events_enabled)
        ):
            raise ValueError("Explicit financial feature flags required")


DEFAULT_POLICY = FinancePolicy()


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def final_authority(s):
    check = s.info.get("finance_final_authority")
    if check is not None:
        check()


def owner(s, box, actor, wid, *, writing=False):
    try:
        return common._owner(s, box, actor, wid, writing=writing)
    except ws.WorkspaceError:
        error("finance_work_unavailable", 404)


def source(s, w, selected, checked=None):
    try:
        return common._source(s, w, selected, checked)
    except ws.WorkspaceError:
        error("finance_source_changed")


def receipt(s, w, actor, kind, request):
    digest = schema.request_digest(kind, {"kind": "workspace", "id": w.id}, request)
    row = s.scalar(
        select(FinanceReceipt).where(
            FinanceReceipt.workspace_id == w.id,
            FinanceReceipt.actor_id == actor,
            FinanceReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row and (row.command_kind != kind or row.request_sha256 != digest):
        error("finance_idempotency_conflict")
    return row, digest


def response(s, row):
    envelope = {
        "scope": {"kind": "workspace", "id": row.workspace_id},
        "command_kind": row.command_kind,
        "idempotency_key": row.idempotency_key,
        "request_sha256": row.request_sha256,
        "effect": row.effect,
    }
    if public.public_digest("cosmas-finance-public-receipt.v1", envelope) != row.receipt_sha256:
        error("finance_unavailable", 503)
    return public.bounded(
        schema.FinanceResponse.model_validate(
            {
                "contract_version": 1,
                **envelope,
                "receipt_sha256": row.receipt_sha256,
                "outcome": "recorded",
                "observed_at": public.timestamp(common._clock(s)),
            }
        ).public(),
        16384,
    )


def record(s, w, actor, kind, request, digest, t, r, effect, *, result=None, result_receipt=None):
    # The receipt guard inspects the newly advanced F8 ticket version.
    s.flush()
    final_authority(s)
    now, rid = common._clock(s), str(uuid4())
    outcome = {
        "ticket_id": t.id,
        "revision_id": r.action_revision_id,
        "operation_id": r.intended_operation_id,
        "payload_hash": r.payload_hash,
        "receipt_id": rid,
        "effect_version": t.version,
        "recorded_at": public.timestamp(now),
        "effect": effect,
    }
    envelope = {
        "scope": {"kind": "workspace", "id": w.id},
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": digest,
        "effect": outcome,
    }
    row = FinanceReceipt(
        id=rid,
        box_id=w.box_id,
        owner_id=w.owner_id,
        workspace_id=w.id,
        actor_id=actor,
        ticket_id=t.id,
        action_revision_id=r.action_revision_id,
        operation_id=r.intended_operation_id,
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        public_request=request.public(),
        request_sha256=digest,
        effect_version=t.version,
        effect=outcome,
        receipt_sha256=public.public_digest("cosmas-finance-public-receipt.v1", envelope),
        recorded_at=now,
        result_payload=result,
        result_receipt_id=result_receipt.id if result_receipt else None,
        observation_head_sha256=request.observation_head.sha256
        if isinstance(request, (schema.FinanceResult, schema.FinanceVerify))
        else None,
        evidence_sha256=request.evidence_sha256
        if isinstance(request, (schema.FinanceResult, schema.FinanceVerify))
        else None,
    )
    s.add(row)
    s.add(
        AuditEvent(
            box_id=w.box_id,
            aggregate_type="ticket",
            aggregate_id=t.id,
            event_type="finance_work." + kind,
            actor_principal_id=actor,
            action_revision_id=r.action_revision_id,
            payload_hash=r.payload_hash,
            outcome=effect,
            detail={"operation_id": r.intended_operation_id, "receipt_id": rid},
        )
    )
    s.flush()
    final_authority(s)
    return row


def selected(s, w, connection, customer, *, writing=True):
    c = s.scalar(
        select(FinanceConnectionVersion)
        .where(
            FinanceConnectionVersion.id == connection.id,
            FinanceConnectionVersion.box_id == w.box_id,
            FinanceConnectionVersion.owner_id == w.owner_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    m = s.scalar(
        select(FinanceCustomerVersion)
        .where(
            FinanceCustomerVersion.id == customer.id,
            FinanceCustomerVersion.box_id == w.box_id,
            FinanceCustomerVersion.owner_id == w.owner_id,
            FinanceCustomerVersion.patient_link_id == w.patient_link_id,
            FinanceCustomerVersion.connection_version_id == connection.id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        c is None
        or m is None
        or c.revoked_at
        or m.revoked_at
        or writing
        and (not c.is_current or not c.write_enabled or not m.is_current)
    ):
        error("finance_selection_changed")
    cv, mv = setup.connection_view(c), setup.customer_view(m)
    if (c.revision, cv["public_sha256"], m.revision, mv["public_sha256"]) != (
        connection.revision,
        connection.public_sha256,
        customer.revision,
        customer.public_sha256,
    ):
        error("finance_selection_changed")
    selection = private.ConnectionSelection.model_validate(c.private_selection)
    mapping = {
        "connection_id": c.id,
        "patient_link_id": m.patient_link_id,
        "customer_id": m.customer_id,
    }
    if (
        selection.vendor != "stripe"
        or c.private_sha256 != selection.commitment()
        or m.mapping_sha256 != private.digest("cosmas-finance-customer.v1", mapping)
    ):
        error("finance_selection_changed")
    return c, m, selection, cv, mv


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
    r = s.get(FinanceWorkRevision, t.current_revision_id) if t else None
    if (
        t is None
        or r is None
        or r.workspace_id != w.id
        or r.ticket_id != tid
        or r.owner_id != w.owner_id
    ):
        error("finance_work_unavailable", 404)
    command = private.VendorCommand.model_validate(r.private_command)
    a = s.get(ActionRevision, r.action_revision_id)
    if (
        command.commitment() != r.private_command_sha256
        or public.public_digest("cosmas-finance-review.v1", r.public_review) != r.review_sha256
        or a is None
        or a.payload_hash != r.payload_hash
        or payload_hash(a.payload) != r.payload_hash
        or a.content != CONTENT
        or a.target_ref != "finance_work:" + tid
    ):
        error("finance_unavailable", 503)
    return t, r, command


def check_bound(t, r, request):
    if (t.version, r.action_revision_id, r.intended_operation_id, r.payload_hash) != (
        request.expected_version,
        request.revision_id,
        request.operation_id,
        request.payload_hash,
    ):
        error("finance_revision_changed")


def latest_result(s, r):
    return s.scalar(
        select(FinanceReceipt)
        .where(
            FinanceReceipt.action_revision_id == r.action_revision_id,
            FinanceReceipt.command_kind == "result",
        )
        .order_by(FinanceReceipt.effect_version.desc())
        .limit(1)
    )


def head(s, r):
    last = s.scalar(
        select(FinanceObservation)
        .where(FinanceObservation.operation_id == r.intended_operation_id)
        .order_by(FinanceObservation.sequence.desc())
        .limit(1)
    )
    return (
        {"sequence": last.sequence, "sha256": last.head_sha256}
        if last
        else {
            "sequence": 0,
            "sha256": public.public_digest(
                "cosmas-finance-observation-head.v1",
                {"operation_id": r.intended_operation_id, "sequence": 0},
            ),
        }
    )


def evidence(s, r):
    current, result = head(s, r), latest_result(s, r)
    return current, public.public_digest(
        "cosmas-finance-evidence.v1",
        {
            "operation_id": r.intended_operation_id,
            "observation_head": current,
            "result_receipt_id": result.id if result else None,
            "result_receipt_sha256": result.receipt_sha256 if result else None,
        },
    )


def summary(s, t, r):
    observations = list(
        s.scalars(
            select(FinanceObservation)
            .where(FinanceObservation.operation_id == r.intended_operation_id)
            .order_by(FinanceObservation.sequence)
        )
    )
    creations = {
        o.public_observation.get("acceptance") for o in observations if o.kind == "creation"
    }
    payments = [o.public_observation for o in observations if o.kind == "payment"]
    states = {p["payment_state"] for p in payments}
    terminal = states & {"succeeded", "canceled"}
    conflict = len(terminal) > 1 or {"accepted", "rejected"}.issubset(creations)
    payment = (
        "unknown"
        if conflict
        else next(iter(terminal))
        if terminal
        else payments[-1]["payment_state"]
        if payments
        else "not_observed"
    )
    paid = next(
        (p["amount_received"] for p in reversed(payments) if p["payment_state"] == payment), 0
    )
    claim, result = s.get(FinanceSubmitClaim, r.intended_operation_id), latest_result(s, r)
    h, e = evidence(s, r)
    return schema.FinanceSummary.model_validate(
        {
            "ticket_id": t.id,
            "version": t.version,
            "revision_id": r.action_revision_id,
            "operation_id": r.intended_operation_id,
            "payload_hash": r.payload_hash,
            "state": t.state,
            "amount": r.amount,
            "currency": r.currency,
            "creation": "accepted"
            if "accepted" in creations
            else "rejected"
            if "rejected" in creations
            else "unconfirmed"
            if creations
            else "not_observed",
            "payment_state": payment,
            "amount_received": paid,
            "submit_claimed": claim is not None,
            "conflicting_evidence": conflict,
            "result": result.result_payload["disposition"] if result else "none",
            "verification": "verified" if t.state == "closed" else "pending",
            "observation_head": h,
            "evidence_sha256": e,
        }
    ).public()


def detail(s, box, actor, wid, tid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid)
    t, r, _ = bound(s, w, tid)
    value = {
        "contract_version": 1,
        "workspace_id": wid,
        "summary": summary(s, t, r),
        "review": r.public_review,
        "review_sha256": r.review_sha256,
        "latest_result": None,
    }
    result = latest_result(s, r)
    if result is not None:
        value["latest_result"] = {
            "receipt_id": result.id,
            "receipt_sha256": result.receipt_sha256,
            **result.result_payload,
            "recorded_at": public.timestamp(result.recorded_at),
        }
    final_authority(s)
    return public.bounded(schema.FinanceDetail.model_validate(value).public(), 65536)


def options(s, box, actor, wid, *, policy=DEFAULT_POLICY):
    w = owner(s, box, actor, wid)
    cs = list(
        s.scalars(
            select(FinanceConnectionVersion)
            .where(
                FinanceConnectionVersion.owner_id == actor, FinanceConnectionVersion.box_id == box
            )
            .order_by(FinanceConnectionVersion.id)
            .limit(51)
        )
    )
    ms = list(
        s.scalars(
            select(FinanceCustomerVersion)
            .where(
                FinanceCustomerVersion.owner_id == actor,
                FinanceCustomerVersion.box_id == box,
                FinanceCustomerVersion.patient_link_id == w.patient_link_id,
            )
            .order_by(FinanceCustomerVersion.id)
            .limit(51)
        )
    )
    if len(cs) > 50 or len(ms) > 50:
        error("finance_history_limit")
    note = note_review._latest(s, wid)
    reviewed_source = (
        {
            "kind": "reviewed_note",
            "note_id": note.id,
            "content_sha256": note.content_hash,
            "source_fingerprint": note.source_fingerprint,
        }
        if note
        and note.source_fingerprint == note_review.source_fingerprint(s, wid, w.revision)
        and s.scalar(select(WorkspaceNoteReview.id).where(WorkspaceNoteReview.note_id == note.id))
        else None
    )
    final_authority(s)
    return public.bounded(
        schema.FinanceOptions.model_validate(
            {
                "contract_version": 1,
                "workspace_id": wid,
                "expected_workspace_revision": w.revision,
                "source": reviewed_source,
                "enabled": policy.enabled,
                "connections": [setup.connection_view(c) for c in cs],
                "customers": [setup.customer_view(m) for m in ms],
            }
        ).public(),
        65536,
    )


def propose(s, box, actor, wid, request, *, policy=DEFAULT_POLICY, core_checked=None):
    w = owner(s, box, actor, wid, writing=True)
    old, digest = receipt(s, w, actor, "propose", request)
    if old:
        final_authority(s)
        return response(s, old)
    if not policy.enabled:
        error("finance_feature_disabled", 403)
    if w.revision != request.expected_workspace_revision:
        error("finance_source_changed")
    n = source(s, w, request.source, core_checked)
    c, m, selection, cv, mv = selected(s, w, request.connection, request.customer)
    if (
        s.scalar(
            select(func.count())
            .select_from(FinanceWorkRevision)
            .where(FinanceWorkRevision.workspace_id == wid)
        )
        >= 100
    ):
        error("finance_history_limit")
    if any(
        value in request.expected_outcome
        for value in (str(selection.credential_ref), selection.remote_account_id, m.customer_id)
    ):
        error("finance_private_text_forbidden")
    if (
        s.scalar(
            select(FinanceWorkRevision.action_revision_id).where(
                FinanceWorkRevision.intended_operation_id == request.proposed_operation_id
            )
        )
        or s.get(Operation, request.proposed_operation_id) is not None
    ):
        error("finance_revision_changed")
    revision_number = 1
    if request.revises is not None:
        revise = request.revises
        t, prior, _ = bound(s, w, revise.ticket_id)
        if (t.version, prior.action_revision_id, prior.payload_hash) != (
            revise.expected_version,
            revise.revision_id,
            revise.payload_hash,
        ) or t.state not in {"pending_approval", "approved"}:
            error("finance_revision_changed")
        if s.get(FinanceSubmitClaim, prior.intended_operation_id) is not None:
            error("finance_submit_already_claimed")
        if prior.revision_number >= 20:
            error("finance_history_limit")
        old_operation = s.scalar(
            select(Operation).where(Operation.id == prior.intended_operation_id).with_for_update()
        )
        if old_operation is not None:
            if old_operation.attempt_count != 0 or old_operation.status != "pending":
                error("finance_submit_already_claimed")
            old_operation.status, old_operation.completed_at = "cancelled", common._clock(s)
        tid, revision_number = t.id, prior.revision_number + 1
    else:
        tid = str(uuid4())
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
    rid, expiry = str(uuid4()), common._clock(s) + timedelta(minutes=15)
    command = private.VendorCommand(
        selection=selection,
        operation_id=request.proposed_operation_id,
        revision_id=UUID(rid),
        expires_at=expiry,
        intent=private.StripePaymentIntentIntent(
            customer_id=m.customer_id, amount=request.amount, currency=request.currency
        ),
    )
    review = schema.FinanceReview(
        ticket_id=tid,
        revision_id=rid,
        operation_id=request.proposed_operation_id,
        connection=schema.FinanceConnectionView.model_validate(cv),
        customer=schema.FinanceCustomerView.model_validate(mv),
        source=request.source,
        amount=request.amount,
        currency=request.currency,
        due_date=request.due_date,
        expected_outcome=request.expected_outcome,
        expires_at=public.timestamp(expiry),
        processor_confirmation="not_requested",
    ).public()
    rsha = public.public_digest("cosmas-finance-review.v1", review)
    envelope = {
        "action": "payment_request.create",
        "private_command_sha256": command.commitment(),
        "review_sha256": rsha,
        "request_sha256": digest,
        "mapping_sha256": m.mapping_sha256,
        "operation_id": request.proposed_operation_id,
    }
    a = ActionRevision(
        id=rid,
        ticket_id=tid,
        box_id=box,
        revision_number=revision_number,
        action_type="payment_request.create",
        target_ref="finance_work:" + tid,
        content=CONTENT,
        payload=envelope,
        payload_hash=payload_hash(envelope),
        automation_class="hitl_required",
        policy_version="finance-human-review-v1",
        charter_version="private-finance-v1",
        config_version="finance-v1",
        created_by_principal_id=actor,
    )
    s.add(a)
    s.flush()
    t.current_revision_id = rid
    if request.revises is not None:
        # Version/state and current revision must change in the same row update.
        t.state, t.version, t.closed_at = "pending_approval", t.version + 1, None
    r = FinanceWorkRevision(
        action_revision_id=rid,
        ticket_id=tid,
        box_id=box,
        owner_id=actor,
        workspace_id=wid,
        patient_link_id=w.patient_link_id,
        revision_number=revision_number,
        source_workspace_revision=w.revision,
        note_id=n.id,
        content_hash=n.content_hash,
        source_fingerprint=n.source_fingerprint,
        intended_operation_id=request.proposed_operation_id,
        connection_version_id=c.id,
        customer_version_id=m.id,
        amount=request.amount,
        currency=request.currency,
        payload_hash=a.payload_hash,
        request_sha256=digest,
        review_sha256=rsha,
        private_command_sha256=command.commitment(),
        private_command=command.model_dump(mode="json"),
        public_proposal=request.public(),
        public_review=review,
        expires_at=expiry,
    )
    s.add(r)
    s.flush()
    saved = record(s, w, actor, "propose", request, digest, t, r, "proposed")
    s.commit()
    return response(s, saved)


def decide(s, box, actor, wid, tid, request, *, policy=DEFAULT_POLICY, core_checked=None):
    w = owner(s, box, actor, wid, writing=True)
    old, digest = receipt(s, w, actor, "decide", request)
    if old:
        if old.ticket_id != tid:
            error("finance_idempotency_conflict")
        final_authority(s)
        return response(s, old)
    if not policy.enabled:
        error("finance_feature_disabled", 403)
    t, r, command = bound(s, w, tid)
    check_bound(t, r, request)
    if t.state != "pending_approval" or request.review_sha256 != r.review_sha256:
        error("finance_revision_changed")
    if request.choice == "approve":
        proposal = schema.FinanceProposal.model_validate(r.public_proposal)
        source(s, w, proposal.source, core_checked)
        selected(s, w, proposal.connection, proposal.customer)
        if common._clock(s) >= command.expires_at:
            error("finance_approval_expired")
    t.state, t.version = ("approved" if request.choice == "approve" else "rejected"), t.version + 1
    s.add(
        Decision(
            box_id=box,
            ticket_id=tid,
            action_revision_id=r.action_revision_id,
            actor_principal_id=actor,
            kind=request.choice,
        )
    )
    saved = record(s, w, actor, "decide", request, digest, t, r, t.state)
    if request.choice == "approve":
        s.add(
            Operation(
                id=r.intended_operation_id,
                box_id=box,
                ticket_id=tid,
                action_revision_id=r.action_revision_id,
                idempotency_key="os-finance:" + r.intended_operation_id,
                adapter=ADAPTER,
                status="pending",
                attempt_count=0,
            )
        )
    s.commit()
    return response(s, saved)


def record_result(s, box, actor, wid, tid, request):
    w = owner(s, box, actor, wid, writing=True)
    old, digest = receipt(s, w, actor, "result", request)
    if old:
        if old.ticket_id != tid:
            error("finance_idempotency_conflict")
        final_authority(s)
        return response(s, old)
    t, r, command = bound(s, w, tid)
    check_bound(t, r, request)
    if t.state != "approved":
        error("finance_revision_changed")
    if not isinstance(command.intent, private.StripePaymentIntentIntent):
        error("finance_unavailable", 503)
    if evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
        error("finance_evidence_changed")
    if any(
        value in request.evidence
        for value in (
            str(command.selection.credential_ref),
            command.selection.remote_account_id,
            command.intent.customer_id,
        )
    ):
        error("finance_private_text_forbidden")
    t.version += 1
    saved = record(
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
    )
    s.commit()
    return response(s, saved)


def verify(s, box, actor, wid, tid, request):
    w = owner(s, box, actor, wid, writing=True)
    old, digest = receipt(s, w, actor, "verify", request)
    if old:
        if old.ticket_id != tid:
            error("finance_idempotency_conflict")
        final_authority(s)
        return response(s, old)
    t, r, _ = bound(s, w, tid)
    check_bound(t, r, request)
    result = latest_result(s, r)
    if (
        t.state != "approved"
        or result is None
        or (result.id, result.receipt_sha256)
        != (request.result_receipt_id, request.result_receipt_sha256)
    ):
        error("finance_result_changed")
    if evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
        error("finance_evidence_changed")
    state = summary(s, t, r)
    manual = result.result_payload["disposition"] == "verified_in_processor"
    if (
        result.result_payload["disposition"] in {"reported_unpaid", "unable_to_establish"}
        or request.reviewed_conflicting_evidence != state["conflicting_evidence"]
        or not manual
        and (
            state["conflicting_evidence"]
            or state["payment_state"] != "succeeded"
            or state["amount_received"] != r.amount
        )
    ):
        error("finance_exception_unresolved")
    t.state, t.closed_at, t.version = "closed", common._clock(s), t.version + 1
    saved = record(s, w, actor, "verify", request, digest, t, r, "verified", result_receipt=result)
    s.commit()
    return response(s, saved)


def resolve(s, box, actor, wid, request):
    w = owner(s, box, actor, wid)
    row = s.scalar(
        select(FinanceReceipt).where(
            FinanceReceipt.workspace_id == wid,
            FinanceReceipt.actor_id == actor,
            FinanceReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row and (
        row.command_kind != request.command_kind or row.request_sha256 != request.request_sha256
    ):
        error("finance_idempotency_conflict")
    final_authority(s)
    return (
        response(s, row)
        if row
        else schema.FinanceResponse.model_validate(
            {
                "contract_version": 1,
                "scope": {"kind": "workspace", "id": w.id},
                **request.public(),
                "outcome": "not_found",
                "effect": None,
                "receipt_sha256": None,
                "observed_at": public.timestamp(common._clock(s)),
            }
        ).public()
    )


def withdraw(s, box, actor, wid, tid, request):
    w = owner(s, box, actor, wid, writing=True)
    old, digest = receipt(s, w, actor, "withdraw", request)
    if old:
        if old.ticket_id != tid:
            error("finance_idempotency_conflict")
        final_authority(s)
        return response(s, old)
    t, r, _ = bound(s, w, tid)
    check_bound(t, r, request)
    if s.get(FinanceSubmitClaim, r.intended_operation_id):
        error("finance_submit_already_claimed")
    if t.state not in {"pending_approval", "approved"}:
        error("finance_revision_changed")
    op = s.get(Operation, r.intended_operation_id)
    if op:
        op.status, op.completed_at = "cancelled", common._clock(s)
    t.state, t.version = "withdrawn", t.version + 1
    saved = record(s, w, actor, "withdraw", request, digest, t, r, "withdrawn")
    s.commit()
    return response(s, saved)


def observations(s, box, actor, wid, tid, cursor=None):
    w = owner(s, box, actor, wid)
    _, r, _ = bound(s, w, tid)
    scope = {"owner": actor, "workspace": wid, "ticket": tid, "kind": "observations"}
    after = paging.decode(scope, cursor)
    if after is not None and (type(after) is not int or after < 0):
        error("invalid_finance_request", 400)
    rows = list(
        s.scalars(
            select(FinanceObservation)
            .where(
                FinanceObservation.operation_id == r.intended_operation_id,
                FinanceObservation.sequence > (after or 0),
            )
            .order_by(FinanceObservation.sequence)
            .limit(21)
        )
    )
    final_authority(s)
    return public.bounded(
        schema.FinanceObservations.model_validate(
            {
                "contract_version": 1,
                "workspace_id": wid,
                "ticket_id": tid,
                "operation_id": r.intended_operation_id,
                "observations": [row.public_observation for row in rows[:20]],
                "observation_head": head(s, r),
                "next_cursor": paging.encode(scope, rows[19].sequence) if len(rows) > 20 else None,
            }
        ).public(),
        65536,
    )


def catalog(s, box, actor, wid, cursor=None):
    owner(s, box, actor, wid)
    scope = {"owner": actor, "workspace": wid, "kind": "catalog"}
    after = paging.decode(scope, cursor)
    if after is not None:
        try:
            public._uuid(after)
        except ValueError:
            error("invalid_finance_request", 400)
    query = (
        select(Ticket, FinanceWorkRevision)
        .join(
            FinanceWorkRevision,
            FinanceWorkRevision.action_revision_id == Ticket.current_revision_id,
        )
        .where(
            FinanceWorkRevision.workspace_id == wid,
            FinanceWorkRevision.box_id == box,
            FinanceWorkRevision.owner_id == actor,
        )
    )
    if after:
        query = query.where(Ticket.id > after)
    rows = list(s.execute(query.order_by(Ticket.id).limit(26)))
    final_authority(s)
    return public.bounded(
        schema.FinanceCatalog.model_validate(
            {
                "contract_version": 1,
                "workspace_id": wid,
                "items": [summary(s, t, r) for t, r in rows[:25]],
                "next_cursor": paging.encode(scope, rows[24][0].id) if len(rows) > 25 else None,
            }
        ).public(),
        65536,
    )
