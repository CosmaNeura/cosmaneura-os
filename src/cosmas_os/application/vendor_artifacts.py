"""Durable local artifact intent and fenced ingestion, never external submission.

The API owns its whole-pipeline deadline and streams no more than the saved
length plus one. These functions commit admission before storage I/O; internal
settlement preserves evidence after revocation without granting disclosure.
"""

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, get_args
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_work as work
from cosmas_os.models import AuditEvent, EncounterWorkspace, Principal
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError, VendorArtifactScope
from cosmas_os.vendor_models import VendorArtifact, VendorArtifactAttempt, VendorCommandReceipt
from cosmas_os.vendor_retirement_models import VendorPreparationRetirement

ContentOutcome = Literal["ready", "input_invalid", "stored_corrupt", "not_found", "unknown"]


@dataclass(frozen=True, repr=False)
class ContentToken:
    box_id: str
    workspace_id: str
    owner_id: str
    artifact_id: str
    attempt_id: str
    generation: int
    fence_token: str
    request_sha256: str
    scope: VendorArtifactScope

    def __repr__(self):
        return "ContentToken(<protected>)"


@dataclass(frozen=True, repr=False)
class ContentAdmission:
    token: ContentToken | None
    response: dict
    scope: VendorArtifactScope

    def __repr__(self):
        return "ContentAdmission(<protected>)"


@dataclass(frozen=True, repr=False)
class PreviewToken:
    box_id: str
    workspace_id: str
    owner_id: str
    artifact_id: str
    version: int
    scope: VendorArtifactScope

    def __repr__(self):
        return "PreviewToken(<protected>)"


def _artifact(s, w, aid, *, writing=False):
    row = s.scalar(select(VendorArtifact).where(VendorArtifact.artifact_id == aid,
        VendorArtifact.box_id == w.box_id, VendorArtifact.workspace_id == w.id,
        VendorArtifact.owner_id == w.owner_id).with_for_update(read=not writing)
        .execution_options(populate_existing=True))
    if row is None:
        work.error("artifact_unavailable", 404)
    return row


def _scope(row):
    return VendorArtifactScope.model_validate({"box_id": row.box_id, "workspace_id": row.workspace_id,
        "owner_id": row.owner_id, "document": {"artifact_id": row.artifact_id,
        "sha256": row.sha256, "byte_length": row.byte_length, "media_type": row.media_type}})


def _metadata(s, row):
    attempt = s.scalar(select(VendorArtifactAttempt).where(
        VendorArtifactAttempt.artifact_id == row.artifact_id,
        VendorArtifactAttempt.generation == row.active_generation)) if row.active_generation else None
    value = {"artifact_id": row.artifact_id, "version": row.version,
        "source": {"kind": "reviewed_note", "note_id": row.note_id,
            "content_sha256": row.content_hash, "source_fingerprint": row.source_fingerprint},
        "document": {"artifact_id": row.artifact_id, "sha256": row.sha256,
            "byte_length": row.byte_length, "media_type": row.media_type},
        "intent_sha256": row.intent_sha256, "state": row.state,
        "generation": row.active_generation,
        "lease_until": public.timestamp(attempt.lease_until) if attempt else None}
    return public.ArtifactMetadata.model_validate(value).public()


