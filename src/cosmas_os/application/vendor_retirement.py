"""Serialize permanent retirement with original exact command admission."""

from uuid import uuid4

from cosmas_os.api import vendor_retirement_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_work as work
from cosmas_os.vendor_models import VendorWorkRevision
from cosmas_os.vendor_retirement_models import VendorCommandRetirement


def response(s, row):
    envelope = {
        "scope": {"kind": "workspace", "id": row.workspace_id},
        "command_kind": row.command_kind,
        "idempotency_key": row.idempotency_key,
        "request_sha256": row.request_sha256,
        "retirement": {k: v for k, v in row.public_retirement.items() if k != "receipt_sha256"},
    }
    if (
        public.public_digest("cosmas-vendor-public-retirement.v1", envelope) != row.receipt_sha256
        or row.public_retirement.get("receipt_sha256") != row.receipt_sha256
    ):
        work.error("vendor_unavailable", 503)
    work._final_authority(s)
    return public.bounded(
        schema.RetirementResponse.model_validate(
            {
                "contract_version": 1,
                **envelope,
                "retirement": row.public_retirement,
                "outcome": "retired",
                "effect": None,
                "summary": None,
                "observed_at": public.timestamp(work._clock(s)),
            }
        ).public(),
        16384,
    )


def retire(s, box, actor, wid, tid, request):
    w = work._owner(s, box, actor, wid, writing=True)
    request = schema.VendorRetire.model_validate(request.public())
    # The same owner/workspace locks are held by every original admission.
    # Exact recorded admission wins; retirement never cancels an existing effect.
    saved, digest = work._receipt(s, w, actor, request.command_kind, request.request)
    if digest != request.request_sha256:
        work.error("vendor_idempotency_conflict")
    if saved is not None:
        if saved.ticket_id != tid:
            work.error("vendor_idempotency_conflict")
        work._final_authority(s)
        return work.command_response(s, saved)
    r = s.get(VendorWorkRevision, request.request.revision_id)
    if r is None or (
        r.box_id,
        r.owner_id,
        r.workspace_id,
        r.ticket_id,
        r.intended_operation_id,
        r.payload_hash,
    ) != (box, actor, wid, tid, request.request.operation_id, request.request.payload_hash):
        work.error("vendor_work_unavailable", 404)
    # Historical owned revisions may be retired without fresh clinical/vendor
    # authority: the only durable effect is blocking this exact unadmitted key.
    now, rid = work._clock(s), str(uuid4())
    retired = {
        "receipt_id": rid,
        "ticket_id": tid,
        "revision_id": r.action_revision_id,
        "operation_id": r.intended_operation_id,
        "payload_hash": r.payload_hash,
        "retired_at": public.timestamp(now),
    }
    sha = public.public_digest(
        "cosmas-vendor-public-retirement.v1",
        {
            "scope": {"kind": "workspace", "id": wid},
            "command_kind": request.command_kind,
            "idempotency_key": request.request.idempotency_key,
            "request_sha256": digest,
            "retirement": retired,
        },
    )
    row = VendorCommandRetirement(
        id=rid,
        box_id=box,
        owner_id=actor,
        workspace_id=wid,
        actor_id=actor,
        ticket_id=tid,
        action_revision_id=r.action_revision_id,
        operation_id=r.intended_operation_id,
        command_kind=request.command_kind,
        idempotency_key=request.request.idempotency_key,
        request_sha256=digest,
        payload_hash=r.payload_hash,
        public_request=request.request.public(),
        public_retirement={**retired, "receipt_sha256": sha},
        receipt_sha256=sha,
        retired_at=now,
    )
    s.add(row)
    work._final_authority(s)
    s.flush()
    work._final_authority(s)
    s.commit()
    return response(s, row)
