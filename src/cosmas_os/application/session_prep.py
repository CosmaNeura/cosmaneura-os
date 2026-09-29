"""Current private encounter authority around Core's prepared-brief lifecycle."""

import hashlib
from uuid import UUID, uuid5

from sqlalchemy import select

from cosmas_os.application import provider_team, team_resources
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import check_capture_deadline
from cosmas_os.application.prep_work import _contains_secret
from cosmas_os.models import AuditEvent, CoreCaptureAccount, ExternalIdentity
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, supports_skill
from cosmas_os.ports.core_capture import CoreCaptureSelection
from cosmas_os.ports.core_session_prep import CoreSessionPrepReceipt


def public_brief(receipt, *, private_tokens=()):
    """Keep internal Core references out of the UI; preserve citation links."""

    def opaque(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else None

    try:
        receipt = CoreSessionPrepReceipt.model_validate(
            receipt.model_dump(mode="python"), strict=True
        )
    except (ValueError, TypeError, AttributeError):
        raise ws.WorkspaceError("session_prep_receipt_invalid", 503) from None
    value = receipt.result
    brief = value.prepared_brief.model_dump(mode="json") if value.prepared_brief else None
    if brief:
        for item in (
            brief["recap"],
            *brief["trajectory_and_material_changes"],
            *brief["talking_points"],
            *brief["open_threads"],
            *brief["cautions"],
            *brief["suggested_outline"],
            *([brief["patient_reported"]] if brief["patient_reported"] else []),
        ):
            text = item.get("text", item.get("summary", ""))
            if not text.strip() or "\0" in text or _contains_secret(text, private_tokens):
                raise ws.WorkspaceError("session_prep_receipt_invalid", 503)
            item["source_refs"] = [opaque(ref) for ref in item["source_refs"]]
    return {
        "state": value.state,
        "freshness": value.freshness,
        "completeness": value.completeness,
        "brief_id": opaque(value.brief_ref),
        "brief_version": value.brief_version,
        "generated_at": value.brief_generated_at.isoformat() if value.brief_generated_at else None,
        "current_through": value.current_through.isoformat() if value.current_through else None,
        "prepared_brief": brief,
        "sources": [
            {
                "source_id": opaque(source.source_ref),
                "source_class": source.source_class,
                "included": source.included,
                "source_version": source.source_version,
                "source_at": source.source_at.isoformat() if source.source_at else None,
                "author_class": source.author_class,
                "reason_code": source.reason_code,
            }
            for source in value.provenance
        ],
        "retry_after_seconds": value.retry_after_seconds,
        "reason_code": value.reason_code,
    }


def read(
    session, *, box, owner, external_identity_id, workspace_id, bot, bearer, idempotency_key,
    reauthenticate, port
):
    def scope(*, final=False):
        check_capture_deadline()
        session.expire_all()
        reauthenticate()
        workspace = ws._workspace(session, box, owner, workspace_id)
        appointment = ws._encounter(
            session, box, workspace.appointment_id, workspace.patient_link_id, owner=owner
        )
        identity = session.scalar(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.id == external_identity_id,
                ExternalIdentity.box_id == box,
                ExternalIdentity.principal_id == owner,
                ExternalIdentity.active.is_(True),
            )
            .with_for_update(read=True)
        )
        account = session.scalar(
            select(CoreCaptureAccount)
            .where(
                CoreCaptureAccount.external_identity_id == external_identity_id,
                CoreCaptureAccount.revoked_at.is_(None),
            )
            .with_for_update(read=True)
        )
        if identity is None or account is None or appointment.source != "cosmaneura_core":
            raise ws.WorkspaceError("capture_connection_required", 409)
        _, member, settings = provider_team.active_bot(
            session, box, owner, bot.address, bot.team_revision
        )
        if not supports_skill(settings, "encounter_prep") or not settings["include_evidence"]:
            raise ws.WorkspaceError("bot_source_unavailable", 409)
        resource = team_resources.reference(
            box, owner, external_identity_id, "core_preparation", account
        )
        team_resources.require(settings, "core_preparation", resource)
        try:
            selected = CoreCaptureSelection(
                workspace_id=UUID(workspace_id),
                appointment_ref=appointment.external_id,
                expected_actor_ref=account.core_actor_ref,
                expected_tenant_ref=account.core_tenant_ref,
            )
        except ValueError:
            raise ws.WorkspaceError("capture_connection_required", 409) from None
        result = (selected, account.id, member.agent_id, resource)
        if not final:
            session.commit()  # No database locks across a Core HTTP phase.
        return result

    def current(*, final=False):
        if scope(final=final) != expected:
            raise ws.WorkspaceError("session_prep_context_changed", 409)

    try:
        expected = scope()
        token = port.exchange_context(expected[0], bearer)
        current()
        # A retransmitted API request must not silently become another Core
        # action. Core either reuses this turn's exact mount or rejects the new
        # mount with a conflict; a deliberate UI refresh supplies a new key.
        turn = uuid5(expected[0].workspace_id, f"session-prep:{external_identity_id}:{idempotency_key}")
        context = port.resolve_context(expected[0], token, turn)
        current()
        selection = port.accept_action(context)
        current()
        receipt = port.read_brief(selection)
        current()
        port.complete_action(selection, receipt)
        current()
        # Core rechecks the live source digest before replaying an artifact
        # receipt, even after the canonical action closes. Never publish a
        # source revoked while the action's final phase was being recorded.
        confirmed = port.read_brief(selection)
        current(final=True)
        if confirmed != receipt:
            raise ws.WorkspaceError("session_prep_context_changed", 409)
        result = public_brief(
            confirmed,
            private_tokens=(
                bearer.get_secret_value(),
                token.context_token.get_secret_value(),
                context.credential.interaction_ref,
                context.context_snapshot_ref,
                selection.source_turn_ref,
            ),
        )
        session.add(
            AuditEvent(
                box_id=box,
                aggregate_type="workspace",
                aggregate_id=workspace_id,
                event_type="workspace.session_prep_read",
                actor_principal_id=expected[2],
                initiated_by_principal_id=owner,
                outcome=confirmed.result.state,
                detail={
                    "receipt_ref": confirmed.tool_call_ref,
                    "brief_id": result["brief_id"],
                    "source_count": confirmed.result.source_count,
                },
            )
        )
        session.commit()
        return {"contract_version": 1, "workspace_id": workspace_id, "receipt": result}
    except ConnectorUnavailable as error:
        code = str(error)
        status = (
            403
            if code == "session_prep_access_unavailable"
            else 409
            if code == "session_prep_request_conflict"
            else 503
        )
        raise ws.WorkspaceError(
            code
            if code in {"session_prep_access_unavailable", "session_prep_request_conflict"}
            else "session_prep_unavailable",
            status,
        ) from None
    finally:
        session.rollback()
