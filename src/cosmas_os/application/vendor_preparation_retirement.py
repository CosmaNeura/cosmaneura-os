"""Exact preparation-key retirement; no cancellation, storage or provider I/O."""

from uuid import uuid4

from sqlalchemy import select

from cosmas_os.api import vendor_retirement_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_artifacts as artifacts
from cosmas_os.application import vendor_work as work
from cosmas_os.vendor_models import VendorArtifactAttempt
from cosmas_os.vendor_retirement_models import VendorPreparationRetirement

DOMAIN = "cosmas-vendor-public-preparation-retirement.v1"


def response(s, row):
    envelope = {
        "scope": {"kind": "workspace", "id": row.workspace_id},
        "command_kind": row.command_kind,
        "idempotency_key": row.idempotency_key,
        "request_sha256": row.request_sha256,
        "retirement": {k: v for k, v in row.public_retirement.items() if k != "receipt_sha256"},
    }
    request = schema.VendorPreparationRetire.model_validate({
        "command_kind": row.command_kind, "request": row.public_request,
        "request_sha256": row.request_sha256,
    }).request
    if (request.idempotency_key != row.idempotency_key
            or public.request_digest(row.command_kind, envelope["scope"], request) != row.request_sha256
            or public.public_digest(DOMAIN, envelope) != row.receipt_sha256
            or row.public_retirement.get("receipt_sha256") != row.receipt_sha256):
        work.error("vendor_unavailable", 503)
    model = (schema.PreparationCommandRetirementResponse if row.command_kind == "propose"
             else schema.PreparationArtifactRetirementResponse)
    body = {"contract_version": 1, **envelope, "retirement": row.public_retirement,
            "outcome": "retired", "effect": None,
            "summary" if row.command_kind == "propose" else "artifact": None,
            "observed_at": public.timestamp(work._clock(s))}
    work._final_authority(s)
    return public.bounded(model.model_validate(body).public(), 8192)


def retire(s, box, actor, wid, request):
    request = schema.VendorPreparationRetire.model_validate(request.public())
    limit = public.MAX_JSON if request.command_kind == "propose" else 2048
    if len(public.canonical(request.request.public())) > limit:
        work.error("invalid_vendor_request", 413)
    w = work._owner(s, box, actor, wid, writing=True)
    saved, digest = work._receipt(s, w, actor, request.command_kind, request.request)
    if digest != request.request_sha256:
        work.error("vendor_idempotency_conflict")
    if saved is not None:
        # An admitted content generation remains admitted, even when unfinished.
        work._final_authority(s)
        return (work.command_response(s, saved) if request.command_kind == "propose"
                else artifacts._response(s, w, saved))
    if request.command_kind == "artifact_content":
        row = artifacts._artifact(s, w, request.request.artifact_id, writing=True)
        q = request.request
        if (row.intent_sha256, row.sha256, row.byte_length, row.media_type) != (
                q.intent_sha256, q.sha256, q.byte_length, q.media_type):
            work.error("vendor_idempotency_conflict")
    # Normally every attempt has a receipt committed in the same transaction.
    # Fail closed on inconsistent custody instead of issuing a negative proof.
    if s.scalar(select(VendorArtifactAttempt.id).where(
            VendorArtifactAttempt.workspace_id == wid, VendorArtifactAttempt.actor_id == actor,
            VendorArtifactAttempt.idempotency_key == request.request.idempotency_key).limit(1)):
        work.error("vendor_unavailable", 503)
    now, rid = work._clock(s), str(uuid4())
    metadata = {"receipt_id": rid, "retired_at": public.timestamp(now)}
    sha = public.public_digest(DOMAIN, {"scope": work._scope(w),
        "command_kind": request.command_kind, "idempotency_key": request.request.idempotency_key,
        "request_sha256": digest, "retirement": metadata})
    row = VendorPreparationRetirement(id=rid, box_id=box, workspace_id=wid, owner_id=actor,
        actor_id=actor, command_kind=request.command_kind,
        idempotency_key=request.request.idempotency_key, request_sha256=digest,
        public_request=request.request.public(), public_retirement={**metadata, "receipt_sha256": sha},
        receipt_sha256=sha, retired_at=now)
    s.add(row)
    work._final_authority(s)
    s.flush()
    work._final_authority(s)
    s.commit()
    return response(s, row)
