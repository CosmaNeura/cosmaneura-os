"""Current receiver reads compose an exact F-8 proposal; no remote mutation."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from cosmas_os.application import appointment_work as work
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AppointmentObservation, AppointmentWork
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, supports_skill
from cosmas_os.ports.scheduling import (
    AvailabilityWindow,
    GoogleSchedulingAvailability,
    SchedulingSelection,
)
from cosmas_os.ports.scheduling_actions import AppointmentIntent, ObservedAppointment

# This imported observation is only a selector. The receiver must independently
# return the exact current patient/practice/resource correspondence.
SCHEDULING_SOURCE = "cosmas_scheduling"


def _current(s, box, owner, wid, identity_id, bot, reauthenticate, *, keep_locks=False, configuration=None):
    from cosmas_os.application import team_resources
    s.rollback()
    reauthenticate()
    w = ws._workspace(s, box, owner, wid, writing=True)
    account, patient, selection = work._current(s, w, identity_id, configuration=configuration)
    _, installed, configuration = team.active_bot(s, box, owner, bot.address, bot.team_revision)
    if not supports_skill(configuration, "calendar_availability") or not configuration["include_evidence"]:
        raise ws.WorkspaceError("bot_source_unavailable")
    resource_ref = team_resources.reference(box, owner, identity_id, "scheduling_context", account)
    team_resources.require(configuration, "scheduling_context", resource_ref)
    observation = s.get(AppointmentObservation, w.appointment_id)
    assert observation is not None
    reference = None
    if observation.source == SCHEDULING_SOURCE:
        try:
            reference = UUID(observation.external_id)
        except (TypeError, ValueError):
            raise ws.WorkspaceError("scheduling_appointment_correspondence_required") from None
    context = (account.id, patient.id, selection, installed.agent_id,
               observation.id, reference, account.label, resource_ref)
    if not keep_locks:
        s.commit()
    return context


def _receipt(port, context):
    selected, reference = context[2], context[5]
    if reference is None:
        raise ws.WorkspaceError("scheduling_appointment_correspondence_required")
    result = port.read_appointment(selected, reference)
    try:
        if not isinstance(result, ObservedAppointment):
            raise ValueError
        result = ObservedAppointment.model_validate(result.model_dump(warnings=False))
        now = datetime.now(UTC)
        if (result.selection != selected or result.appointment.id != reference
            or not now - timedelta(seconds=30) <= result.observed_at <= now + timedelta(seconds=5)):
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise ConnectorUnavailable("scheduling_receipt_invalid") from None


def read_current(s, *, box, owner, workspace_id, external_identity_id, bot, port, reauthenticate, configuration=None):
    try:
        initial = _current(s, box, owner, workspace_id, external_identity_id, bot, reauthenticate, configuration=configuration)
        result = _receipt(port, initial) if initial[5] is not None else None
        if _current(s, box, owner, workspace_id, external_identity_id, bot, reauthenticate, keep_locks=True, configuration=configuration) != initial:
            raise ws.WorkspaceError("scheduling_context_changed")
        s.commit()
        return {"workspace_id": workspace_id, "label": initial[6],
                "appointment": result.appointment.model_dump(mode="json") if result else None,
                "checked_at": result.observed_at.isoformat() if result else None}
    except ConnectorUnavailable:
        s.rollback()
        raise ws.WorkspaceError("scheduling_unavailable", 503) from None
    except Exception:
        s.rollback()
        raise


def prepare(s, *, box, owner, workspace_id, external_identity_id, body,
            availability_port, appointment_port, reauthenticate, configuration: Settings | None = None):
    fingerprint = payload_hash({"contract": "appointment.prepare.v1", "request": body.model_dump(mode="json")})
    try:
        work._proposal_gate(s, configuration)
        # Recover a committed response before requiring new source access.
        s.rollback()
        reauthenticate()
        work._proposal_gate(s, configuration)
        w = ws._workspace(s, box, owner, workspace_id, writing=True)
        prior = s.scalar(select(AppointmentWork).where(AppointmentWork.workspace_id == w.id,
                                                      AppointmentWork.idempotency_key == body.idempotency_key))
        if prior is not None:
            if prior.request_hash != fingerprint:
                raise ws.WorkspaceError("idempotency_conflict")
            result = work.read(s, box, owner, workspace_id, prior.ticket_id, configuration=configuration)
            s.commit()
            return result
        s.commit()
        initial = _current(s, box, owner, workspace_id, external_identity_id, body.bot, reauthenticate, configuration=configuration)
        before = _receipt(appointment_port, initial).appointment if body.action != "book" else None
        google = None
        if body.action != "cancel":
            # Match the exact selected slot again; the browser's old display is
            # neither a reservation nor an attestation of Google coverage.
            assert body.slot is not None
            window = AvailabilityWindow(starts_at=body.slot.starts_at, ends_at=body.slot.ends_at)
            selection = SchedulingSelection.model_validate(initial[2].model_dump(
                exclude={"patient_link_id", "patient_id"}, warnings=False))
            result = availability_port.verified_availability(selection, window)
            try:
                if not isinstance(result, GoogleSchedulingAvailability):
                    raise ValueError
                result = GoogleSchedulingAvailability.model_validate(result.model_dump(warnings=False))
                now = datetime.now(UTC)
                if (result.selection != selection or result.window != window or body.slot not in result.slots
                    or not now - timedelta(seconds=30) <= result.google.checked_at <= now + timedelta(seconds=5)):
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise ConnectorUnavailable("scheduling_receipt_invalid") from None
            google = result.google
        if _current(s, box, owner, workspace_id, external_identity_id, body.bot, reauthenticate, keep_locks=True, configuration=configuration) != initial:
            raise ws.WorkspaceError("scheduling_context_changed")
        now = datetime.now(UTC)
        expiry = min(now + timedelta(minutes=3), google.checked_at + timedelta(minutes=5)) if google else now + timedelta(minutes=3)
        try:
            intent = AppointmentIntent(action=body.action, selection=initial[2], expected=before,
                                       slot=body.slot, google=google, expires_at=expiry)
        except (ValueError, TypeError):
            raise ws.WorkspaceError("appointment_selection_unavailable") from None
        return work.propose(s, box, owner, workspace_id, external_identity_id=external_identity_id,
                            intent=intent, key=body.idempotency_key, share=True,
                            request_fingerprint=fingerprint, configuration=configuration)
    except ConnectorUnavailable:
        s.rollback()
        raise ws.WorkspaceError("scheduling_unavailable", 503) from None
    except Exception:
        s.rollback()
        raise
