"""Reviewed portal actions on F8. Local commands never call a provider."""

from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from cosmas_os.adapters.vendor_connectors.transport import require_reference
from cosmas_os.api import portal_work_schemas as schema
from cosmas_os.api.vendor_work_schemas import public_digest, timestamp
from cosmas_os.application import portal_setup as setup
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ActionRevision, AuditEvent, Decision, Operation, Ticket
from cosmas_os.portal_work_models import (
    PortalWork,
    PortalWorkClaim,
    PortalWorkObservation,
    PortalWorkReceipt,
)
from cosmas_os.ports import vendor_connectors as private

LANE = "encounter_portal_work"
ADAPTER = "workspace_portal"
CONTENT = "Portal action — private review"


@dataclass(frozen=True)
class PortalWorkPolicy:
    enabled: bool = False
    io_enabled: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.io_enabled) is not bool:
            raise ValueError("Explicit flags required")


DEFAULT_POLICY = PortalWorkPolicy()


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


def owner(s, box, actor, wid, writing=False):
    return common._owner(s, box, actor, wid, writing=writing)


def fence(s):
    check = s.info.get("portal_work_authority")
    if check is not None:
        check()


def gate(policy):
    if not settings.workspace_available or not policy.enabled:
        error("portal_work_disabled", 403)


def clock(s):
    return common._clock(s)


def scope(w):
    return {"kind": "workspace", "id": w.id}


