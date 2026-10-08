"""Attach device-local audio metadata without patient or upstream capture authority."""
from datetime import timedelta

from sqlalchemy import func, or_, select

from cosmas_os.application import provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, ExternalIdentity, WorkspaceAppointmentLink
from cosmas_os.ports.private_recording import (
    MAX_SECONDS,
    AttachRecording,
    FinishRecording,
    LinkRecording,
)
from cosmas_os.private_recording_models import (
    PrivateRecording,
    PrivateRecordingFinish,
    PrivateRecordingLink,
)


def digest(kind, command):
    return payload_hash({"contract": "cosmas.private-recording." + kind + ".v1",
                         "request": command.model_dump(mode="json")})


def identity(s, box, owner, external):
    ws._human(s, box, owner, creating=True)
    row = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == external,
        ExternalIdentity.box_id == box, ExternalIdentity.principal_id == owner,
        ExternalIdentity.provider == "clerk", ExternalIdentity.active.is_(True)).with_for_update(read=True))
    if row is None:
        raise ws.WorkspaceError("private_recording_access_denied", 403)


def scope(s, box, owner, wid, external):
    identity(s, box, owner, external)
    w = ws._workspace(s, box, owner, wid, writing=True, allow_private=True)
    if w.draft_title is None:
        raise ws.WorkspaceError("private_recording_notebook_required", 409)
    return w


def checked(s, box, owner, wid, external, rid):
    w = scope(s, box, owner, wid, external)
    row = s.scalar(select(PrivateRecording).where(PrivateRecording.id == rid,
        PrivateRecording.workspace_id == wid, PrivateRecording.box_id == box,
        PrivateRecording.owner_id == owner).with_for_update())
    if row is None:
        raise ws.WorkspaceError("private_recording_not_found", 404)
    if row.external_identity_id != external:
        raise ws.WorkspaceError("private_recording_access_denied", 403)
    command = AttachRecording.model_validate(row.request)
    if row.request_sha256 != digest("attach", command):
        raise ws.WorkspaceError("private_recording_unavailable", 503)
    version, bot, settings = provider_team.active_bot(s, box, owner, command.bot.address, command.bot.team_revision)
    if settings["role"] != "scribe" or bot.agent_id != row.agent_id or version.id != row.team_revision_id:
        raise ws.WorkspaceError("private_recording_scope_changed", 409)
    return w, row


def view(s, row):
    finish = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == row.id))
    link = s.scalar(select(PrivateRecordingLink).where(PrivateRecordingLink.recording_id == row.id))
    if finish is not None and finish.request_sha256 != digest("finish", FinishRecording.model_validate(finish.request)):
        raise ws.WorkspaceError("private_recording_unavailable", 503)
    if link is not None:
        if finish is None or link.request_sha256 != digest("link", LinkRecording.model_validate(link.request)):
            raise ws.WorkspaceError("private_recording_unavailable", 503)
        appointment_link = s.get(WorkspaceAppointmentLink, link.workspace_link_receipt_id)
        if appointment_link is None or appointment_link.workspace_id != row.workspace_id or link.source_sha256 != source_digest(row, finish, appointment_link):
            raise ws.WorkspaceError("private_recording_unavailable", 503)
    return {"contract": "cosmas.private-recording.v1", "custody": "local_device_metadata",
        "recording_id": row.id, "local_recording_id": row.local_recording_id,
        "workspace_id": row.workspace_id, "workspace_revision": row.workspace_revision,
        "owner_id": row.owner_id, "box_id": row.box_id, "agent_id": row.agent_id,
        "team_revision_id": row.team_revision_id, "recovery_scope": row.recovery_scope,
        "attach_sha256": row.request_sha256, "started_at": row.started_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "state": "linked_metadata" if link else finish.capture_state if finish else "unfinished",
        "finish": None if finish is None else {"receipt_id": finish.id,
            "request_sha256": finish.request_sha256, "manifest_sha256": finish.manifest_sha256,
            "chunks": finish.chunks, "frames": finish.frames,
            "ended_at": finish.ended_at.isoformat() if finish.ended_at else None},
        "link": None if link is None else {"receipt_id": link.id,
            "workspace_link_receipt_id": link.workspace_link_receipt_id,
            "source_sha256": link.source_sha256, "request_sha256": link.request_sha256},
        "upstream_capture_admitted": False, "audio_uploaded": False, "transcription_started": False}


def audit(s, row, action, sha):
    s.add(AuditEvent(box_id=row.box_id, aggregate_type="private_recording", aggregate_id=row.id,
        event_type="workspace.private_recording_" + action, actor_principal_id=row.owner_id,
        outcome="saved", payload_hash=sha, detail={"workspace_id": row.workspace_id,
        "request_sha256": sha, "custody": "local_device_metadata"}))


def resolve(s, box, owner, wid, command, *, external):
    scope(s, box, owner, wid, external)  # Serializes with the exact original attach before not_found.
    row = s.scalar(select(PrivateRecording).where(PrivateRecording.owner_id == owner,
        or_(PrivateRecording.request_key == str(command.idempotency_key),
            PrivateRecording.local_recording_id == str(command.local_recording_id))))
    if row is None:
        return {"outcome": "not_found", "recording": None}
    if (row.workspace_id != wid or row.request_key != str(command.idempotency_key)
            or row.request_sha256 != digest("attach", command)):
        raise ws.WorkspaceError("idempotency_conflict", 409)
    checked(s, box, owner, wid, external, row.id)
    return {"outcome": "saved", "recording": view(s, row)}


