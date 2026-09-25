"""Private workspace authorization surrounds each first-party capture phase."""

import hashlib
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    DeadlineCorePort,
    check_capture_deadline,
    core_phase,
    current_budget,
)
from cosmas_os.models import AuditEvent, CoreCaptureAccount, ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, supports_skill
from cosmas_os.ports.capture_protocol import CaptureOperation, CaptureProfileReceipt, ReadOperation
from cosmas_os.ports.core_capture import (
    CoreCaptureAdmissionPort,
    CoreCaptureSelection,
    CoreConsentAttestation,
)
from cosmas_os.ports.core_notes import CoreNoteSelection
from cosmas_os.ports.notebook_source import NotebookSource, ScratchNotes


def notebook_snapshot(session, workspace_id, entry_id):
    row = session.scalar(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == workspace_id,
        WorkspaceEntry.kind == "scratchpad").order_by(WorkspaceEntry.revision.desc()).limit(1))
    if row is None or str(row.id) != str(entry_id):
        raise ws.WorkspaceError("capture_notebook_changed", 409)
    return ScratchNotes(workspace_id=workspace_id, entry_id=row.id, revision=row.revision,
        content=row.content, content_sha256=hashlib.sha256(row.content.encode("utf-8")).hexdigest())


def require_notebook_current(session, workspace_id, source: NotebookSource | None):
    if source is None:
        return
    if str(source.workspace_id) != str(workspace_id):
        raise ws.WorkspaceError("capture_notebook_changed", 409)
    saved = notebook_snapshot(session, workspace_id, source.entry_id)
    if NotebookSource.model_validate(saved.model_dump(exclude={"content"})) != source:
        raise ws.WorkspaceError("capture_notebook_changed", 409)