def old_receipt(s, w, kind, request):
    sha = schema.request_digest(w.id, kind, request)
    old = s.scalar(
        select(PortalWorkReceipt).where(
            PortalWorkReceipt.workspace_id == w.id,
            PortalWorkReceipt.owner_id == w.owner_id,
            PortalWorkReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if old and (old.command_kind != kind or old.request_sha256 != sha):
        error("portal_work_idempotency_conflict")
    return old, sha


def response(row):
    value = row.response
    if (
        value.get("receipt_sha256") != row.receipt_sha256
        or public_digest(
            "cosmas-portal-work-receipt.v1",
            {k: v for k, v in value.items() if k != "receipt_sha256"},
        )
        != row.receipt_sha256
    ):
        error("portal_work_integrity", 503)
    return value


def record(s, w, kind, request, sha, t, r, effect):
    s.flush()
    fence(s)
    rid = str(uuid4())
    now = clock(s)
    value = {
        "contract_version": 1,
        "outcome": "recorded",
        "scope": scope(w),
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": sha,
        "effect": {
            "receipt_id": rid,
            "ticket_id": t.id,
            "revision_id": r.action_revision_id,
            "operation_id": r.operation_id,
            "payload_hash": r.payload_hash,
            "version": t.version,
            "state": t.state,
            "effect": effect,
            "recorded_at": timestamp(now),
        },
    }
    receipt_sha = public_digest("cosmas-portal-work-receipt.v1", value)
    value["receipt_sha256"] = receipt_sha
    row = PortalWorkReceipt(
        id=rid,
        box_id=w.box_id,
        owner_id=w.owner_id,
        workspace_id=w.id,
        ticket_id=t.id,
        version=t.version,
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        request=request.public(),
        request_sha256=sha,
        response=value,
        receipt_sha256=receipt_sha,
        recorded_at=now,
    )
    s.add(row)
    s.add(
        AuditEvent(
            box_id=w.box_id,
            aggregate_type="ticket",
            aggregate_id=t.id,
            event_type="portal_work." + kind,
            actor_principal_id=w.owner_id,
            action_revision_id=r.action_revision_id,
            payload_hash=r.payload_hash,
            outcome=effect,
            detail={"operation_id": r.operation_id, "receipt_id": rid},
        )
    )
    s.flush()
    fence(s)
    return row


def bound(s, w, tid, request=None):
    t = s.scalar(
        select(Ticket)
        .where(Ticket.id == tid, Ticket.box_id == w.box_id, Ticket.lane == LANE)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    r = s.get(PortalWork, tid)
    if (
        t is None
        or r is None
        or (r.workspace_id, r.owner_id, r.box_id) != (w.id, w.owner_id, w.box_id)
    ):
        error("portal_work_unavailable", 404)
    a = s.get(ActionRevision, r.action_revision_id)
    command = private.VendorCommand.model_validate(r.private_command)
    if (
        t.current_revision_id != r.action_revision_id
        or a is None
        or a.invalidated
        or a.payload_hash != r.payload_hash
        or payload_hash(a.payload) != r.payload_hash
        or command.commitment() != r.command_sha256
        or public_digest("cosmas-portal-work-review.v1", r.review) != r.review_sha256
    ):
        error("portal_work_integrity", 503)
    if request and (
        request.expected_version,
        request.revision_id,
        request.operation_id,
        request.payload_hash,
    ) != (t.version, r.action_revision_id, r.operation_id, r.payload_hash):
        error("portal_work_changed")
    return t, r, command


def current(s, w, r, catalog, core_checked=None, reading=False):
    proposal = schema.Proposal.model_validate(r.proposal)
    if not reading:
        common._source(s, w, proposal.source, core_checked)
        common._artifact(s, w, proposal.document, proposal.source)
    d = setup.detail(s, w.box_id, w.owner_id, r.setup_connection_id, catalog)
    if (
        not d["usable_locally"]
        or d["revision_id"] != r.setup_revision_id
        or not reading
        and d["version"] != r.setup_version
        or d["review"]["mappings"]["patient_link_id"] != w.patient_link_id
    ):
        error("portal_work_mapping_changed")
    selected, correspondence, _ = setup.active_correspondence(
        s,
        w.box_id,
        w.owner_id,
        r.setup_connection_id,
        "referral.read" if reading else r.action,
        catalog,
    )
    command = private.VendorCommand.model_validate(r.private_command)
    if (
        selected != command.selection
        or not isinstance(command.intent, private.PortalIntent)
        or command.intent.correspondence != correspondence
        or command.intent.profile_sha256 != d["review"]["profile_sha256"]
    ):
        error("portal_work_mapping_changed")
    if not reading and clock(s) >= r.expires_at:
        error("portal_work_approval_expired")
    return command


def head(s, r):
    row = s.scalar(
        select(PortalWorkObservation)
        .where(PortalWorkObservation.ticket_id == r.ticket_id)
        .order_by(PortalWorkObservation.sequence.desc())
        .limit(1)
    )
    return (
        {"sequence": row.sequence, "sha256": row.head_sha256}
        if row
        else {
            "sequence": 0,
            "sha256": public_digest(
                "cosmas-portal-work-head.v1", {"operation_id": r.operation_id, "sequence": 0}
            ),
        }
    )


def latest_result(s, r):
    return s.scalar(
        select(PortalWorkReceipt)
        .where(
            PortalWorkReceipt.ticket_id == r.ticket_id, PortalWorkReceipt.command_kind == "result"
        )
        .order_by(PortalWorkReceipt.version.desc())
        .limit(1)
    )


def evidence(s, r):
    h = head(s, r)
    result = latest_result(s, r)
    return h, public_digest(
        "cosmas-portal-work-evidence.v1",
        {
            "operation_id": r.operation_id,
            "observation_head": h,
            "result_receipt_id": result.id if result else None,
            "result_receipt_sha256": result.receipt_sha256 if result else None,
        },
    )


def states(s, r):
    rows = list(
        s.scalars(
            select(PortalWorkObservation)
            .where(PortalWorkObservation.ticket_id == r.ticket_id)
            .order_by(PortalWorkObservation.sequence)
        )
    )
    submissions = [o for o in rows if o.public_observation["mode"] == "submit"]
    statuses = [o for o in rows if o.public_observation["mode"] == "status"]
    accepted = {o.public_observation["state"] for o in submissions}
    terminals = {o.public_observation["state"] for o in statuses} & {"received", "declined"}
    conflict = len(accepted & {"accepted", "rejected"}) > 1 or len(terminals) > 1
    acceptance = (
        "accepted"
        if accepted == {"accepted"}
        else "rejected"
        if accepted == {"rejected"}
        else "unknown"
        if submissions
        else "not_observed"
    )
    state = statuses[-1].public_observation["state"] if statuses else "not_observed"
    if conflict:
        state = "unknown"
    claim = s.scalar(
        select(PortalWorkClaim).where(
            PortalWorkClaim.operation_id == r.operation_id, PortalWorkClaim.mode == "submit"
        )
    )
    return {
        "submit_claimed": claim is not None,
        "acceptance": acceptance,
        "referral_status": state,
        "conflicting_evidence": conflict,
        "provider_requirement_met": acceptance == "accepted"
        and not conflict
        and (r.action == "document.upload" or state == "received"),
    }


def accepted_upload(s, w, operation, document, source, setup_revision):
    r = s.scalar(
        select(PortalWork).where(
            PortalWork.operation_id == operation,
            PortalWork.workspace_id == w.id,
            PortalWork.box_id == w.box_id,
            PortalWork.owner_id == w.owner_id,
        )
    )
    if (
        r is None
        or r.action != "document.upload"
        or r.artifact_id != document.artifact_id
        or r.setup_revision_id != setup_revision
        or (r.note_id, r.content_hash, r.source_fingerprint)
        != (source.note_id, source.content_sha256, source.source_fingerprint)
        or states(s, r)["acceptance"] != "accepted"
    ):
        error("portal_work_upload_unavailable")
    command = private.VendorCommand.model_validate(r.private_command)
    if not isinstance(
        command.intent, private.PortalDocumentIntent
    ) or command.intent.document != private.DocumentBinding.model_validate(document.public()):
        error("portal_work_upload_unavailable")
    row = s.scalar(
        select(PortalWorkObservation)
        .where(
            PortalWorkObservation.ticket_id == r.ticket_id,
            PortalWorkObservation.kind == "submission",
        )
        .order_by(PortalWorkObservation.sequence.desc())
        .limit(1)
    )
    if row is None:
        error("portal_work_upload_unavailable")
    observed = private.SubmissionObservation.model_validate(row.private_observation)
    if observed.reference is None:
        error("portal_work_upload_unavailable")
    return require_reference(command, observed.reference, "portal_document")


def propose(
    s,
    box,
    actor,
    wid,
    request,
    *,
    catalog=setup.EMPTY_CATALOG,
    policy=DEFAULT_POLICY,
    core_checked=None,
):
    request = schema.Proposal.model_validate(request.public())
    w = owner(s, box, actor, wid, True)
    old, sha = old_receipt(s, w, "propose", request)
    if old:
        return response(old)
    gate(policy)
    if w.revision != request.expected_workspace_revision:
        error("portal_work_source_changed")
    note = common._source(s, w, request.source, core_checked)
    common._artifact(s, w, request.document, request.source)
    d = setup.detail(s, box, actor, request.setup.connection_id, catalog)
    if (d["revision_id"], d["version"], d["review_sha256"]) != (
        request.setup.revision_id,
        request.setup.version,
        request.setup.review_sha256,
    ) or d["review"]["mappings"]["patient_link_id"] != w.patient_link_id:
        error("portal_work_mapping_changed")
    selection, correspondence, _ = setup.active_correspondence(
        s, box, actor, request.setup.connection_id, request.action, catalog
    )
    if (
        s.scalar(select(func.count()).select_from(PortalWork).where(PortalWork.workspace_id == wid))
        >= 100
    ):
        error("portal_work_history_limit")
    document = private.DocumentBinding.model_validate(request.document.public())
    args = {
        "portal_id": d["review"]["portal_id"],
        "profile_sha256": d["review"]["profile_sha256"],
        "correspondence": correspondence,
    }
    if request.action == "document.upload":
        intent = private.PortalDocumentIntent(**args, document=document)
    else:
        ref = accepted_upload(
            s, w, request.uploaded_operation_id, request.document, request.source, d["revision_id"]
        )
        if request.summary is None:
            error("invalid_portal_work_request", 422)
        intent = private.PortalReferralIntent(
            **args,
            summary=request.summary,
            attachment=private.PortalAttachment(document=document, reference=ref),
        )
    tid, rid = str(uuid4()), str(uuid4())
    expiry = clock(s) + timedelta(hours=24)
    command = private.VendorCommand(
        selection=selection,
        operation_id=UUID(request.proposed_operation_id),
        revision_id=UUID(rid),
        expires_at=expiry,
        intent=intent,
    )
    review = {
        "ticket_id": tid,
        "revision_id": rid,
        "operation_id": request.proposed_operation_id,
        "action": request.action,
        "setup": request.setup.public(),
        "profile_label": d["review"]["profile_label"],
        "mappings": d["review"]["mappings"],
        "source": request.source.public(),
        "document": request.document.public(),
        "due_date": request.due_date,
        "expected_outcome": request.expected_outcome,
        "expires_at": timestamp(expiry),
    }
    if request.summary is not None:
        review["summary"] = request.summary
    if request.uploaded_operation_id:
        review["uploaded_operation_id"] = request.uploaded_operation_id
    review_sha = public_digest("cosmas-portal-work-review.v1", review)
    envelope = {
        "action": "portal_work." + request.action,
        "operation_id": request.proposed_operation_id,
        "command_sha256": command.commitment(),
        "review_sha256": review_sha,
        "request_sha256": sha,
    }
    ph = payload_hash(envelope)
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
    s.add(
        ActionRevision(
            id=rid,
            ticket_id=tid,
            box_id=box,
            revision_number=1,
            action_type="portal_work." + request.action,
            target_ref="portal_work:" + tid,
            content=CONTENT,
            payload=envelope,
            payload_hash=ph,
            automation_class="hitl_required",
            policy_version="portal-review-v1",
            charter_version="private-portal-v1",
            config_version="portal-work-1",
            created_by_principal_id=actor,
        )
    )
    s.flush()
    t.current_revision_id = rid
    s.flush()
    r = PortalWork(
        ticket_id=tid,
        action_revision_id=rid,
        operation_id=request.proposed_operation_id,
        box_id=box,
        owner_id=actor,
        workspace_id=wid,
        note_id=note.id,
        content_hash=note.content_hash,
        source_fingerprint=note.source_fingerprint,
        payload_hash=ph,
        action=request.action,
        setup_connection_id=request.setup.connection_id,
        setup_revision_id=request.setup.revision_id,
        setup_version=request.setup.version,
        artifact_id=request.document.artifact_id,
        uploaded_operation_id=request.uploaded_operation_id,
        private_command=command.model_dump(mode="json"),
        command_sha256=command.commitment(),
        proposal=request.public(),
        request_sha256=sha,
        review=review,
        review_sha256=review_sha,
        expires_at=expiry,
    )
    s.add(r)
    s.flush()
    receipt = record(s, w, "propose", request, sha, t, r, "proposed")
    s.commit()
    return response(receipt)


def local_command(
    s,
    box,
    actor,
    wid,
    tid,
    kind,
    request,
    *,
    catalog=setup.EMPTY_CATALOG,
    policy=DEFAULT_POLICY,
    core_checked=None,
):
    if kind not in {"decide", "withdraw", "result", "verify"}:
        error("invalid_portal_work_request", 422)
    request = schema.COMMANDS[kind].model_validate(request.public())
    w = owner(s, box, actor, wid, True)
    old, sha = old_receipt(s, w, kind, request)
    if old:
        if old.ticket_id != tid:
            error("portal_work_idempotency_conflict")
        return response(old)
    t, r, command = bound(s, w, tid, request)
    if kind == "decide":
        if t.state != "pending_approval" or request.review_sha256 != r.review_sha256:
            error("portal_work_changed")
        if request.choice == "approve":
            gate(policy)
            current(s, w, r, catalog, core_checked)
        t.state = "approved" if request.choice == "approve" else "rejected"
        s.add(
            Decision(
                box_id=box,
                ticket_id=tid,
                action_revision_id=r.action_revision_id,
                actor_principal_id=actor,
                kind=request.choice,
            )
        )
        if request.choice == "approve":
            s.add(
                Operation(
                    id=r.operation_id,
                    box_id=box,
                    ticket_id=tid,
                    action_revision_id=r.action_revision_id,
                    idempotency_key="portal-work:" + r.operation_id,
                    adapter=ADAPTER,
                    status="pending",
                    attempt_count=0,
                )
            )
        effect = t.state
    elif kind == "withdraw":
        if t.state not in {"pending_approval", "approved"} or states(s, r)["submit_claimed"]:
            error("portal_work_changed")
        t.state = "cancelled"
        op = s.get(Operation, r.operation_id)
        if op:
            op.status = "cancelled"
            op.completed_at = clock(s)
        effect = "withdrawn"
    else:
        if t.state != "approved":
            error("portal_work_changed")
        if evidence(s, r) != (request.observation_head.public(), request.evidence_sha256):
            error("portal_work_evidence_changed")
        if kind == "result":
            effect = "result_recorded"
        else:
            result = latest_result(s, r)
            if result is None or (result.id, result.receipt_sha256) != (
                request.result_receipt_id,
                request.result_receipt_sha256,
            ):
                error("portal_work_result_changed")
            if (
                result.request["disposition"] != "verified_in_portal"
                or result.request["observation_head"] != request.observation_head.public()
                or not states(s, r)["provider_requirement_met"]
            ):
                error("portal_work_exception_unresolved")
            t.state = "closed"
            t.closed_at = clock(s)
            effect = "verified"
    t.version += 1
    receipt = record(s, w, kind, request, sha, t, r, effect)
    s.commit()
    return response(receipt)


def current_result(w, t, r, row):
    """Disclose only the exact immutable result committed by its receipt."""
    if row is None:
        return None
    try:
        request = schema.Result.model_validate(row.request)
        receipt = response(row)
        effect = receipt["effect"]
        if (
            set(receipt)
            != {
                "contract_version",
                "outcome",
                "scope",
                "command_kind",
                "idempotency_key",
                "request_sha256",
                "effect",
                "receipt_sha256",
            }
            or receipt["contract_version"] != 1
            or set(effect)
            != {
                "receipt_id",
                "ticket_id",
                "revision_id",
                "operation_id",
                "payload_hash",
                "version",
                "state",
                "effect",
                "recorded_at",
            }
            or (row.box_id, row.owner_id, row.workspace_id, row.ticket_id, row.command_kind)
            != (w.box_id, w.owner_id, w.id, t.id, "result")
            or receipt["scope"] != scope(w)
            or receipt["outcome"] != "recorded"
            or receipt["command_kind"] != "result"
            or receipt["idempotency_key"] != row.idempotency_key
            or request.idempotency_key != row.idempotency_key
            or schema.request_digest(w.id, "result", request) != row.request_sha256
            or receipt["request_sha256"] != row.request_sha256
            or (
                effect["receipt_id"],
                effect["ticket_id"],
                effect["revision_id"],
                effect["operation_id"],
                effect["payload_hash"],
                effect["version"],
                effect["state"],
                effect["effect"],
                effect["recorded_at"],
            )
            != (
                row.id,
                t.id,
                r.action_revision_id,
                r.operation_id,
                r.payload_hash,
                row.version,
                "approved",
                "result_recorded",
                timestamp(row.recorded_at),
            )
            or (
                request.revision_id,
                request.operation_id,
                request.payload_hash,
                request.expected_version + 1,
            )
            != (r.action_revision_id, r.operation_id, r.payload_hash, row.version)
            or row.version > t.version
        ):
            error("portal_work_integrity", 503)
        return schema.CurrentResult(
            receipt_id=row.id,
            receipt_sha256=row.receipt_sha256,
            request_sha256=row.request_sha256,
            recorded_at=timestamp(row.recorded_at),
            request=request,
        ).public()
    except (ValidationError, KeyError, TypeError, ValueError):
        error("portal_work_integrity", 503)


def detail(s, box, actor, wid, tid, *, catalog=setup.EMPTY_CATALOG, include_current_result=True):
    w = owner(s, box, actor, wid)
    t, r, _ = bound(s, w, tid)
    h, sha = evidence(s, r)
    result = latest_result(s, r)
    value = {
        "contract_version": 1,
        "scope": scope(w),
        "ticket_id": tid,
        "version": t.version,
        "revision_id": r.action_revision_id,
        "operation_id": r.operation_id,
        "payload_hash": r.payload_hash,
        "state": t.state,
        "action": r.action,
        "review": r.review,
        "review_sha256": r.review_sha256,
        **states(s, r),
        "observation_head": h,
        "evidence_sha256": sha,
        "latest_result": response(result) if result else None,
        "verification": "verified" if t.state == "closed" else "pending",
    }
    if include_current_result:
        value["current_result"] = current_result(w, t, r, result)
    fence(s)
    return value


def catalog(s, box, actor, wid):
    w = owner(s, box, actor, wid)
    return {
        "contract_version": 1,
        "scope": scope(w),
        "items": [
            detail(s, box, actor, wid, r.ticket_id, include_current_result=False)
            for r in s.scalars(
                select(PortalWork)
                .where(
                    PortalWork.workspace_id == wid,
                    PortalWork.owner_id == actor,
                    PortalWork.box_id == box,
                )
                .order_by(PortalWork.ticket_id)
                .limit(100)
            )
        ],
    }


def resolve(s, box, actor, wid, request):
    request = schema.Resolve.model_validate(request.public())
    w = owner(s, box, actor, wid)
    row = s.scalar(
        select(PortalWorkReceipt).where(
            PortalWorkReceipt.workspace_id == wid,
            PortalWorkReceipt.owner_id == actor,
            PortalWorkReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row:
        if (row.command_kind, row.request_sha256) != (request.command_kind, request.request_sha256):
            error("portal_work_idempotency_conflict")
        return response(row)
    return {"contract_version": 1, "outcome": "not_found", "scope": scope(w), **request.public()}


def observations(s, box, actor, wid, tid):
    w = owner(s, box, actor, wid)
    _, r, _ = bound(s, w, tid)
    return {
        "contract_version": 1,
        "scope": scope(w),
        "ticket_id": tid,
        "head": head(s, r),
        "items": [
            o.public_observation
            for o in s.scalars(
                select(PortalWorkObservation)
                .where(PortalWorkObservation.ticket_id == tid)
                .order_by(PortalWorkObservation.sequence)
            )
        ],
    }
