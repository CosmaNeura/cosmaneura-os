"""Open one ordinary private notebook from a freshly authorized Core reference."""

from sqlalchemy import select

from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AppointmentObservation, AuditEvent, EncounterWorkspace, PatientLink


def existing_notebook(s, identity, appointment_ref):
    return s.scalar(select(EncounterWorkspace).join(AppointmentObservation,
        AppointmentObservation.id == EncounterWorkspace.appointment_id).where(
        EncounterWorkspace.box_id == identity.box_id,
        EncounterWorkspace.owner_id == identity.principal_id,
        AppointmentObservation.source_owner_id == identity.principal_id,
        AppointmentObservation.source == "cosmaneura_core",
        AppointmentObservation.external_id == appointment_ref))


def open_selected(s, *, identity, account, discovery, budget, canonical_workspace_id=None):
    # core_connection owns the active human write lock and has rechecked the
    # identity/account after the remote read. Never accept renderer identity IDs.
    if account is None or len(discovery.encounters) != 1:
        raise ws.WorkspaceError("core_connection_changed", 409)
    box, owner = identity.box_id, identity.principal_id
    snapshot = discovery.encounters[0]
    selected = snapshot.appointment
    pair = "core-private:" + payload_hash({"box": box, "owner": owner,
        "tenant": account.core_tenant_ref, "patient": snapshot.patient.patient_ref})
    link = s.scalar(select(PatientLink).where(PatientLink.box_id == box,
        PatientLink.source_pair_key == pair).with_for_update())
    if link is not None and (link.source_owner_id != owner or link.source_account_id != account.id
                            or link.state != "confirmed" or link.revoked_at is not None):
        raise ws.WorkspaceError("core_connection_review_required", 409)
    if link is None:
        link = PatientLink(box_id=box, source_pair_key=pair, label=snapshot.patient.display_name,
            source_owner_id=owner, source_account_id=account.id, confirmed_by_principal_id=owner,
            attested_at=discovery.checked_at, state="confirmed")
        s.add(link)
        s.flush()
    appointment = s.scalar(select(AppointmentObservation).where(
        AppointmentObservation.box_id == box, AppointmentObservation.source_owner_id == owner,
        AppointmentObservation.source == "cosmaneura_core",
        AppointmentObservation.external_id == selected.appointment_ref).with_for_update())
    if appointment is not None and appointment.patient_link_id != link.id:
        # Moving a visit to another patient must never reassign a saved notebook.
        raise ws.WorkspaceError("core_connection_review_required", 409)
    if appointment is None:
        appointment = AppointmentObservation(box_id=box, source_owner_id=owner,
            source="cosmaneura_core", external_id=selected.appointment_ref, patient_link_id=link.id)
        s.add(appointment)
    changed = appointment.source_sha256 != snapshot.source_sha256
    appointment.patient_label = snapshot.patient.display_name
    appointment.start_at = selected.appointment_date if selected.timezone_known else None
    appointment.source_local_start = None if selected.timezone_known else selected.appointment_date
    appointment.source_sha256 = snapshot.source_sha256
    link.label = snapshot.patient.display_name
    s.flush()
    workspace = s.scalar(select(EncounterWorkspace).where(EncounterWorkspace.box_id == box,
        EncounterWorkspace.owner_id == owner, EncounterWorkspace.appointment_id == appointment.id))
    if canonical_workspace_id is not None:
        canonical_workspace_id = str(canonical_workspace_id)
        occupied = s.get(EncounterWorkspace, canonical_workspace_id)
        if ((workspace is not None and workspace.id != canonical_workspace_id)
            or occupied is not None and occupied is not workspace):
            # Never rekey an existing notebook or replace another creator's work.
            raise ws.WorkspaceError("core_existing_recording_conflict", 409)
    if workspace is None:
        workspace = EncounterWorkspace(box_id=box, owner_id=owner, appointment_id=appointment.id,
            patient_link_id=link.id, create_key="core:"+appointment.id, revision=1,
            **({"id": canonical_workspace_id} if canonical_workspace_id is not None else {}))
        s.add(workspace)
        s.flush()
        ws._audit(s, workspace, "created")
    if changed:
        s.add(AuditEvent(box_id=box, aggregate_type="workspace", aggregate_id=workspace.id,
            event_type="workspace.core_reference_observed", actor_principal_id=owner,
            outcome="saved", detail={"source_sha256":snapshot.source_sha256}))
    result = {"workspace_id":workspace.id, "appointment_id":appointment.id}
    budget.check()
    # References and the empty notebook commit together. No clinical write,
    # generated note or provider-team command is part of this operation.
    s.commit()
    return result
