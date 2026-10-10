"""Private workspace authorization surrounds each first-party capture phase."""

import hashlib
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, SecretStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import (
    DeadlineCorePort,
    check_capture_deadline,
    core_phase,
    current_budget,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    AuditEvent,
    CoreCaptureAccount,
    ExternalIdentity,
    WorkspaceEntry,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable, supports_skill
from cosmas_os.ports.capture_protocol import (
    CaptureOperation,
    CaptureProfileReceipt,
    NativeRecordingContext,
    ReadOperation,
)
from cosmas_os.ports.core_capture import (
    ConfiguredCaptureSelection,
    CoreCaptureAdmissionPort,
    CoreCaptureSelection,
    CoreConsentAttestation,
)
from cosmas_os.ports.core_notes import CoreNoteSelection
from cosmas_os.ports.notebook_source import NotebookSource, ScratchNotes
from cosmas_os.private_recording_models import (
    PrivateRecordingTransfer,
    PrivateRecordingTransferAttempt,
    PrivateRecordingTransferRejection,
    PrivateRecordingTransferSession,
)


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
    configured_capture: ConfiguredCaptureSelection | None = None,
    saved_recording=None,
    renew_saved_consent: bool = False,
    operation: CaptureOperation | None = None,
    expected_session_id: UUID | None = None,
    note_selection: CoreNoteSelection | None = None,
    scratchpad_entry_id: UUID | None = None,
    bot_selection=None,
    prep: bool = False,
    binding_only: bool = False,
    existing_recording: bool = False,
    finalize_existing: Callable[[BaseModel], Any] | None = None,
    finalize_note: Callable[[BaseModel], Any] | None = None,
    finalize_prep: Callable[[BaseModel], Any] | None = None,
) -> Any:
    if current_budget() is not None:
        port = DeadlineCorePort(port)

    transfer_id = None
    transfer_sha = None
    def selection(*, finalizing: bool = False):
        nonlocal transfer_id, transfer_sha
        check_capture_deadline()
        # Auth's identity map must not hide a revocation committed during I/O.
        session.expire_all()
        reauthenticate()
        w = ws._workspace(session, box, actor, workspace_id, writing=finalizing)
        if w.appointment_id is None:
            raise ws.WorkspaceError("capture_connection_required", 409)
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
        selected_source = saved_recording
        transfer_query = select(PrivateRecordingTransfer).where(PrivateRecordingTransfer.workspace_id == workspace_id)
        if saved_recording is not None:
            transfer_query = transfer_query.where(PrivateRecordingTransfer.recording_id == str(saved_recording.recording_id))
        elif expected_session_id is not None:
            transfer_query = transfer_query.join(PrivateRecordingTransferSession).where(PrivateRecordingTransferSession.session_id == str(expected_session_id))
        transfer = None if prep or binding_only or existing_recording or saved_recording is None and expected_session_id is None else session.scalar(transfer_query.with_for_update(of=PrivateRecordingTransfer))
        if transfer is None and expected_session_id is not None and session.scalar(
            select(PrivateRecordingTransfer.id).where(PrivateRecordingTransfer.workspace_id == workspace_id).limit(1)) is not None:
            recorded_legacy = session.scalar(select(AuditEvent.id).where(
                AuditEvent.aggregate_id == workspace_id, AuditEvent.event_type == "workspace.bot_capture_prepared",
                AuditEvent.detail["session_id"].astext == str(expected_session_id)).limit(1))
            if recorded_legacy is None:
                raise ws.WorkspaceError("capture_saved_recording_changed", 409)
        transfer_session = session.get(PrivateRecordingTransferSession, transfer.id) if transfer is not None else None
        if transfer is not None and selected_source is None:
            if expected_session_id is None or transfer_session is None or str(transfer_session.session_id) != str(expected_session_id):
                raise ws.WorkspaceError("capture_saved_recording_changed", 409)
            from cosmas_os.ports.private_recording import (
                SavedRecordingSelection,
                VisitBoundRecordingSelection,
            )
            selected_source = TypeAdapter(SavedRecordingSelection | VisitBoundRecordingSelection).validate_python(transfer.request["source"])
        if selected_source is not None:
            from cosmas_os.application import private_recording
            recording, finish = private_recording.capture_source(session, box, actor, w,
                external_identity_id, selected_source)
            if bot_selection is not None and agent_id != recording.agent_id:
                raise ws.WorkspaceError("capture_saved_recording_changed", 409)
            if operation is not None and operation.kind in {"source_start", "source_extend", "native_recording_context"}:
                raise ws.WorkspaceError("capture_source_unavailable", 409)
            if operation is not None and operation.kind == "complete":
                channels = operation.payload.channels
                if len(channels) != 1 or channels[0].channel != "microphone" or channels[0].final_sequence_number != finish.chunks - 1:
                    raise ws.WorkspaceError("capture_saved_recording_changed", 409)
            if saved_recording is not None:
                if attestation is None or configured_capture is None or bot_selection is None:
                    raise ws.WorkspaceError("invalid_capture_request", 422)
                document = {"source": saved_recording.model_dump(mode="json"),
                    "attestation": attestation.model_dump(mode="json"), "configured": configured_capture.model_dump(mode="json"),
                    "bot": bot_selection.model_dump(mode="json")}
                sha = payload_hash(document)
                if transfer is None:
                    if renew_saved_consent:
                        raise ws.WorkspaceError("capture_saved_recording_changed", 409)
                    transfer = PrivateRecordingTransfer(recording_id=recording.id, workspace_id=workspace_id,
                        request=document, request_sha256=sha)
                    session.add(transfer)
                    session.flush()
                if transfer.recording_id != recording.id or payload_hash(transfer.request) != transfer.request_sha256:
                    raise ws.WorkspaceError("capture_saved_recording_changed", 409)
                if transfer.request_sha256 != sha:
                    attempt = session.scalar(select(PrivateRecordingTransferAttempt).where(
                        PrivateRecordingTransferAttempt.transfer_id == transfer.id,
                        PrivateRecordingTransferAttempt.request_sha256 == sha))
                    if attempt is None:
                        last = session.scalar(select(PrivateRecordingTransferAttempt).where(
                            PrivateRecordingTransferAttempt.transfer_id == transfer.id).order_by(
                            PrivateRecordingTransferAttempt.created_at.desc(), PrivateRecordingTransferAttempt.id.desc()).limit(1))
                        prior_sha = last.request_sha256 if last is not None else transfer.request_sha256
                        prior_document = last.request if last is not None else transfer.request
                        rejection = session.get(PrivateRecordingTransferRejection, (transfer.id, prior_sha))
                        if (not renew_saved_consent or transfer_session is not None or rejection is None
                            or payload_hash(prior_document) != prior_sha
                            or any(document[k] != prior_document[k] for k in ("source", "configured", "bot"))
                            or any(document["attestation"][k] != prior_document["attestation"][k] for k in document["attestation"] if k != "granted_at")):
                            raise ws.WorkspaceError("capture_saved_recording_changed", 409)
                        attempt = PrivateRecordingTransferAttempt(transfer_id=transfer.id, prior_request_sha256=prior_sha,
                            request_sha256=sha, request=document)
                        session.add(attempt)
                        session.flush()
                    if payload_hash(attempt.request) != sha:
                        raise ws.WorkspaceError("capture_saved_recording_changed", 409)
            if transfer is None or payload_hash(transfer.request) != transfer.request_sha256:
                raise ws.WorkspaceError("capture_saved_recording_changed", 409)
            transfer_id, transfer_sha = transfer.id, sha if saved_recording is not None else transfer.request_sha256
        result = account.id, value, notebook, agent_id, transfer_sha
        if prep and bot_selection is not None:
            result = (*result, resource_ref)
        if not finalizing:
            session.commit()
        return result

    try:
        if type(renew_saved_consent) is not bool or renew_saved_consent and saved_recording is None:
            raise ws.WorkspaceError("invalid_capture_request", 422)
        using_admission = operation is not None or note_selection is not None
        if saved_recording is not None and (using_admission or prep or binding_only or existing_recording
                or attestation is None or configured_capture is None or bot_selection is None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if existing_recording and (configured_capture is not None or using_admission or prep or binding_only
            or attestation is not None or expected_session_id is not None or scratchpad_entry_id is not None
            or bot_selection is not None or finalize_note is not None or finalize_prep is not None):
            raise ws.WorkspaceError("invalid_capture_request", 422)
        if finalize_existing is not None and not existing_recording:
            raise ws.WorkspaceError("invalid_capture_request", 422)
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
        if binding_only or existing_recording:
            # Stop before consent/session admission or any note/model operation.
            from cosmas_os.ports.core_capture import CoreCaptureBindingSnapshot
            if (not isinstance(binding, CoreCaptureBindingSnapshot)
                or binding.workspace_id != expected[1].workspace_id
                or binding.appointment_ref != expected[1].appointment_ref
                or binding.actor_ref != expected[1].expected_actor_ref
                or binding.tenant_ref != expected[1].expected_tenant_ref):
                raise ws.WorkspaceError("capture_context_changed", 409)
            if binding_only:
                return binding
            from cosmas_os.ports.creator_review import ProviderEncounter
            result = port.provider_encounter(binding, credential, idempotency_key)
            if not isinstance(result, ProviderEncounter):
                raise ws.WorkspaceError("capture_request_unconfirmed", 503)
            if selection(finalizing=finalize_existing is not None) != expected:
                raise ws.WorkspaceError("capture_context_changed", 409)
            # The remote receiver has verified the original session and consent.
            # Publication uses this same final local scope lock; no admission,
            # key registration, capture lease or source-start call occurs here.
            return core_phase(finalize_existing, result) if finalize_existing is not None else result
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
            f"verify:{expected_session_id}" if using_admission else
                "saved:" + hashlib.sha256(
                    f"{saved_recording.recording_id}:{saved_recording.source_sha256}".encode("ascii")
                ).hexdigest() if saved_recording is not None else idempotency_key,
            expected_session_id=expected_session_id if using_admission else None,
            configured_capture=None if using_admission else configured_capture,
            **({"recording_key_sha256":hashlib.sha256(
                f"{saved_recording.recording_id}:{saved_recording.source_sha256}".encode("ascii")
            ).hexdigest(), "recover_legacy_request":True} if saved_recording is not None else {}),
        )
        if selection() != expected:
            raise ws.WorkspaceError("capture_context_changed", 409)
        if (receipt.workspace_id != binding.workspace_id or receipt.binding_ref != binding.binding_ref
            or receipt.appointment_ref != binding.appointment_ref):
            raise ws.WorkspaceError("capture_context_changed", 409)
        if transfer_id is not None:
            prior = session.get(PrivateRecordingTransferSession, transfer_id)
            if (prior is not None and (str(prior.session_id) != str(receipt.session_id)
                or prior.receipt["consent_record_id"] != str(receipt.consent_record_id)
                or prior.receipt["operation_ref"] != receipt.operation_ref
                or prior.receipt.get("configured_capture") != (receipt.configured_capture.model_dump(mode="json") if receipt.configured_capture else None))
                or configured_capture is not None and receipt.configured_capture != configured_capture):
                raise ws.WorkspaceError("capture_saved_recording_changed", 409)
        if using_admission:
            if receipt.session_id != expected_session_id:
                raise ws.WorkspaceError("capture_session_changed", 409)
            if note_selection is not None:
                selected_note = note_selection.model_copy(update={"scratch_notes": expected[2]})
                result = port.capture_note(binding, credential, receipt.session_id, selected_note)
            else:
                assert operation is not None
                if operation.kind in {"source_start", "source_extend", "native_recording_context"} and receipt.configured_capture is None:
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
                if operation.kind == "native_recording_context" and (
                    not isinstance(result, NativeRecordingContext)
                    or result.workspace_id != binding.workspace_id
                    or result.session_id != receipt.session_id
                ):
                    raise ConnectorUnavailable("core_capture_receipt_invalid")
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
            if saved_recording is not None:
                prior = session.get(PrivateRecordingTransferSession, transfer_id)
                document = receipt.model_dump(mode="json")
                if prior is None:
                    session.add(PrivateRecordingTransferSession(transfer_id=transfer_id, session_id=str(receipt.session_id), receipt=document))
                    session.flush()
                elif str(prior.session_id) != str(receipt.session_id) or prior.receipt != document:
                    # Volatile checked_at/nonces may change on a verified resume;
                    # the immutable session and consent must remain the same.
                    if str(prior.session_id) != str(receipt.session_id) or prior.receipt["consent_record_id"] != str(receipt.consent_record_id):
                        raise ws.WorkspaceError("capture_saved_recording_changed", 409)
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
            "upload_authorization_expired": 409,
            "capture_in_progress": 202,
            "core_capture_access_unavailable": 403,
            "capture_note_conflict": 409,
            "capture_source_unavailable": 409,
            "capture_notes_unavailable": 503,
        }
        code = str(error)
        if code == "capture_recording_consent_required" and saved_recording is not None:
            if selection(finalizing=True) != expected or transfer_id is None or transfer_sha is None:
                raise ws.WorkspaceError("capture_context_changed", 409) from None
            if session.get(PrivateRecordingTransferSession, transfer_id) is not None:
                raise ws.WorkspaceError("capture_saved_recording_changed", 409) from None
            if session.get(PrivateRecordingTransferRejection, (transfer_id, transfer_sha)) is None:
                session.add(PrivateRecordingTransferRejection(transfer_id=transfer_id, request_sha256=transfer_sha))
                session.commit()
            raise ws.WorkspaceError(code, 409) from None
        if code in known:
            raise ws.WorkspaceError(code, known[code]) from None
        raise ws.WorkspaceError("capture_request_unconfirmed", 503) from None
    finally:
        session.rollback()
