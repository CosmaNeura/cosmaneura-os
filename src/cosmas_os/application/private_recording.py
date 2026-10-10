"""Attach device-local audio metadata without patient or upstream capture authority."""
from datetime import timedelta

from sqlalchemy import func, or_, select

from cosmas_os.application import provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, ExternalIdentity, WorkspaceAppointmentLink
from cosmas_os.ports.private_recording import (
    AttachRecording,
    BindRecordingVisit,
    FinishRecording,
    LinkRecording,
    VisitBoundRecordingSelection,
)
from cosmas_os.private_recording_models import (
    PrivateRecording,
    PrivateRecordingFinish,
    PrivateRecordingLink,
    PrivateRecordingTransfer,
    PrivateRecordingVisitBinding,
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
        # A saved clip may be mapped or finalized hours after capture, or span
        # pauses. Frames bound audio duration; metadata update time is not it.
        if (elapsed <= 0 or command.frames / 16000 > elapsed
                or command.ended_at > now + timedelta(seconds=5)):
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


def appointment_digest(appointment):
    return payload_hash({"appointment_id": appointment.id, "patient_link_id": appointment.patient_link_id,
        "source": appointment.source, "source_sha256": appointment.source_sha256,
        "external_id": appointment.external_id, "label": appointment.patient_label,
        "start_at": appointment.start_at.isoformat() if appointment.start_at else None,
        "source_local_start": appointment.source_local_start.isoformat() if appointment.source_local_start else None})


def visit_source_digest(recording, finish_row, binding):
    return payload_hash({"contract": "cosmas.private-recording.visit-source.v1",
        "recording_id": recording.id, "origin_workspace_id": recording.workspace_id,
        "attach_sha256": recording.request_sha256, "finish_sha256": finish_row.request_sha256,
        "manifest_sha256": finish_row.manifest_sha256, "target_workspace_id": binding.target_workspace_id,
        "appointment_sha256": binding.appointment_sha256, "binding_request_sha256": binding.request_sha256})


def checked_visit_binding(s, box, owner, wid, external, rid):
    origin, row = checked(s, box, owner, wid, external, rid)
    view(s, row)  # The original finish/link receipts must remain intact.
    binding = s.scalar(select(PrivateRecordingVisitBinding).where(
        PrivateRecordingVisitBinding.recording_id == rid))
    if binding is None:
        return row, None, None
    target = ws._workspace(s, box, owner, binding.target_workspace_id)
    if target.appointment_id is None:
        raise ws.WorkspaceError("private_recording_visit_changed", 409)
    appointment = ws._encounter(s, box, target.appointment_id, target.patient_link_id, owner=owner)
    finish_row = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == rid))
    command = BindRecordingVisit.model_validate(binding.request)
    if (binding.box_id != box or binding.owner_id != owner or binding.origin_workspace_id != wid
        or finish_row is None or finish_row.id != binding.finish_id or finish_row.capture_state != "finished"
        or binding.request_key != str(command.idempotency_key) or binding.request_sha256 != digest("visit-binding", command)
        or str(command.target_workspace_id) != target.id or str(command.appointment_id) != appointment.id
        or binding.target_revision != command.expected_target_revision
        or binding.appointment_id != appointment.id or binding.patient_link_id != appointment.patient_link_id
        or binding.appointment_sha256 != appointment_digest(appointment)
        or binding.source_sha256 != visit_source_digest(row, finish_row, binding)
        or origin.appointment_id is not None and origin.appointment_id != target.appointment_id):
        raise ws.WorkspaceError("private_recording_visit_changed", 409)
    return row, binding, target


def visit_binding_view(binding):
    return {"contract": "cosmas.private-recording.visit-binding.v1", "receipt_id": binding.id,
        "recording_id": binding.recording_id, "origin_workspace_id": binding.origin_workspace_id,
        "target_workspace_id": binding.target_workspace_id, "appointment_id": binding.appointment_id,
        "request": binding.request, "request_sha256": binding.request_sha256,
        "appointment_sha256": binding.appointment_sha256, "source_sha256": binding.source_sha256}


