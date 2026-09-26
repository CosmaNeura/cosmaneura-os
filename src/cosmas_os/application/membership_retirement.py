"""Retire only a locally provable rejection, serialized with exact admission."""

import json
from uuid import uuid4

from sqlalchemy import text

from cosmas_os.api import membership_retirement_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import membership_work as work
from cosmas_os.application import vendor_work as common
from cosmas_os.membership_models import MembershipCommandRetirement


def response(row):
    value = dict(row.response)
    digest = public.public_digest("cosmas-membership-retirement.v1", value)
    if digest != row.receipt_sha256:
        work.error("membership_unavailable", 503)
    return public.bounded(
        schema.MembershipRetirementResponse.model_validate(
            {**value, "receipt_sha256": digest}
        ).public(),
        8192,
    )


def retire(s, box, actor, wid, request, *, policy=work.DEFAULT_POLICY):
    w = work.owner(s, box, actor, wid, policy=policy, writing=True)
    original = request.request
    if len(public.canonical(original.public())) > 8192:
        work.error("invalid_membership_request", 413)
    old, digest = work.saved(s, w, request.command_kind, original)
    if digest != request.request_sha256:
        work.error("membership_idempotency_conflict")
    if old is not None:
        work.final_authority(s)
        return work.response(old)
    # This read-only SQL guard is shared with the table's insertion guard. It
    # recognizes a strict local subset of admission failures. Missing authority,
    # a Core/service outage, and a currently admissible request cannot qualify.
    reason = s.scalar(
        text("SELECT public.membership_rejection_reason(:wid, :kind, CAST(:request AS jsonb))"),
        {"wid": wid, "kind": request.command_kind, "request": json.dumps(original.public())},
    )
    if reason is None:
        work.error("membership_retirement_unavailable")
    now, rid = common._clock(s), str(uuid4())
    value = {
        "contract_version": 1,
        "scope": work.scope(w),
        "command_kind": request.command_kind,
        "idempotency_key": original.idempotency_key,
        "request_sha256": digest,
        "outcome": "retired",
        "effect": None,
        "retirement": {"receipt_id": rid, "reason": reason, "retired_at": public.timestamp(now)},
    }
    row = MembershipCommandRetirement(
        id=rid,
        box_id=box,
        owner_id=actor,
        workspace_id=wid,
        ticket_id=None if request.command_kind == "propose" else original.ticket_id,
        command_kind=request.command_kind,
        idempotency_key=original.idempotency_key,
        request=original.public(),
        request_sha256=digest,
        reason=reason,
        response=value,
        receipt_sha256=public.public_digest("cosmas-membership-retirement.v1", value),
        retired_at=now,
    )
    s.add(row)
    work.final_authority(s)
    s.flush()
    work.final_authority(s)
    s.commit()
    return response(row)
