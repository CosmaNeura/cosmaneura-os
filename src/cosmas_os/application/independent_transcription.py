"""CosmaBot independent recording transcription (default off; fake processor)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from cosmas_os.application import private_recording as private
from cosmas_os.application import real_patient_recording as real_patient
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import AppointmentObservation, AuditEvent, BoxContext, PatientLink, Principal
from cosmas_os.ports.independent_transcription_contracts import MAX_LEASE
from cosmas_os.ports.recording_transcription import (
    FakeTranscriptionProcessor,
    TranscriptionFailure,
    TranscriptionProcessor,
    TranscriptionRequest,
    TranscriptionResult,
)
from cosmas_os.private_recording_models import (
    IndependentRecordingAudioPurgeReceipt,
    IndependentRecordingAudioUpload,
    IndependentRecordingTranscript,
    IndependentRecordingTranscriptionJob,
    PrivateRecordingVisitBinding,
)

DISABLED = "independent_recording_transcription_disabled"
AUDIO_TTL = timedelta(hours=48)
CLAIM_LEASE = timedelta(seconds=30)
LOCK_TIMEOUT = "1500ms"
MAX_JOB_ATTEMPTS = 5
JOB_PENDING, JOB_CLAIMED, JOB_READY = "pending", "claimed", "ready"
JOB_RETRYABLE, JOB_TERMINAL = "failed_retryable", "failed_terminal"
_NOT_FOUND_TYPES = frozenset({"ResourceNotFoundError", "KeyError", "FileNotFoundError"})
_PROCESSOR: TranscriptionProcessor | None = None
_Upload = IndependentRecordingAudioUpload
_Job = IndependentRecordingTranscriptionJob
_Tx = IndependentRecordingTranscript
_Receipt = IndependentRecordingAudioPurgeReceipt
_Binding = PrivateRecordingVisitBinding


def set_processor_override(processor: TranscriptionProcessor | None) -> None:
    global _PROCESSOR
    _PROCESSOR = processor


def _now(c: svc.Container) -> datetime:
    v = c.clock.now()
    return v if v.tzinfo is not None else v.replace(tzinfo=UTC)


def _lock_timeout(session: Session) -> None:
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _is_lock_timeout(exc: BaseException) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "55P03":
        return True
    message = str(exc).lower()
    return "lock timeout" in message or "canceling statement due to lock timeout" in message


def _enabled(session: Session, box_id: str) -> bool:
    if not settings.independent_recording_transcription_enabled:
        return False
    box = session.get(BoxContext, box_id)
    return bool(box is not None and box.independent_recording_transcription_enabled)


def require_enabled(session: Session, box_id: str) -> None:
    if not _enabled(session, box_id):
        raise ws.WorkspaceError(DISABLED, 403)


def enabled_status(session: Session, box_id: str, owner_id: str, wid: str, *, external: str) -> dict[str, bool]:
    private.identity(session, box_id, owner_id, external)
    ws._workspace(session, box_id, owner_id, wid, writing=False, allow_private=True)
    return {"enabled": _enabled(session, box_id)}


def _processor() -> TranscriptionProcessor:
    return _PROCESSOR if _PROCESSOR is not None else FakeTranscriptionProcessor()


def _scoped(model, session: Session, box_id: str, wid: str, rid: str, oid: str, *, lock=False, state=None):
    q = select(model).where(
        model.box_id == box_id, model.workspace_id == wid, model.recording_id == rid, model.operation_id == oid
    )
    if state is not None:
        q = q.where(model.state == state)
    if lock:
        q = q.with_for_update()
    return session.scalar(q)


def _binding(session: Session, recording_id: str):
    return session.scalar(select(_Binding).where(_Binding.recording_id == recording_id))


def _synthetic_environment() -> bool:
    return settings.data_mode == "synthetic"


def _derive_recording_class(session: Session, box_id: str, recording_id: str) -> str:
    binding = _binding(session, recording_id)
    if binding is None:
        if not _synthetic_environment():
            raise ws.WorkspaceError(real_patient.REFUSED, 403)
        return "synthetic"
    appointment = session.get(AppointmentObservation, binding.appointment_id)
    if appointment is None:
        if not _synthetic_environment():
            raise ws.WorkspaceError(real_patient.REFUSED, 403)
        return "synthetic"
    return real_patient.visit_recording_class(appointment, session.get(PatientLink, binding.patient_link_id))


def _require_recording_class(session: Session, box_id: str, recording_id: str, *, claimed: str | None) -> tuple[str, bool]:
    derived = _derive_recording_class(session, box_id, recording_id)
    if claimed is not None and claimed != derived:
        raise ws.WorkspaceError("independent_transcription_recording_class_mismatch", 422)
    if derived not in real_patient.RECORDING_CLASSES:
        raise ws.WorkspaceError("invalid_independent_transcription_request", 422)
    if derived in {"synthetic", "demo"}:
        return derived, True
    binding = _binding(session, recording_id)
    if binding is None:
        raise ws.WorkspaceError(real_patient.REFUSED, 403)
    appointment = session.get(AppointmentObservation, binding.appointment_id)
    if appointment is None:
        raise ws.WorkspaceError(real_patient.REFUSED, 403)
    real_patient.require_recording_start_allowed(session, box_id=box_id, appointment=appointment, runtime=settings)
    return derived, False


def _consent_ok(consent: dict, now: datetime) -> None:
    if consent.get("all_parties_consented") is not True:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    raw = consent.get("granted_at")
    if isinstance(raw, datetime):
        granted = raw
    elif isinstance(raw, str):
        granted = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    if granted.tzinfo is None or granted > now:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)


def _lease_ok(lease_expires_at: datetime, now: datetime) -> None:
    if lease_expires_at.tzinfo is None or lease_expires_at <= now:
        raise ws.WorkspaceError("independent_transcription_lease_expired", 403)
    if lease_expires_at > now + timedelta(seconds=MAX_LEASE):
        raise ws.WorkspaceError("independent_transcription_lease_too_long", 422)


def _audio_readable(row: IndependentRecordingAudioUpload, now: datetime) -> None:
    if row.revoked_at is not None:
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    if row.audio_purged_at is not None or row.audio_expires_at <= now or row.blob_key is None:
        raise ws.WorkspaceError("independent_transcription_audio_expired", 410)


def _view_transcript(row: IndependentRecordingTranscript) -> dict[str, Any]:
    return {
        "contract": "cosmas.independent-transcription.v1",
        "transcript_id": row.id, "recording_id": row.recording_id, "operation_id": row.operation_id,
        "processor_id": row.processor_id, "profile_id": row.profile_id, "synthetic": row.synthetic,
        "source_sha256": row.source_sha256, "label": row.label, "segments": row.segments,
        "created_at": row.created_at.isoformat(),
    }


def _idem_conflict(existing: IndependentRecordingAudioUpload, *, sha256: str, owner_id: str) -> None:
    if existing.sha256 != sha256 or existing.owner_id != owner_id:
        raise ws.WorkspaceError("idempotency_conflict", 409)


def _dup_view(row: IndependentRecordingAudioUpload) -> dict[str, Any]:
    return {
        "upload_id": row.id, "operation_id": row.operation_id, "sha256": row.sha256,
        "audio_expires_at": row.audio_expires_at.isoformat(), "duplicate": True,
    }


def _reput_matching_upload(
    session: Session,
    c: svc.Container,
    existing: IndependentRecordingAudioUpload,
    *,
    audio_bytes: bytes,
    sha256: str,
    owner_id: str,
    now: datetime,
    synthetic: bool,
) -> dict[str, Any]:
    """Idempotent retry: same sha, not revoked/purged → re-put bytes and audit after put."""
    _idem_conflict(existing, sha256=sha256, owner_id=owner_id)
    if existing.revoked_at is not None:
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    if existing.audio_purged_at is not None or existing.audio_expires_at <= now:
        raise ws.WorkspaceError("independent_transcription_audio_expired", 410)
    if existing.blob_key is None:
        raise ws.WorkspaceError("independent_transcription_audio_expired", 410)
    try:
        c.blob.put_bytes(existing.blob_key, audio_bytes, "application/octet-stream")
    except Exception as exc:  # noqa: BLE001 — storage failure is retryable for the client
        raise ws.WorkspaceError("independent_transcription_unavailable", 503) from exc
    session.add(AuditEvent(
        box_id=existing.box_id, aggregate_type="independent_recording_audio", aggregate_id=existing.id,
        event_type="recording_audio.uploaded", actor_principal_id=owner_id, outcome="saved",
        detail={"operation_id": existing.operation_id, "synthetic": synthetic, "duplicate": True},
    ))
    session.commit()
    return _dup_view(existing)


def upload_audio(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, payload: dict[str, Any], *,
    external: str, fence=None, blob=None, clock=None,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    _, recording = private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock, blob=blob)
    now = _now(c)
    _lock_timeout(session)
    oid, sha256, audio = str(payload["operation_id"]), str(payload["sha256"]), payload["audio"]
    if not isinstance(audio, (bytes, bytearray)):
        raise ws.WorkspaceError("invalid_independent_transcription_request", 422)
    audio_bytes = bytes(audio)
    if hashlib.sha256(audio_bytes).hexdigest() != sha256:
        raise ws.WorkspaceError("independent_transcription_corrupt", 422)
    existing = _scoped(_Upload, session, box_id, wid, rid, oid, lock=True)
    if existing is not None:
        return _recover_duplicate_upload(
            session, c, existing, audio_bytes=audio_bytes, sha256=sha256, owner_id=owner_id, now=now,
        )
    duration_ms = int(payload["duration_ms"])
    language = str(payload.get("language") or "en-US")
    claimed_raw = payload.get("recording_class")
    claimed = str(claimed_raw) if claimed_raw is not None else None
    lease_raw = payload["lease_expires_at"]
    lease = lease_raw if isinstance(lease_raw, datetime) else datetime.fromisoformat(str(lease_raw).replace("Z", "+00:00"))
    consent = payload.get("consent")
    if not isinstance(consent, dict):
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    _consent_ok(consent, now)
    _lease_ok(lease, now)
    recording_class, synthetic = _require_recording_class(session, box_id, rid, claimed=claimed)
    if fence:
        fence()
    upload_id = str(uuid4())
    key = f"{box_id}/independent-transcription/{rid}/{upload_id}/{sha256}"
    row = _Upload(
        id=upload_id, recording_id=recording.id, workspace_id=wid, box_id=box_id, owner_id=owner_id,
        operation_id=oid, blob_key=key, sha256=sha256, byte_count=len(audio_bytes),
        duration_ms=duration_ms, language=language, recording_class=recording_class, consent=consent,
        lease_expires_at=lease, audio_expires_at=now + AUDIO_TTL,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        raced = _scoped(_Upload, session, box_id, wid, rid, oid, lock=True)
        if raced is None:
            raise ws.WorkspaceError("idempotency_conflict", 409) from None
        return _recover_duplicate_upload(
            session, c, raced, audio_bytes=audio_bytes, sha256=sha256, owner_id=owner_id, now=now,
        )
    # Persist the deterministic key before the blob write so a crash mid-put leaves
    # a row the duplicate path can re-put into. Audit "saved" only after put succeeds.
    session.commit()
    try:
        c.blob.put_bytes(key, audio_bytes, "application/octet-stream")
    except Exception as exc:  # noqa: BLE001 — storage failure is retryable for the client
        raise ws.WorkspaceError("independent_transcription_unavailable", 503) from exc
    session.add(AuditEvent(
        box_id=box_id, aggregate_type="independent_recording_audio", aggregate_id=row.id,
        event_type="recording_audio.uploaded", actor_principal_id=owner_id, outcome="saved",
        detail={"operation_id": oid, "synthetic": synthetic},
    ))
    session.commit()
    return {
        "upload_id": row.id, "operation_id": row.operation_id, "sha256": row.sha256,
        "audio_expires_at": row.audio_expires_at.isoformat(), "duplicate": False,
    }


def _recover_duplicate_upload(
    session: Session,
    c: svc.Container,
    existing: IndependentRecordingAudioUpload,
    *,
    audio_bytes: bytes,
    sha256: str,
    owner_id: str,
    now: datetime,
) -> dict[str, Any]:
    synthetic = existing.recording_class in {"synthetic", "demo"}
    return _reput_matching_upload(
        session, c, existing,
        audio_bytes=audio_bytes, sha256=sha256, owner_id=owner_id, now=now, synthetic=synthetic,
    )


def _claim_job(session: Session, *, upload: IndependentRecordingAudioUpload, now: datetime) -> IndependentRecordingTranscriptionJob:
    job = _scoped(_Job, session, upload.box_id, upload.workspace_id, upload.recording_id, upload.operation_id, lock=True)
    if job is None:
        job = _Job(
            id=str(uuid4()), upload_id=upload.id, recording_id=upload.recording_id,
            workspace_id=upload.workspace_id, box_id=upload.box_id, owner_id=upload.owner_id,
            operation_id=upload.operation_id, state=JOB_PENDING, attempts=0,
        )
        session.add(job)
        session.flush()
    if job.state == JOB_READY:
        return job
    if job.state == JOB_TERMINAL:
        raise ws.WorkspaceError("independent_transcription_failed", 422)
    if job.state == JOB_CLAIMED and job.claimed_at is not None:
        claimed_at = job.claimed_at if job.claimed_at.tzinfo is not None else job.claimed_at.replace(tzinfo=UTC)
        if now - claimed_at < CLAIM_LEASE:
            raise ws.WorkspaceError("independent_transcription_unavailable", 503)
    if job.attempts >= MAX_JOB_ATTEMPTS:
        job.state, job.finished_at, job.error_kind = JOB_TERMINAL, now, "attempts_exhausted"
        session.commit()
        raise ws.WorkspaceError("independent_transcription_failed", 422)
    job.state, job.attempts, job.claimed_at, job.error_kind = JOB_CLAIMED, job.attempts + 1, now, None
    session.flush()
    return job


def start_transcription(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, payload: dict[str, Any], *,
    external: str, fence=None, blob=None, clock=None, processor: TranscriptionProcessor | None = None,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock, blob=blob)
    now, oid = _now(c), str(payload["operation_id"])
    _lock_timeout(session)
    existing = _scoped(_Tx, session, box_id, wid, rid, oid)
    if existing is not None:
        return {"status": "ready", "transcript": _view_transcript(existing), "recovered": True}
    upload = _scoped(_Upload, session, box_id, wid, rid, oid, lock=True)
    if upload is None:
        raise ws.WorkspaceError("independent_transcription_upload_not_found", 404)
    if upload.owner_id != owner_id:
        raise ws.WorkspaceError("idempotency_conflict", 409)
    _lease_ok(upload.lease_expires_at, now)
    _consent_ok(upload.consent, now)
    _audio_readable(upload, now)
    # Re-derive at start so a binding change after upload cannot silently widen class.
    _require_recording_class(session, box_id, rid, claimed=upload.recording_class)
    if fence:
        fence()
    job = _claim_job(session, upload=upload, now=now)
    if job.state == JOB_READY:
        ready = _scoped(_Tx, session, box_id, wid, rid, oid)
        if ready is not None:
            return {"status": "ready", "transcript": _view_transcript(ready), "recovered": True}
    claim_attempt = job.attempts
    upload_id = upload.id
    session.commit()
    upload = session.get(_Upload, upload_id, populate_existing=True)
    if upload is None or upload.blob_key is None:
        _finish_claimed_failure(
            session, box_id=box_id, wid=wid, rid=rid, operation_id=oid,
            kind="audio_missing", terminal=True, claim_attempt=claim_attempt, now=_now(c),
        )
        if upload is not None and upload.revoked_at is not None:
            raise ws.WorkspaceError("independent_transcription_revoked", 409)
        raise ws.WorkspaceError("independent_transcription_audio_expired", 410)
    try:
        audio = c.blob.get_bytes(upload.blob_key)
    except Exception:
        _finish_claimed_failure(
            session, box_id=box_id, wid=wid, rid=rid, operation_id=oid,
            kind="blob_read", terminal=False, claim_attempt=claim_attempt, now=_now(c),
        )
        raise ws.WorkspaceError("independent_transcription_unavailable", 503) from None
    if hashlib.sha256(audio).hexdigest() != upload.sha256:
        _finish_claimed_failure(
            session, box_id=box_id, wid=wid, rid=rid, operation_id=oid,
            kind="corrupt", terminal=True, claim_attempt=claim_attempt, now=_now(c),
        )
        raise ws.WorkspaceError("independent_transcription_corrupt", 422)
    request = TranscriptionRequest(
        audio=audio, sha256=upload.sha256, duration_ms=upload.duration_ms, language=upload.language,
        operation_id=oid, synthetic=upload.recording_class in {"synthetic", "demo"},
    )
    try:
        outcome = (processor or _processor()).transcribe(request)
    except Exception:
        _finish_claimed_failure(
            session, box_id=box_id, wid=wid, rid=rid, operation_id=oid,
            kind="crash", terminal=False, claim_attempt=claim_attempt, now=_now(c),
        )
        raise ws.WorkspaceError("independent_transcription_processor_crash", 503) from None
    return _finish_transcription(
        session, c=c, upload_id=upload.id, box_id=box_id, owner_id=owner_id, wid=wid, rid=rid,
        operation_id=oid, outcome=outcome, now=_now(c), claim_attempt=claim_attempt,
    )


def _finish_claimed_failure(
    session: Session,
    *,
    box_id: str,
    wid: str,
    rid: str,
    operation_id: str,
    kind: str,
    terminal: bool,
    now: datetime,
    claim_attempt: int | None = None,
) -> None:
    """Mark a claimed job retryable/terminal. No-op when the claim attempt no longer matches."""
    _lock_timeout(session)
    job = _scoped(_Job, session, box_id, wid, rid, operation_id, lock=True, state=JOB_CLAIMED)
    if job is None:
        session.commit()
        return
    if claim_attempt is not None and job.attempts != claim_attempt:
        session.commit()
        return
    when = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    if terminal or job.attempts >= MAX_JOB_ATTEMPTS:
        job.state, job.finished_at, job.error_kind = JOB_TERMINAL, when, kind
    else:
        job.state, job.error_kind = JOB_RETRYABLE, kind
    session.commit()


def _finish_transcription(
    session: Session, *, c: svc.Container, upload_id: str, box_id: str, owner_id: str, wid: str, rid: str,
    operation_id: str, outcome: TranscriptionResult | TranscriptionFailure, now: datetime,
    claim_attempt: int,
) -> dict[str, Any]:
    _lock_timeout(session)
    # Lock upload then job — same order as start_transcription — to avoid deadlocks.
    try:
        upload = session.get(_Upload, upload_id, with_for_update=True, populate_existing=True)
        job = _scoped(_Job, session, box_id, wid, rid, operation_id, lock=True, state=JOB_CLAIMED)
    except DBAPIError as exc:
        if _is_lock_timeout(exc):
            raise ws.WorkspaceError("independent_transcription_unavailable", 503) from exc
        raise
    if job is None or job.attempts != claim_attempt:
        lost = _scoped(_Tx, session, box_id, wid, rid, operation_id)
        if lost is not None:
            return {"status": "ready", "transcript": _view_transcript(lost), "recovered": True}
        raise ws.WorkspaceError("independent_transcription_unavailable", 503)
    if upload is None or upload.revoked_at is not None:
        job.state, job.error_kind, job.finished_at = JOB_TERMINAL, "revoked", now
        session.commit()
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    after = _scoped(_Tx, session, box_id, wid, rid, operation_id)
    if after is not None:
        job.state, job.finished_at = JOB_READY, now
        session.commit()
        return {"status": "ready", "transcript": _view_transcript(after), "recovered": True}
    if isinstance(outcome, TranscriptionFailure):
        if outcome.kind in {"retryable", "unavailable"}:
            job.state = JOB_RETRYABLE if job.attempts < MAX_JOB_ATTEMPTS else JOB_TERMINAL
            job.error_kind = outcome.kind
            if job.state == JOB_TERMINAL:
                job.finished_at = now
            session.commit()
            code = (
                "independent_transcription_retryable"
                if outcome.kind == "retryable"
                else "independent_transcription_unavailable"
            )
            raise ws.WorkspaceError(code, 503)
        job.state, job.error_kind, job.finished_at = JOB_TERMINAL, outcome.kind, now
        session.commit()
        raise ws.WorkspaceError(f"independent_transcription_{outcome.kind}", 422)
    assert isinstance(outcome, TranscriptionResult)
    if not outcome.label:
        job.state, job.error_kind, job.finished_at = JOB_TERMINAL, "missing_label", now
        session.commit()
        raise ws.WorkspaceError("independent_transcription_unavailable", 503)
    row = _Tx(
        id=str(uuid4()), upload_id=upload.id, recording_id=rid, workspace_id=wid, box_id=box_id,
        owner_id=owner_id, operation_id=operation_id, processor_id=outcome.processor_id,
        profile_id=outcome.profile_id, synthetic=outcome.synthetic, source_sha256=upload.sha256,
        segments=[{"text": s.text, "offset_ms": s.offset_ms, "duration_ms": s.duration_ms} for s in outcome.segments],
        label=outcome.label,
    )
    session.add(row)
    job.state, job.finished_at = JOB_READY, now
    session.commit()
    return {"status": "ready", "transcript": _view_transcript(row), "recovered": False}


def read_transcription(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, *, external: str, operation_id: str,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    private.checked(session, box_id, owner_id, wid, external, rid)
    row = _scoped(_Tx, session, box_id, wid, rid, operation_id)
    upload = _scoped(_Upload, session, box_id, wid, rid, operation_id)
    if upload is not None and upload.revoked_at is not None:
        if row is not None:
            return {"status": "ready", "transcript": _view_transcript(row), "revoked": True}
        return {"status": "revoked"}
    if row is None:
        if upload is None:
            raise ws.WorkspaceError("independent_transcription_not_found", 404)
        job = _scoped(_Job, session, box_id, wid, rid, operation_id)
        if job is not None and job.state == JOB_TERMINAL:
            return {"status": "failed", "error_kind": job.error_kind}
        return {"status": "pending"}
    return {"status": "ready", "transcript": _view_transcript(row)}


def read_transcript(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, *, external: str, operation_id: str,
) -> dict[str, Any]:
    result = read_transcription(session, box_id, owner_id, wid, rid, external=external, operation_id=operation_id)
    if result.get("status") != "ready":
        raise ws.WorkspaceError("independent_transcription_not_found", 404)
    return result["transcript"]


def _blob_delete(c: svc.Container, key: str) -> str:
    try:
        c.blob.delete(key)
        return "purged"
    except Exception as exc:  # noqa: BLE001 — typed absence vs retryable failure
        if isinstance(exc, (KeyError, FileNotFoundError)) or type(exc).__name__ in _NOT_FOUND_TYPES:
            return "purged"
        return "failed"


def revoke_transcription(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, payload: dict[str, Any], *,
    external: str, fence=None, blob=None, clock=None,
) -> dict[str, Any]:
    # Revoke stays available when the process switch is off so leftover audio can
    # still be deleted after the feature is disabled.
    private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock, blob=blob)
    now, oid = _now(c), str(payload["operation_id"])
    _lock_timeout(session)
    upload = _scoped(_Upload, session, box_id, wid, rid, oid, lock=True)
    if upload is None:
        raise ws.WorkspaceError("independent_transcription_upload_not_found", 404)
    if fence:
        fence()
    if upload.revoked_at is None:
        upload.revoked_at = now
    outcome = "purged"
    if upload.blob_key and upload.audio_purged_at is None:
        outcome = _blob_delete(c, upload.blob_key)
        if outcome == "purged":
            upload.blob_key, upload.audio_purged_at = None, now
        session.add(_Receipt(
            id=str(uuid4()), box_id=box_id, upload_id=upload.id,
            retention_rule="revoke_delete", deleted_at=now, outcome=outcome,
        ))
    session.commit()
    return {
        "status": "revoked", "operation_id": oid,
        "revoked_at": upload.revoked_at.isoformat(), "audio_outcome": outcome,
    }


def purge_due_recording_audio(
    c: svc.Container, box_id: str | None = None, actor_id: str | None = None,
) -> list[dict[str, Any]]:
    _lock_timeout(c.session)
    if actor_id is not None and box_id is not None:
        actor = c.session.scalar(select(Principal).where(Principal.id == actor_id).with_for_update())
        svc._require_active_human(actor, box_id=box_id, owner_required=True)
    now = _now(c)
    q = select(_Upload).where(_Upload.audio_purged_at.is_(None), _Upload.audio_expires_at <= now)
    if box_id is not None:
        q = q.where(_Upload.box_id == box_id)
    rows = c.session.scalars(q.with_for_update(skip_locked=True)).all()
    receipts: list[dict[str, Any]] = []
    for row in rows:
        outcome = _blob_delete(c, row.blob_key) if row.blob_key else "purged"
        if outcome != "failed":
            row.blob_key, row.audio_purged_at = None, now
        receipt = {
            "upload_id": row.id, "retention_rule": "audio_plus_48h",
            "deleted_at": now.isoformat(), "outcome": outcome,
        }
        c.session.add(_Receipt(
            id=str(uuid4()), box_id=row.box_id, upload_id=row.id,
            retention_rule="audio_plus_48h", deleted_at=now, outcome=outcome,
        ))
        receipts.append(receipt)
        if outcome == "failed":
            continue
        c.session.add(AuditEvent(
            box_id=row.box_id, aggregate_type="independent_recording_audio", aggregate_id=row.id,
            event_type="recording_audio.purged", actor_principal_id=actor_id, outcome="purged",
            detail={"retention_rule": receipt["retention_rule"], "owner_authorized": actor_id is not None},
        ))
    c.session.commit()
    return receipts


def purge_route(
    session: Session, box_id: str, owner_id: str, wid: str, *, external: str, fence=None, blob=None, clock=None,
) -> dict[str, Any]:
    private.identity(session, box_id, owner_id, external)
    ws._workspace(session, box_id, owner_id, wid, writing=True, allow_private=True)
    if fence:
        fence()
    return {"receipts": purge_due_recording_audio(svc.Container(session, clock=clock, blob=blob), box_id, owner_id)}


def wipe_owner_transcription_data(session: Session, *, box_id: str, owner_id: str, blob) -> None:
    c = svc.Container(session, blob=blob)
    uploads = session.scalars(select(_Upload).where(_Upload.box_id == box_id, _Upload.owner_id == owner_id)).all()
    for upload in uploads:
        if upload.blob_key:
            outcome = _blob_delete(c, upload.blob_key)
            if outcome != "purged":
                raise ws.WorkspaceError("independent_transcription_unavailable", 503)
            upload.blob_key = None
    upload_ids = [u.id for u in uploads]
    if not upload_ids:
        return
    for job in session.scalars(select(_Job).where(_Job.upload_id.in_(upload_ids))).all():
        session.delete(job)
    for transcript in session.scalars(select(_Tx).where(_Tx.upload_id.in_(upload_ids))).all():
        session.delete(transcript)
    session.flush()
    for receipt in session.scalars(
        select(_Receipt).where(_Receipt.box_id == box_id, _Receipt.upload_id.in_(upload_ids))
    ).all():
        session.delete(receipt)
    for upload in uploads:
        session.delete(upload)
    session.flush()