def _response(s, w, receipt, row=None):
    if isinstance(receipt, VendorPreparationRetirement):
        from cosmas_os.application import vendor_preparation_retirement
        return vendor_preparation_retirement.response(s, receipt)
    row = row or _artifact(s, w, receipt.artifact_id)
    scope = work._scope(w)
    request_model = public.VendorArtifactIntent if receipt.command_kind == "artifact_intent" else public.VendorArtifactContent
    request = request_model.model_validate(receipt.public_request)
    effect = receipt.effect["effect"]
    check = {"scope": scope, "command_kind": receipt.command_kind,
        "idempotency_key": receipt.idempotency_key, "request_sha256": receipt.request_sha256,
        "effect": {k: v for k, v in effect.items() if k != "receipt_sha256"}}
    if (receipt.artifact_id != row.artifact_id or request.artifact_id != row.artifact_id
            or receipt.scope_kind != "workspace" or receipt.scope_id != w.id
            or public.request_digest(receipt.command_kind, scope, request) != receipt.request_sha256
            or public.public_digest("cosmas-vendor-public-receipt.v1", check) != receipt.receipt_sha256
            or effect.get("receipt_sha256") != receipt.receipt_sha256):
        work.error("vendor_unavailable", 503)
    return public.bounded(public.ArtifactResponse.model_validate({"contract_version": 1,
        "scope": scope, "command_kind": receipt.command_kind,
        "idempotency_key": receipt.idempotency_key, "request_sha256": receipt.request_sha256,
        "outcome": "recorded", "effect": effect, "artifact": _metadata(s, row),
        "observed_at": public.timestamp(work._clock(s))}).public(), 8192)


def _record(s, w, actor, kind, request, digest, artifact):
    rid, now = str(uuid4()), work._clock(s)
    effect = {"artifact_id": artifact.artifact_id, "receipt_id": rid,
        "effect_version": artifact.version, "recorded_at": public.timestamp(now)}
    sha = public.public_digest("cosmas-vendor-public-receipt.v1", {"scope": work._scope(w),
        "command_kind": kind, "idempotency_key": request.idempotency_key,
        "request_sha256": digest, "effect": effect})
    effect["receipt_sha256"] = sha
    receipt = VendorCommandReceipt(id=rid, box_id=w.box_id, workspace_id=w.id, owner_id=actor,
        actor_id=actor, scope_kind="workspace", scope_id=w.id, command_kind=kind,
        idempotency_key=request.idempotency_key, public_request=request.public(), request_sha256=digest,
        artifact_id=artifact.artifact_id, effect_version=artifact.version, effect={"effect": effect},
        receipt_sha256=sha, recorded_at=now)
    s.add(receipt)
    s.add(AuditEvent(box_id=w.box_id, aggregate_type="workspace", aggregate_id=w.id,
        actor_principal_id=actor, event_type="vendor_artifact." + kind, outcome="intent_recorded",
        detail={"artifact_id": artifact.artifact_id, "receipt_id": rid}))
    s.flush()
    return receipt


def intent(s, box, actor, wid, request, *, core_checked=None):
    request = public.VendorArtifactIntent.model_validate(request.public())
    w = work._owner(s, box, actor, wid, writing=True)
    prior, digest = work._receipt(s, w, actor, "artifact_intent", request)
    if prior:
        response = _response(s, w, prior)
        work._final_authority(s)
        s.commit()
        return response
    work._gate()
    note = work._source(s, w, request.source, core_checked)
    if s.get(VendorArtifact, request.artifact_id) is not None:
        work.error("vendor_idempotency_conflict")
    row = VendorArtifact(artifact_id=request.artifact_id, box_id=box, workspace_id=wid, owner_id=actor,
        note_id=note.id, content_hash=note.content_hash, source_fingerprint=note.source_fingerprint,
        intent_sha256=digest, sha256=request.sha256, byte_length=request.byte_length,
        media_type=request.media_type, scope_version=1, state="empty", version=1, active_generation=0)
    s.add(row)
    s.flush()
    receipt = _record(s, w, actor, "artifact_intent", request, digest, row)
    response = _response(s, w, receipt, row)
    work._final_authority(s)
    s.commit()
    return response


def resolve(s, box, actor, wid, request):
    request = public.VendorArtifactResolve.model_validate(request.public())
    w = work._owner(s, box, actor, wid)
    receipt = work._saved(s, wid, actor, request.idempotency_key)
    if receipt:
        if (receipt.command_kind != request.command_kind or receipt.request_sha256 != request.request_sha256
                or receipt.public_request.get("artifact_id") != request.artifact_id or receipt.scope_kind != "workspace"):
            work.error("vendor_idempotency_conflict")
        return _response(s, w, receipt)
    return public.bounded(public.ArtifactResponse.model_validate({"contract_version": 1,
        "scope": work._scope(w), "command_kind": request.command_kind,
        "idempotency_key": request.idempotency_key, "request_sha256": request.request_sha256,
        "outcome": "not_found", "effect": None, "artifact": None,
        "observed_at": public.timestamp(work._clock(s))}).public(), 8192)


