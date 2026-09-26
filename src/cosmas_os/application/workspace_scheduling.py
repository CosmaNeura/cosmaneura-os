"""Current private owner and bot scope around a read-only Scheduling request."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from cosmas_os.application import provider_team as team
from cosmas_os.application import team_resources
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, ExternalIdentity, SchedulingAccount
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, supports_skill
from cosmas_os.ports.scheduling import GoogleSchedulingAvailability, SchedulingSelection


def read_availability(session, *, box, owner, external_identity_id, workspace_id,
                      bot, window, port, reauthenticate):
    def current(*, final=False):
        session.rollback()
        reauthenticate()
        ws._workspace(session, box, owner, workspace_id, writing=True)
        identity = session.scalar(select(ExternalIdentity).where(
            ExternalIdentity.id == external_identity_id, ExternalIdentity.box_id == box,
            ExternalIdentity.principal_id == owner, ExternalIdentity.active.is_(True),
        ).with_for_update(read=True))
        account = session.scalar(select(SchedulingAccount).where(
            SchedulingAccount.external_identity_id == external_identity_id,
            SchedulingAccount.revoked_at.is_(None),
        ).with_for_update(read=True))
        if identity is None or account is None:
            raise ws.WorkspaceError("scheduling_connection_required", 409)
        _, installed, settings = team.active_bot(session, box, owner, bot.address, bot.team_revision)
        if not supports_skill(settings, "calendar_availability") or not settings["include_evidence"]:
            raise ws.WorkspaceError("bot_source_unavailable", 409)
        resource_ref = team_resources.reference(box, owner, external_identity_id, "scheduling_context", account)
        team_resources.require(settings, "scheduling_context", resource_ref)
        selection = SchedulingSelection(box_id=box, owner_id=owner,
            practice_id=account.practice_id, expected_actor_id=account.actor_id,
            practitioner_id=account.practitioner_id, location_id=account.location_id,
            appointment_type_id=account.appointment_type_id)
        result = account.id, selection, installed.agent_id, account.label, resource_ref
        if not final:
            session.commit()
        return result

    try:
        expected = current()
        result = port.verified_availability(expected[1], window)
        if current(final=True) != expected:
            raise ws.WorkspaceError("scheduling_context_changed", 409)
        if not isinstance(result, GoogleSchedulingAvailability):
            raise ConnectorUnavailable("scheduling_receipt_invalid")
        try:
            result = GoogleSchedulingAvailability.model_validate(result.model_dump(warnings=False))
        except (ValueError, TypeError):
            raise ConnectorUnavailable("scheduling_receipt_invalid") from None
        now = datetime.now(UTC)
        if (result.selection != expected[1] or result.window != window
            or not now - timedelta(seconds=30) <= result.google.checked_at <= now + timedelta(seconds=5)):
            raise ConnectorUnavailable("scheduling_receipt_invalid")
        session.add(AuditEvent(box_id=box, aggregate_type="workspace", aggregate_id=workspace_id,
            actor_principal_id=expected[2], initiated_by_principal_id=owner,
            event_type="workspace.bot_availability_read", outcome="read",
            detail={"receipt_sha256": payload_hash(result.model_dump(mode="json")),
                    "slot_count": len(result.slots)}))
        session.commit()
        return {"workspace_id": workspace_id, "label": expected[3], "source": "google_primary",
                "window": window.model_dump(mode="json"),
                "checked_at": result.google.checked_at.isoformat(),
                "valid_until": (result.google.checked_at + timedelta(seconds=60)).isoformat(),
                "slots": [slot.model_dump(mode="json") for slot in result.slots]}
    except ConnectorUnavailable:
        session.rollback()
        raise ws.WorkspaceError("scheduling_unavailable", 503) from None
    except Exception:
        session.rollback()
        raise