def admit(
    session: Session,
    *,
    box: str,
    actor: str,
    external_identity_id: str,
    workspace_id: str,
    bearer: SecretStr,
    reauthenticate: Callable[[], None],
    port: CoreCaptureAdmissionPort,
    attestation: CoreConsentAttestation | None,
    idempotency_key: str,
    configured_capture=None,
    operation: CaptureOperation | None = None,
    expected_session_id: UUID | None = None,
    note_selection: CoreNoteSelection | None = None,
    scratchpad_entry_id: UUID | None = None,
    bot_selection=None,
    prep: bool = False,
    binding_only: bool = False,
    finalize_note: Callable[[BaseModel], Any] | None = None,
    finalize_prep: Callable[[BaseModel], Any] | None = None,
) -> Any:
    if current_budget() is not None:
        port = DeadlineCorePort(port)

    def selection(*, finalizing: bool = False):
        check_capture_deadline()
        # Auth's identity map must not hide a revocation committed during I/O.
        session.expire_all()
        reauthenticate()
        w = ws._workspace(session, box, actor, workspace_id, writing=finalizing)
        appointment = ws._encounter(session, box, w.appointment_id, w.patient_link_id, owner=w.owner_id)
        identity = session.scalar(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.id == external_identity_id,
                ExternalIdentity.box_id == box,
                ExternalIdentity.principal_id == actor,
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
        try:
            value = CoreCaptureSelection(
                workspace_id=UUID(workspace_id),
                appointment_ref=appointment.external_id,
                expected_actor_ref=account.core_actor_ref,
                expected_tenant_ref=account.core_tenant_ref,
            )
        except ValueError:
            raise ws.WorkspaceError("capture_connection_required", 409) from None
        notebook = notebook_snapshot(session, workspace_id, scratchpad_entry_id) if scratchpad_entry_id else None
        agent_id = None
        if bot_selection is not None:
            from cosmas_os.application import provider_team
            _, bot, settings = provider_team.active_bot(session, box, actor, bot_selection.address, bot_selection.team_revision)
            allowed_role = supports_skill(settings, "encounter_prep") if prep else settings["role"] == "scribe"
            if not allowed_role or notebook is not None and not settings["include_notebook"] or prep and not settings["include_evidence"]:
                raise ws.WorkspaceError("bot_source_unavailable", 409)
            if prep:
                from cosmas_os.application import team_resources
                resource_ref = team_resources.reference(box, actor, external_identity_id, "core_preparation", account)
                team_resources.require(settings, "core_preparation", resource_ref)
            agent_id = bot.agent_id
        result = account.id, value, notebook, agent_id
        if prep and bot_selection is not None:
            result = (*result, resource_ref)
        if not finalizing:
            session.commit()
        return result

    try:
        using_admission = operation is not None or note_selection is not None
        if configured_capture is not None and (using_admission or prep or binding_only):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if binding_only and (using_admission or prep or attestation is not None or expected_session_id is not None
            or finalize_note is not None or finalize_prep is not None or scratchpad_entry_id is not None or bot_selection is not None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if prep and (using_admission or attestation is not None or expected_session_id is not None or finalize_note is not None or scratchpad_entry_id is not None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if finalize_prep is not None and (not prep or bot_selection is None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if operation is not None and note_selection is not None:
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if finalize_note is not None and (note_selection is None or note_selection.action != "read"):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if using_admission and (expected_session_id is None or attestation is not None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if scratchpad_entry_id is not None and (note_selection is None or note_selection.action not in {"read", "prepare"}):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if note_selection is not None and note_selection.scratch_notes is not None:
            raise ws.WorkspaceError("invalid_capture_request", 422)
        expected = selection()
        token = port.exchange_context(expected[1], bearer)
        if selection() != expected:
            raise ws.WorkspaceError("capture_context_changed", 409)
        credential = port.resolve_context(expected[1], token)
        if selection() != expected:
            raise ws.WorkspaceError("capture_context_changed", 409)
        binding = port.resolve_binding(expected[1], credential)
        if selection() != expected:
            raise ws.WorkspaceError("capture_context_changed", 409)
        if binding_only:
            # Stop before consent/session admission or any note/model operation.
            from cosmas_os.ports.core_capture import CoreCaptureBindingSnapshot
            if (not isinstance(binding, CoreCaptureBindingSnapshot)
                or binding.workspace_id != expected[1].workspace_id
                or binding.appointment_ref != expected[1].appointment_ref
                or binding.actor_ref != expected[1].expected_actor_ref
                or binding.tenant_ref != expected[1].expected_tenant_ref):
                raise ws.WorkspaceError("capture_context_changed", 409)
            return binding
        if prep:
            result = port.encounter_context(binding, credential)
            if selection(finalizing=bot_selection is not None or finalize_prep is not None) != expected:
                raise ws.WorkspaceError("capture_context_changed", 409)
            if finalize_prep is not None:
                return core_phase(finalize_prep, result)
            if bot_selection is not None:
                session.add(AuditEvent(box_id=box, aggregate_type="workspace", aggregate_id=workspace_id,
                    event_type="workspace.bot_prep_read", actor_principal_id=expected[3],
                    initiated_by_principal_id=actor, outcome="read",
                    detail={"snapshot_sha256": result.snapshot_sha256, "source_count": len(result.sources)}))
                session.commit()
            return result
        if operation is not None and operation.kind == "source_start" and operation.action == "stop":
            # Cessation must reach the retained owner after recording consent
            # expires or is withdrawn. Core still resolves the existing admitted
            # binding and Scribe verifies the original private owner proof; no
            # new session or capture authority is created by this path.
            assert expected_session_id is not None
            result = port.perform_capture_operation(
                binding, credential, expected_session_id, operation, idempotency_key
            )
            if selection() != expected:
                raise ws.WorkspaceError("capture_context_changed", 409)
            return result
        receipt = port.admit_capture(
            binding,
            credential,
            attestation,
            f"verify:{expected_session_id}" if using_admission else idempotency_key,
            **({"expected_session_id": expected_session_id} if using_admission else
               {"configured_capture": configured_capture} if configured_capture is not None else {}),
        )
        if selection() != expected:
            raise ws.WorkspaceError("capture_context_changed", 409)
        if using_admission:
            if receipt.session_id != expected_session_id:
                raise ws.WorkspaceError("capture_session_changed", 409)
            if note_selection is not None:
                selected_note = note_selection.model_copy(update={"scratch_notes": expected[2]})
                result = port.capture_note(binding, credential, receipt.session_id, selected_note)
            else:
                assert operation is not None
                if operation.kind in {"source_start", "source_extend"} and receipt.configured_capture is None:
                    raise ws.WorkspaceError("capture_source_unavailable", 409)
                profile_id = getattr(operation, "profile_receipt_id", None)
                if profile_id is not None:
                    profile = port.perform_capture_operation(
                        binding, credential, receipt.session_id,
                        ReadOperation(kind="capture_profile"),
                        "profile:" + hashlib.sha256(idempotency_key.encode()).hexdigest(),
                    )
                    # Profile reads cross a service boundary too. Release the
                    # prior locks and recheck local authority before reserving.
                    if selection() != expected:
                        raise ws.WorkspaceError("capture_context_changed", 409)
                    if (
                        not isinstance(profile, CaptureProfileReceipt)
                        or profile.session_id != receipt.session_id
                        or profile.receipt_id != profile_id
                    ):
                        raise ConnectorUnavailable("core_capture_receipt_invalid")
                    result = port.perform_capture_operation(
                        binding, credential, receipt.session_id, operation, idempotency_key,
                        capture_profile=profile,
                    )
                else:
                    result = port.perform_capture_operation(
                        binding, credential, receipt.session_id, operation, idempotency_key
                    )
            if selection(finalizing=finalize_note is not None or bot_selection is not None) != expected:
                raise ws.WorkspaceError("capture_context_changed", 409)
            # An OS review/action can commit while the final private workspace,
            # human, encounter and account checks remain locked. All Core I/O
            # has already completed; callbacks cannot make another remote call.
            if finalize_note is not None:
                return core_phase(finalize_note, result)
            if bot_selection is not None:
                if note_selection is not None:
                    action = note_selection.action
                else:
                    assert operation is not None
                    action = operation.kind
                session.add(AuditEvent(box_id=box, aggregate_type="workspace", aggregate_id=workspace_id,
                    event_type="workspace.bot_note_confirmed", actor_principal_id=expected[3],
                    initiated_by_principal_id=actor, outcome="confirmed",
                    detail={"session_id": str(receipt.session_id), "action": action,
                            "note_ref": getattr(result, "note_ref", None), "status": getattr(result, "status", None)}))
                session.commit()
            return result
        if bot_selection is not None:
            if selection(finalizing=True) != expected:
                raise ws.WorkspaceError("capture_context_changed", 409)
            session.add(AuditEvent(box_id=box, aggregate_type="workspace", aggregate_id=workspace_id,
                event_type="workspace.bot_capture_prepared", actor_principal_id=expected[3],
                initiated_by_principal_id=actor, outcome="prepared",
                detail={"session_id": str(receipt.session_id), "operation_ref": str(receipt.operation_ref)}))
            session.commit()
        return receipt
    except ConnectorUnavailable as error:
        known = {
            "capture_consent_required": 409,
            "capture_consent_unavailable": 409,
            "capture_request_conflict": 409,
            "capture_in_progress": 202,
            "core_capture_access_unavailable": 403,
            "capture_note_conflict": 409,
            "capture_source_unavailable": 409,
            "capture_notes_unavailable": 503,
        }
        code = str(error)
        if code in known:
            raise ws.WorkspaceError(code, known[code]) from None
        raise ws.WorkspaceError("capture_request_unconfirmed", 503) from None
    finally:
        session.rollback()