def read_visit_binding(s, box, owner, wid, rid, *, external):
    _, binding, _ = checked_visit_binding(s, box, owner, wid, external, rid)
    return None if binding is None else visit_binding_view(binding)


def bind_visit(s, box, owner, wid, rid, command, *, external, fence):
    # identity() serializes human-owned metadata writes; this also fences a
    # same-recording link/admission racing with the new association.
    origin, row = checked(s, box, owner, wid, external, rid)
    _, prior, _ = checked_visit_binding(s, box, owner, wid, external, rid)
    sha = digest("visit-binding", command)
    if prior is not None:
        if prior.request_key != str(command.idempotency_key) or prior.request_sha256 != sha:
            raise ws.WorkspaceError("idempotency_conflict", 409)
        return visit_binding_view(prior)
    target = ws._workspace(s, box, owner, str(command.target_workspace_id))
    if target.appointment_id is None:
        raise ws.WorkspaceError("private_recording_visit_changed", 409)
    appointment = ws._encounter(s, box, target.appointment_id, target.patient_link_id, owner=owner)
    finish_row = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == rid))
    if (target.revision != command.expected_target_revision or target.appointment_id != str(command.appointment_id)
        or finish_row is None or finish_row.capture_state != "finished"
        or origin.appointment_id is not None and origin.appointment_id != target.appointment_id):
        raise ws.WorkspaceError("private_recording_visit_changed", 409)
    if s.scalar(select(PrivateRecordingTransfer.id).where(or_(
        PrivateRecordingTransfer.recording_id == rid, PrivateRecordingTransfer.workspace_id == target.id))):
        raise ws.WorkspaceError("private_recording_visit_in_use", 409)
    binding = PrivateRecordingVisitBinding(recording_id=rid, origin_workspace_id=wid,
        target_workspace_id=target.id, box_id=box, owner_id=owner, appointment_id=appointment.id,
        patient_link_id=appointment.patient_link_id, finish_id=finish_row.id, target_revision=target.revision,
        request_key=str(command.idempotency_key), request_sha256=sha, appointment_sha256=appointment_digest(appointment),
        request=command.model_dump(mode="json"))
    binding.source_sha256 = visit_source_digest(row, finish_row, binding)
    s.add(binding)
    s.flush()
    audit(s, row, "visit_bound", sha)
    fence()
    s.commit()
    return visit_binding_view(binding)


def capture_source(s, box, owner, target, external, selected):
    if isinstance(selected, VisitBoundRecordingSelection):
        row, binding, current_target = checked_visit_binding(s, box, owner,
            str(selected.origin_workspace_id), external, str(selected.recording_id))
        if (binding is None or current_target is None or current_target.id != target.id
            or binding.id != str(selected.visit_binding_receipt_id)
            or binding.source_sha256 != selected.source_sha256):
            raise ws.WorkspaceError("capture_saved_recording_changed", 409)
    else:
        _, row = checked(s, box, owner, target.id, external, str(selected.recording_id))
        view(s, row)
        link = s.scalar(select(PrivateRecordingLink).where(PrivateRecordingLink.recording_id == row.id))
        appointment_link = s.get(WorkspaceAppointmentLink, link.workspace_link_receipt_id) if link else None
        if (link is None or link.id != str(selected.link_receipt_id)
            or link.source_sha256 != selected.source_sha256 or appointment_link is None
            or appointment_link.appointment_id != target.appointment_id
            or appointment_link.patient_link_id != target.patient_link_id
            or s.scalar(select(PrivateRecordingVisitBinding.id).where(PrivateRecordingVisitBinding.recording_id == row.id))):
            raise ws.WorkspaceError("capture_saved_recording_changed", 409)
    finish_row = s.scalar(select(PrivateRecordingFinish).where(PrivateRecordingFinish.recording_id == row.id))
    if (finish_row is None or finish_row.capture_state != "finished"
        or finish_row.manifest_sha256 != selected.manifest_sha256
        or finish_row.chunks != selected.chunks or finish_row.frames != selected.frames):
        raise ws.WorkspaceError("capture_saved_recording_changed", 409)
    return row, finish_row