def attach(s, box, owner, wid, command, *, external, fence):
    w = scope(s, box, owner, wid, external)
    existing = resolve(s, box, owner, wid, command, external=external)
    if existing["recording"] is not None:
        return existing["recording"]
    if w.appointment_id is not None or w.revision != command.expected_workspace_revision:
        raise ws.WorkspaceError("private_recording_scope_changed", 409)
    version, bot, settings = provider_team.active_bot(s, box, owner, command.bot.address, command.bot.team_revision)
    if settings["role"] != "scribe":
        raise ws.WorkspaceError("private_recording_scribe_required", 409)
    now = s.scalar(select(func.clock_timestamp()))
    if not now - timedelta(days=7) <= command.started_at <= now + timedelta(seconds=5):
        raise ws.WorkspaceError("invalid_private_recording_timestamp", 422)
    if s.scalar(select(func.count()).select_from(PrivateRecording).where(
            PrivateRecording.workspace_id == wid)) >= 100:
        raise ws.WorkspaceError("private_recording_limit", 409)
    row = PrivateRecording(workspace_id=wid, box_id=box, owner_id=owner,
        external_identity_id=external, agent_id=bot.agent_id, team_revision_id=version.id,
        workspace_revision=w.revision, local_recording_id=str(command.local_recording_id),
        request_key=str(command.idempotency_key), request_sha256=digest("attach", command),
        recovery_scope=payload_hash({"contract": "cosmas-private-drafts-v1", "box_id": box, "owner_id": owner}),
        request=command.model_dump(mode="json"), started_at=command.started_at)
    s.add(row)
    s.flush()
    audit(s, row, "attached", row.request_sha256)
    fence()
    s.commit()
    return view(s, row)


def finish(s, box, owner, wid, rid, command, *, external, fence):
    _, row = checked(s, box, owner, wid, external, rid)
    sha = digest("finish", command)
    prior = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == rid))
    if prior is not None:
        if prior.request_key != str(command.idempotency_key) or prior.request_sha256 != sha:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        return view(s, row)
    if command.ended_at is not None:
        elapsed = (command.ended_at - row.started_at).total_seconds()
        now = s.scalar(select(func.clock_timestamp()))
        if not 0 < elapsed <= MAX_SECONDS or command.ended_at > now + timedelta(seconds=5):
            raise ws.WorkspaceError("invalid_private_recording_timestamp", 422)
    values = command.model_dump(exclude={"idempotency_key"})
    outcome = PrivateRecordingFinish(recording_id=rid, request_key=str(command.idempotency_key),
        request_sha256=sha, request=command.model_dump(mode="json"), **values)
    s.add(outcome)
    s.flush()
    audit(s, row, "finished", sha)
    fence()
    s.commit()
    return view(s, row)


def link(s, box, owner, wid, rid, command, *, external, fence):
    w, row = checked(s, box, owner, wid, external, rid)
    sha = digest("link", command)
    prior = s.scalar(select(PrivateRecordingLink).where(PrivateRecordingLink.recording_id == rid))
    if prior is not None:
        if prior.request_key != str(command.idempotency_key) or prior.request_sha256 != sha:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        return view(s, row)
    finish_row = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == rid))
    appointment_link = s.scalar(select(WorkspaceAppointmentLink).where(
        WorkspaceAppointmentLink.id == str(command.workspace_link_receipt_id),
        WorkspaceAppointmentLink.workspace_id == wid, WorkspaceAppointmentLink.box_id == box,
        WorkspaceAppointmentLink.owner_id == owner))
    if (finish_row is None or finish_row.capture_state == "unknown" or appointment_link is None
            or w.appointment_id is None
            or w.appointment_id != appointment_link.appointment_id
            or w.patient_link_id != appointment_link.patient_link_id
            or w.revision != command.expected_workspace_revision):
        raise ws.WorkspaceError("private_recording_link_unavailable", 409)
    ws._encounter(s, box, w.appointment_id, w.patient_link_id, owner=owner)
    source_sha = source_digest(row, finish_row, appointment_link)
    s.add(PrivateRecordingLink(recording_id=rid, finish_id=finish_row.id,
        workspace_link_receipt_id=appointment_link.id, request_key=str(command.idempotency_key),
        request_sha256=sha, source_sha256=source_sha, request=command.model_dump(mode="json")))
    s.flush()
    audit(s, row, "linked", sha)
    fence()
    s.commit()
    return view(s, row)


def read(s, box, owner, wid, rid, *, external):
    _, row = checked(s, box, owner, wid, external, rid)
    return view(s, row)


def source_digest(recording, finish_row, appointment_link):
    return payload_hash({"recording_id": recording.id, "attach_sha256": recording.request_sha256,
        "finish_sha256": finish_row.request_sha256, "manifest_sha256": finish_row.manifest_sha256,
        "workspace_link_sha256": appointment_link.request_hash})