def begin_content(s, box, actor, wid, aid, key, *, core_checked=None, storage_available=True):
    # This resumes the immutable local intent; it cannot associate a new source.
    # Current patient/owner access is required, but a newer note does not erase it.
    w = work._owner(s, box, actor, wid, writing=True)
    row = _artifact(s, w, aid, writing=True)
    request = public.VendorArtifactContent.model_validate({"artifact_id": aid,
        "intent_sha256": row.intent_sha256, "idempotency_key": key, "sha256": row.sha256,
        "byte_length": row.byte_length, "media_type": row.media_type})
    prior, digest = work._receipt(s, w, actor, "artifact_content", request)
    if isinstance(prior, VendorPreparationRetirement):
        admission = ContentAdmission(None, _response(s, w, prior), _scope(row))
        work._final_authority(s)
        s.commit()
        return admission
    if not storage_available:
        work.error("artifact_unavailable", 503)
    first = s.scalar(select(VendorArtifactAttempt).where(VendorArtifactAttempt.artifact_id == aid)
        .order_by(VendorArtifactAttempt.generation).limit(1))
    if first and (first.idempotency_key != key or first.request_sha256 != digest):
        work.error("vendor_idempotency_conflict")
    active = s.scalar(select(VendorArtifactAttempt).where(VendorArtifactAttempt.artifact_id == aid,
        VendorArtifactAttempt.generation == row.active_generation).with_for_update()
        .execution_options(populate_existing=True)) if row.active_generation else None
    now = work._clock(s)
    if prior and (row.state in {"ready", "quarantined"} or active and active.lease_until > now):
        admission = ContentAdmission(None, _response(s, w, prior, row), _scope(row))
        work._final_authority(s)
        s.commit()
        return admission
    work._gate()
    if row.state == "quarantined":
        work.error("artifact_changed")
    if active and active.lease_until > now:
        work.error("artifact_write_in_progress")
    if active and active.completed_at is None:
        active.state, active.safe_error, active.completed_at = "unknown", "artifact_write_unconfirmed", now
    row.active_generation += 1
    row.version += 1
    row.state = "receiving"
    attempt = VendorArtifactAttempt(id=str(uuid4()), artifact_id=aid, box_id=box, workspace_id=wid,
        owner_id=actor, actor_id=actor, idempotency_key=key, request_sha256=digest,
        generation=row.active_generation, fence_token=str(uuid4()), admitted_at=now,
        lease_until=now + timedelta(seconds=90), state="receiving")
    s.add(attempt)
    s.flush()
    receipt = prior or _record(s, w, actor, "artifact_content", request, digest, row)
    scope = _scope(row)
    token = ContentToken(box, wid, actor, aid, attempt.id, attempt.generation,
        attempt.fence_token, digest, scope)
    admission = ContentAdmission(token, _response(s, w, receipt, row), scope)
    work._final_authority(s)
    s.commit()
    return admission


def write_content(store, token: ContentToken, data: bytes, *, deadline: float | None = None) -> ContentOutcome:
    """Call only after begin_content committed, off the API event loop."""
    if deadline is not None and time.monotonic() >= deadline:
        return "unknown"
    try:
        token.scope.require_bytes(data)
    except ArtifactStoreError:
        return "input_invalid"
    try:
        if deadline is None:
            store.put_verified(token.scope, data)
        else:
            store.put_verified(token.scope, data, deadline=deadline)
            if time.monotonic() >= deadline:
                return "unknown"
        return "ready"
    except ArtifactStoreError as exc:
        return "stored_corrupt" if exc.code == "artifact_changed" else "unknown"
    except Exception:
        return "unknown"


