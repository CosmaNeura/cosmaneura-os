"""CosmaBot independent recording transcription (default off; fake processor)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.adapters.azure_fast_transcription import AzureFastTranscriptionProcessor
from cosmas_os.application import private_recording as private
from cosmas_os.application import real_patient_recording as real_patient
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import AppointmentObservation, AuditEvent, BoxContext, Principal
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
    PrivateRecordingVisitBinding,
)

DISABLED = "independent_recording_transcription_disabled"
AUDIO_TTL = timedelta(hours=48)
_PROCESSOR: TranscriptionProcessor | None = None


def set_processor_override(processor: TranscriptionProcessor | None) -> None:
    global _PROCESSOR
    _PROCESSOR = processor


def _now(c: svc.Container) -> datetime:
    value = c.clock.now()
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
    if _PROCESSOR is not None:
        return _PROCESSOR
    if settings.independent_recording_transcription_azure_enabled:
        endpoint = settings.azure_fast_transcription_endpoint
        if not endpoint:
            raise ws.WorkspaceError("independent_recording_transcription_unavailable", 503)
        return AzureFastTranscriptionProcessor.from_settings(
            endpoint=endpoint,
            key_env_name=settings.azure_fast_transcription_key_env_name,
        )
    return FakeTranscriptionProcessor()


def _require_recording_class(session: Session, box_id: str, recording_id: str, recording_class: str) -> bool:
    if recording_class not in real_patient.RECORDING_CLASSES:
        raise ws.WorkspaceError("invalid_independent_transcription_request", 422)
    synthetic = recording_class in {"synthetic", "demo"}
    if synthetic:
        return True
    binding = session.scalar(
        select(PrivateRecordingVisitBinding).where(PrivateRecordingVisitBinding.recording_id == recording_id)
    )
    if binding is None:
        raise ws.WorkspaceError(real_patient.REFUSED, 403)
    appointment = session.get(AppointmentObservation, binding.appointment_id)
    if appointment is None:
        raise ws.WorkspaceError(real_patient.REFUSED, 403)
    real_patient.require_recording_start_allowed(
        session, box_id=box_id, appointment=appointment, runtime=settings
    )
    return False


def _consent_ok(consent: dict, now: datetime) -> None:
    if consent.get("all_parties_consented") is not True:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    raw = consent.get("granted_at")
    if not isinstance(raw, str):
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    granted = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if granted.tzinfo is None:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    if granted > now:
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)


def _lease_ok(lease_expires_at: datetime, now: datetime) -> None:
    if lease_expires_at.tzinfo is None or lease_expires_at <= now:
        raise ws.WorkspaceError("independent_transcription_lease_expired", 403)


def _audio_readable(row: IndependentRecordingAudioUpload, now: datetime) -> None:
    if row.revoked_at is not None:
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    if row.audio_purged_at is not None or row.audio_expires_at <= now or row.blob_key is None:
        raise ws.WorkspaceError("independent_transcription_audio_expired", 410)


def _view_transcript(row: IndependentRecordingTranscript) -> dict[str, Any]:
    return {
        "contract": "cosmas.independent-transcription.v1",
        "transcript_id": row.id,
        "recording_id": row.recording_id,
        "operation_id": row.operation_id,
        "processor_id": row.processor_id,
        "profile_id": row.profile_id,
        "synthetic": row.synthetic,
        "source_sha256": row.source_sha256,
        "label": row.label,
        "segments": row.segments,
        "created_at": row.created_at.isoformat(),
    }


def upload_audio(
    session: Session,
    box_id: str,
    owner_id: str,
    wid: str,
    rid: str,
    payload: dict[str, Any],
    *,
    external: str,
    fence=None,
    blob=None,
    clock=None,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    _, recording = private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock, blob=blob)
    now = _now(c)
    operation_id = str(payload["operation_id"])
    sha256 = str(payload["sha256"])
    audio = payload["audio"]
    if not isinstance(audio, (bytes, bytearray)):
        raise ws.WorkspaceError("invalid_independent_transcription_request", 422)
    audio_bytes = bytes(audio)
    if hashlib.sha256(audio_bytes).hexdigest() != sha256:
        raise ws.WorkspaceError("independent_transcription_corrupt", 422)

    # Same operation identity is resolved before lease/consent so expired audio
    # cannot return via a fresh lease on re-upload.
    existing = session.scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.owner_id == owner_id,
            IndependentRecordingAudioUpload.operation_id == operation_id,
        ).with_for_update()
    )
    if existing is not None:
        if existing.sha256 != sha256:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        if existing.audio_purged_at is not None or existing.audio_expires_at <= now:
            raise ws.WorkspaceError("independent_transcription_audio_expired", 410)
        return {
            "upload_id": existing.id,
            "operation_id": existing.operation_id,
            "sha256": existing.sha256,
            "audio_expires_at": existing.audio_expires_at.isoformat(),
            "duplicate": True,
        }

    duration_ms = int(payload["duration_ms"])
    language = str(payload.get("language") or "en-US")
    recording_class = str(payload.get("recording_class") or "synthetic")
    lease_raw = payload["lease_expires_at"]
    lease_expires_at = datetime.fromisoformat(str(lease_raw).replace("Z", "+00:00"))
    consent = payload.get("consent")
    if not isinstance(consent, dict):
        raise ws.WorkspaceError("independent_transcription_consent_required", 403)
    _consent_ok(consent, now)
    _lease_ok(lease_expires_at, now)
    synthetic = _require_recording_class(session, box_id, rid, recording_class)

    if fence:
        fence()
    key = f"{box_id}/independent-transcription/{rid}/{operation_id}"
    c.blob.put_bytes(key, audio_bytes, "application/octet-stream")
    row = IndependentRecordingAudioUpload(
        id=str(uuid4()),
        recording_id=recording.id,
        workspace_id=wid,
        box_id=box_id,
        owner_id=owner_id,
        operation_id=operation_id,
        blob_key=key,
        sha256=sha256,
        byte_count=len(audio_bytes),
        duration_ms=duration_ms,
        language=language,
        recording_class=recording_class,
        consent=consent,
        lease_expires_at=lease_expires_at,
        audio_expires_at=now + AUDIO_TTL,
    )
    session.add(row)
    session.add(
        AuditEvent(
            box_id=box_id,
            aggregate_type="independent_recording_audio",
            aggregate_id=row.id,
            event_type="recording_audio.uploaded",
            actor_principal_id=owner_id,
            outcome="saved",
            detail={"operation_id": operation_id, "synthetic": synthetic},
        )
    )
    session.commit()
    return {
        "upload_id": row.id,
        "operation_id": row.operation_id,
        "sha256": row.sha256,
        "audio_expires_at": row.audio_expires_at.isoformat(),
        "duplicate": False,
    }


def start_transcription(
    session: Session,
    box_id: str,
    owner_id: str,
    wid: str,
    rid: str,
    payload: dict[str, Any],
    *,
    external: str,
    fence=None,
    blob=None,
    clock=None,
    processor: TranscriptionProcessor | None = None,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock, blob=blob)
    now = _now(c)
    operation_id = str(payload["operation_id"])
    existing = session.scalar(
        select(IndependentRecordingTranscript).where(
            IndependentRecordingTranscript.owner_id == owner_id,
            IndependentRecordingTranscript.operation_id == operation_id,
        )
    )
    if existing is not None:
        return {"status": "ready", "transcript": _view_transcript(existing), "recovered": True}

    upload = session.scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.owner_id == owner_id,
            IndependentRecordingAudioUpload.operation_id == operation_id,
            IndependentRecordingAudioUpload.recording_id == rid,
        ).with_for_update()
    )
    if upload is None:
        raise ws.WorkspaceError("independent_transcription_upload_not_found", 404)
    _lease_ok(upload.lease_expires_at, now)
    _consent_ok(upload.consent, now)
    _audio_readable(upload, now)
    if fence:
        fence()
    assert upload.blob_key is not None
    audio = c.blob.get_bytes(upload.blob_key)
    selected = processor or _processor()
    request = TranscriptionRequest(
        audio=audio,
        sha256=upload.sha256,
        duration_ms=upload.duration_ms,
        language=upload.language,
        operation_id=operation_id,
        synthetic=upload.recording_class in {"synthetic", "demo"},
    )
    session.refresh(upload)
    if upload.revoked_at is not None:
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    try:
        outcome = selected.transcribe(request)
    except Exception:
        session.commit()
        raise ws.WorkspaceError("independent_transcription_processor_crash", 503) from None
    session.refresh(upload)
    if upload.revoked_at is not None:
        raise ws.WorkspaceError("independent_transcription_revoked", 409)
    if isinstance(outcome, TranscriptionFailure):
        raise ws.WorkspaceError(f"independent_transcription_{outcome.kind}", 422)
    assert isinstance(outcome, TranscriptionResult)
    lost = session.scalar(
        select(IndependentRecordingTranscript).where(
            IndependentRecordingTranscript.owner_id == owner_id,
            IndependentRecordingTranscript.operation_id == operation_id,
        )
    )
    if lost is not None:
        return {"status": "ready", "transcript": _view_transcript(lost), "recovered": True}
    row = IndependentRecordingTranscript(
        id=str(uuid4()),
        upload_id=upload.id,
        recording_id=rid,
        workspace_id=wid,
        box_id=box_id,
        owner_id=owner_id,
        operation_id=operation_id,
        processor_id=outcome.processor_id,
        profile_id=outcome.profile_id,
        synthetic=outcome.synthetic,
        source_sha256=upload.sha256,
        segments=[
            {"text": seg.text, "offset_ms": seg.offset_ms, "duration_ms": seg.duration_ms}
            for seg in outcome.segments
        ],
        label="SYNTHETIC TRANSCRIPT",
    )
    session.add(row)
    session.commit()
    return {"status": "ready", "transcript": _view_transcript(row), "recovered": False}


def read_transcription(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, *, external: str, operation_id: str
) -> dict[str, Any]:
    require_enabled(session, box_id)
    private.checked(session, box_id, owner_id, wid, external, rid)
    row = session.scalar(
        select(IndependentRecordingTranscript).where(
            IndependentRecordingTranscript.owner_id == owner_id,
            IndependentRecordingTranscript.operation_id == operation_id,
            IndependentRecordingTranscript.recording_id == rid,
        )
    )
    if row is None:
        upload = session.scalar(
            select(IndependentRecordingAudioUpload).where(
                IndependentRecordingAudioUpload.owner_id == owner_id,
                IndependentRecordingAudioUpload.operation_id == operation_id,
                IndependentRecordingAudioUpload.recording_id == rid,
            )
        )
        if upload is None:
            raise ws.WorkspaceError("independent_transcription_not_found", 404)
        if upload.revoked_at is not None:
            return {"status": "revoked"}
        return {"status": "pending"}
    return {"status": "ready", "transcript": _view_transcript(row)}


def read_transcript(
    session: Session, box_id: str, owner_id: str, wid: str, rid: str, *, external: str, operation_id: str
) -> dict[str, Any]:
    result = read_transcription(
        session, box_id, owner_id, wid, rid, external=external, operation_id=operation_id
    )
    if result.get("status") != "ready":
        raise ws.WorkspaceError("independent_transcription_not_found", 404)
    return result["transcript"]


def revoke_transcription(
    session: Session,
    box_id: str,
    owner_id: str,
    wid: str,
    rid: str,
    payload: dict[str, Any],
    *,
    external: str,
    fence=None,
    clock=None,
) -> dict[str, Any]:
    require_enabled(session, box_id)
    private.checked(session, box_id, owner_id, wid, external, rid)
    c = svc.Container(session, clock=clock)
    now = _now(c)
    operation_id = str(payload["operation_id"])
    upload = session.scalar(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.owner_id == owner_id,
            IndependentRecordingAudioUpload.operation_id == operation_id,
            IndependentRecordingAudioUpload.recording_id == rid,
        ).with_for_update()
    )
    if upload is None:
        raise ws.WorkspaceError("independent_transcription_upload_not_found", 404)
    if fence:
        fence()
    if upload.revoked_at is None:
        upload.revoked_at = now
        session.commit()
    return {"status": "revoked", "operation_id": operation_id, "revoked_at": upload.revoked_at.isoformat()}


def purge_due_recording_audio(
    c: svc.Container,
    box_id: str,
    actor_id: str,
) -> list[dict[str, Any]]:
    actor = c.session.scalar(select(Principal).where(Principal.id == actor_id).with_for_update())
    svc._require_active_human(actor, box_id=box_id, owner_required=True)
    now = _now(c)
    rows = c.session.scalars(
        select(IndependentRecordingAudioUpload).where(
            IndependentRecordingAudioUpload.box_id == box_id,
            IndependentRecordingAudioUpload.audio_purged_at.is_(None),
            IndependentRecordingAudioUpload.audio_expires_at <= now,
        ).with_for_update()
    ).all()
    receipts: list[dict[str, Any]] = []
    for row in rows:
        if row.blob_key:
            try:
                c.blob.delete(row.blob_key)
            except Exception:
                pass
        row.blob_key = None
        row.audio_purged_at = now
        receipt = {
            "upload_id": row.id,
            "retention_rule": "audio_plus_48h",
            "deleted_at": now.isoformat(),
            "outcome": "purged",
        }
        c.session.add(
            IndependentRecordingAudioPurgeReceipt(
                id=str(uuid4()),
                box_id=box_id,
                upload_id=row.id,
                retention_rule=receipt["retention_rule"],
                deleted_at=now,
                outcome="purged",
            )
        )
        receipts.append(receipt)
        c.session.add(
            AuditEvent(
                box_id=box_id,
                aggregate_type="independent_recording_audio",
                aggregate_id=row.id,
                event_type="recording_audio.purged",
                actor_principal_id=actor_id,
                outcome="purged",
                detail={"retention_rule": receipt["retention_rule"], "owner_authorized": True},
            )
        )
    c.session.commit()
    return receipts


def purge_route(
    session: Session, box_id: str, owner_id: str, wid: str, *, external: str, blob=None, clock=None
) -> dict[str, Any]:
    # Owner-triggered purge; still requires the feature enabled so live users never hit it.
    require_enabled(session, box_id)
    private.identity(session, box_id, owner_id, external)
    ws._workspace(session, box_id, owner_id, wid, writing=True, allow_private=True)
    c = svc.Container(session, clock=clock, blob=blob)
    return {"receipts": purge_due_recording_audio(c, box_id, owner_id)}