def _internal_artifact(s, token):
    owner = s.scalar(select(Principal).where(Principal.id == token.owner_id,
        Principal.box_id == token.box_id).with_for_update())
    w = s.scalar(select(EncounterWorkspace).where(EncounterWorkspace.id == token.workspace_id,
        EncounterWorkspace.box_id == token.box_id, EncounterWorkspace.owner_id == token.owner_id)
        .with_for_update().execution_options(populate_existing=True))
    if owner is None or w is None:
        work.error("vendor_unavailable", 503)
    row = _artifact(s, w, token.artifact_id, writing=True)
    if _scope(row) != token.scope:
        work.error("vendor_unavailable", 503)
    return row


def settle_in_session(s, token: ContentToken, outcome: ContentOutcome):
    """Internal bookkeeping only. Never returns public metadata or document bytes."""
    if outcome not in get_args(ContentOutcome):
        raise ValueError("invalid artifact outcome")
    row = _internal_artifact(s, token)
    attempt = s.scalar(select(VendorArtifactAttempt).where(VendorArtifactAttempt.id == token.attempt_id)
        .with_for_update().execution_options(populate_existing=True))
    if (attempt is None or attempt.artifact_id != token.artifact_id or attempt.owner_id != token.owner_id
            or attempt.workspace_id != token.workspace_id or attempt.box_id != token.box_id
            or attempt.generation != token.generation or attempt.fence_token != token.fence_token
            or attempt.request_sha256 != token.request_sha256):
        work.error("vendor_unavailable", 503)
    if attempt.completed_at is not None:
        return "already_settled"
    now = work._clock(s)
    current = row.active_generation == token.generation and attempt.lease_until > now
    if not current:
        outcome = "unknown"
    attempt.state = "ready" if outcome == "ready" else "unknown" if outcome == "unknown" else "failed"
    attempt.safe_error = None if outcome == "ready" else (
        "artifact_changed" if outcome in {"input_invalid", "stored_corrupt"} else "artifact_write_unconfirmed")
    attempt.completed_at = now
    if current and outcome in {"ready", "stored_corrupt"} and row.state != "quarantined":
        row.state = "ready" if outcome == "ready" else "quarantined"
        row.version += 1
    s.flush()
    return "settled" if current else "expired"


def settle_content(session_factory, token: ContentToken, outcome: ContentOutcome):
    with session_factory() as s, s.begin():
        return settle_in_session(s, token, outcome)


def preview(s, box, actor, wid, aid):
    w = work._owner(s, box, actor, wid)
    row = _artifact(s, w, aid)
    if row.state != "ready":
        work.error("artifact_unavailable", 409)
    token = PreviewToken(box, wid, actor, aid, row.version, _scope(row))
    work._final_authority(s)
    s.commit()  # No owner/workspace/artifact locks survive into the blob read.
    return token


def finish_preview(s, box, actor, wid, token: PreviewToken, data: bytes, *, deadline: float):
    if (token.box_id, token.owner_id, token.workspace_id) != (box, actor, wid):
        work.error("artifact_unavailable", 404)
    w = work._owner(s, box, actor, wid)
    row = _artifact(s, w, token.artifact_id)
    if row.version != token.version or row.state != "ready" or _scope(row) != token.scope:
        work.error("artifact_changed")
    try:
        token.scope.require_bytes(data)
    except ArtifactStoreError:
        work.error("artifact_changed")
    work._final_authority(s)
    if time.monotonic() >= deadline:
        work.error("artifact_unavailable", 503)
    return data


def quarantine_in_session(s, token: PreviewToken):
    row = _internal_artifact(s, token)
    if row.version == token.version and row.state == "ready":
        row.state, row.version = "quarantined", row.version + 1
        s.flush()
        return True
    return False


def quarantine_preview(session_factory, token: PreviewToken):
    """Record verified stored corruption even if the owner lost access during I/O."""
    with session_factory() as s, s.begin():
        return quarantine_in_session(s, token)
