"""Current-context and durable admission client for the first-party Core facade."""

import json
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import AwareDatetime, Field, SecretStr

from cosmas_os.adapters.capture_native_start import validate_native_start
from cosmas_os.adapters.core_capture import HttpCoreCaptureBinding
from cosmas_os.ports import capture_protocol as protocol
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_native_extension import validate_native_extension
from cosmas_os.ports.capture_recovery import (
    MAX_RECOVERY_STATE_BYTES,
    CaptureRecoveryReceipt,
    CaptureRecoveryState,
)
from cosmas_os.ports.capture_source import MAX_CAPTURE_SOURCE_BYTES, CaptureSourceEnvelope
from cosmas_os.ports.capture_working import (
    MAX_WORKING_BYTES,
    CaptureWorkingTranscript,
    canonical_hash,
)
from cosmas_os.ports.core_capture import (
    ActorRef,
    BindingRef,
    ConfiguredCaptureSelection,
    CoreCaptureAdmissionSnapshot,
    CoreCaptureBindingSnapshot,
    CoreCaptureSelection,
    CoreConsentAttestation,
    CoreInteractionCredential,
    CoreMountToken,
    TenantRef,
)
from cosmas_os.ports.core_notes import (
    CoreDraftReceipt,
    CoreNoteSelection,
    CoreSaveResolution,
    CoreTemplateReceipt,
    NoteAction,
    core_note_edit_hash,
)
from cosmas_os.ports.creator_review import (
    MAX_CREATOR_REVIEW_BYTES,
    CreatorDecisionReceipt,
    CreatorReviewView,
    ProviderEncounter,
)
from cosmas_os.ports.encounter_prep import CorePrepReceipt
from cosmas_os.ports.scribe_capture import ProtectedModel, ScribeSessionReceipt


class _ResolvedContext(ProtectedModel):
    surface: Literal["provider_assistant"]
    auth_tier: Literal["provider"]
    capabilities: list[str] = Field(max_length=100)
    tenant_id: TenantRef
    actor_id: ActorRef


class CoreAdmissionUnavailable(ConnectorUnavailable):
    """Fixed codes distinguish consent requirements, pending recovery and denial."""


class _OperationEnvelope(ProtectedModel):
    contract_version: Literal["1"]
    binding_ref: BindingRef
    workspace_id: UUID
    request_nonce: UUID
    operation: str
    receipt: dict
    checked_at: AwareDatetime


class _NoteEnvelope(ProtectedModel):
    contract_version: Literal["1"]
    binding_ref: BindingRef
    workspace_id: UUID
    request_nonce: UUID
    action: NoteAction
    receipt: dict
    checked_at: AwareDatetime


class _PrepEnvelope(ProtectedModel):
    contract_version: Literal["1"]
    binding_ref: BindingRef
    workspace_id: UUID
    request_nonce: UUID
    checked_at: AwareDatetime
    receipt: CorePrepReceipt


class HttpCoreCaptureAdmission(HttpCoreCaptureBinding):
    def provider_encounter(self, binding, credential, idempotency_key):
        """Read the original session without using the capture-admission route."""
        try:
            binding = CoreCaptureBindingSnapshot.model_validate(binding.model_dump())
            credential = CoreInteractionCredential.model_validate(credential.model_dump())
            if not 8 <= len(idempotency_key) <= 100 or not all(33 <= ord(c) <= 126 for c in idempotency_key):
                raise ValueError
            nonce = uuid4()
            data, _ = self._request("/service/v1/agent/scribe/capture-operations", {
                "binding_ref": binding.binding_ref, "workspace_id": str(binding.workspace_id),
                "request_nonce": str(nonce), "operation": {"kind": "provider_encounter"},
            }, {**self._workload_headers(), "X-Cosmaneura-Capture-Version": "1",
                "Idempotency-Key": idempotency_key,
                "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id)},
                200, ("X-Cosmaneura-Capture-Version", "1"), max_bytes=MAX_CREATOR_REVIEW_BYTES + 4096)
            envelope = _OperationEnvelope.model_validate(data)
            if (envelope.binding_ref != binding.binding_ref or envelope.workspace_id != binding.workspace_id
                or envelope.request_nonce != nonce or envelope.operation != "provider_encounter"
                or not self._now() - timedelta(seconds=30) <= envelope.checked_at <= self._now() + timedelta(seconds=5)):
                raise ValueError
            return ProviderEncounter.model_validate(envelope.receipt)
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None

    def encounter_context(self, binding, credential):
        try:
            binding = CoreCaptureBindingSnapshot.model_validate(binding.model_dump())
            credential = CoreInteractionCredential.model_validate(credential.model_dump())
            nonce = uuid4()
            data, _ = self._request("/service/v1/agent/scribe/encounter-context",
                {"binding_ref": binding.binding_ref, "workspace_id": str(binding.workspace_id),
                 "request_nonce": str(nonce)},
                {**self._workload_headers(), "X-Cosmaneura-Capture-Version": "1",
                 "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                 "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                 "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id)},
                200, ("X-Cosmaneura-Capture-Version", "1"), max_bytes=262144)
            envelope = _PrepEnvelope.model_validate(data)
            if (envelope.binding_ref != binding.binding_ref or envelope.workspace_id != binding.workspace_id
                or envelope.request_nonce != nonce or envelope.receipt.appointment_ref != binding.appointment_ref
                or not self._now() - timedelta(seconds=30) <= envelope.checked_at <= self._now() + timedelta(seconds=5)):
                raise ValueError
            return envelope.receipt
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None

    def _request(
        self, path, payload, headers, expected_status, version_header=None, max_bytes=16384,
        timeout_seconds=None,
    ):
        try:
            with self._client.stream(
                "POST",
                self._origin + path,
                json=payload,
                headers={"Accept": "application/json", "Cache-Control": "no-store", **headers},
                **({"timeout": timeout_seconds} if timeout_seconds is not None else {}),
            ) as response:
                # Authentication middleware can deny before protocol headers exist.
                # Classify the denial without reading or disclosing its body.
                if response.status_code in {401, 403, 404, 410}:
                    raise CoreAdmissionUnavailable("core_capture_access_unavailable")
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                no_store = "no-store" in {
                    part.strip().lower()
                    for part in response.headers.get("cache-control", "").split(",")
                }
                if not no_store or content_type not in {
                    "application/json",
                    "application/problem+json",
                }:
                    raise CoreAdmissionUnavailable("core_capture_receipt_invalid")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > max_bytes:
                        raise CoreAdmissionUnavailable("core_capture_receipt_invalid")
                    data.extend(chunk)
                body = json.loads(data)
                if response.status_code != expected_status:
                    code = body.get("code") if isinstance(body, dict) else ""
                    if not isinstance(code, str):
                        code = ""
                    known = {
                        (409, "CAPTURE_CONSENT_REQUIRED"): "capture_consent_required",
                        (409, "CAPTURE_CONSENT_UNAVAILABLE"): "capture_consent_unavailable",
                        (409, "CAPTURE_REQUEST_CONFLICT"): "capture_request_conflict",
                        (202, "CAPTURE_IN_PROGRESS"): "capture_in_progress",
                        (409, "CAPTURE_NOTE_CONFLICT"): "capture_note_conflict",
                        (409, "CAPTURE_SOURCE_UNAVAILABLE"): "capture_source_unavailable",
                        (503, "CAPTURE_NOTES_UNAVAILABLE"): "capture_notes_unavailable",
                        (409, "CAPTURE_OPERATION_UNAVAILABLE"): "capture_source_unavailable",
                        (409, "CAPTURE_OPERATION_CONFLICT"): "capture_request_conflict",
                    }
                    raise CoreAdmissionUnavailable(
                        known.get((response.status_code, code), "core_capture_request_unconfirmed")
                    )
                if (
                    content_type != "application/json"
                    or version_header
                    and response.headers.get(version_header[0]) != version_header[1]
                ):
                    raise CoreAdmissionUnavailable("core_capture_receipt_invalid")
                return body, response.headers
        except ConnectorUnavailable:
            raise
        except httpx.HTTPError:
            raise CoreAdmissionUnavailable("core_capture_request_unconfirmed") from None
        except (ValueError, TypeError, RecursionError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None

    def _workload_headers(self):
        try:
            token = self._workload_token()
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 8192
                or not token.isascii()
                or not token.isprintable()
                or any(c.isspace() for c in token)
            ):
                raise ValueError
        except Exception:
            raise CoreAdmissionUnavailable("core_capture_identity_unavailable") from None
        return {"Authorization": "Bearer " + token}

    def capture_note(self, binding, credential, session_id, selection):
        try:
            binding = CoreCaptureBindingSnapshot.model_validate(binding.model_dump())
            credential = CoreInteractionCredential.model_validate(credential.model_dump())
            selection = CoreNoteSelection.model_validate(selection.model_dump())
            session_id = UUID(str(session_id))
            nonce = uuid4()
            data, _ = self._request(
                "/service/v1/agent/scribe/capture-notes",
                {"binding_ref": binding.binding_ref, "workspace_id": str(binding.workspace_id),
                 "request_nonce": str(nonce), "expected_session_id": str(session_id),
                 **selection.model_dump(mode="json", exclude_none=True)},
                {**self._workload_headers(), "X-Cosmaneura-Capture-Version": "1",
                 "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                 "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                 "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id)},
                200, ("X-Cosmaneura-Capture-Version", "1"), max_bytes=1_052_672,
                timeout_seconds=100 if selection.action == "prepare" else 30,
            )
            envelope = _NoteEnvelope.model_validate(data)
            now = self._now()
            if (envelope.binding_ref != binding.binding_ref or envelope.workspace_id != binding.workspace_id
                or envelope.request_nonce != nonce or envelope.action != selection.action
                or not now - timedelta(seconds=30) <= envelope.checked_at <= now + timedelta(seconds=5)):
                raise ValueError
            receipt_type = CoreTemplateReceipt if selection.action == "templates" else CoreSaveResolution if selection.action == "resolve" else CoreDraftReceipt
            receipt = receipt_type.model_validate(envelope.receipt)
            if receipt.session_id != session_id:
                raise ValueError
            if isinstance(receipt, (CoreDraftReceipt, CoreSaveResolution)) and receipt.schema_ref != selection.schema_ref:
                raise ValueError
            if isinstance(receipt, CoreDraftReceipt):
                if receipt.notebook_source is not None and receipt.notebook_source.workspace_id != binding.workspace_id:
                    raise ValueError
                if selection.scratch_notes is not None and receipt.status == "draft":
                    if receipt.notebook_source is None or receipt.notebook_source.model_dump() != selection.scratch_notes.model_dump(exclude={"content"}):
                        raise ValueError
            if selection.action == "save" and selection.edit is not None and (
                not isinstance(receipt, CoreDraftReceipt) or receipt.status != "draft"
                or receipt.source_sha256 != selection.edit.expected_source_sha256
                or receipt.fields != selection.edit.fields
                or receipt.note_ref == selection.edit.expected_note_ref
            ):
                raise ValueError
            if isinstance(receipt, CoreSaveResolution):
                if (selection.edit is None or selection.schema_ref is None
                    or receipt.client_key != selection.edit.client_key
                    or receipt.request_sha256 != core_note_edit_hash(selection.edit, selection.schema_ref, session_id, binding.workspace_id)
                    or receipt.result_note_ref == selection.edit.expected_note_ref):
                    raise ValueError
            return receipt
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None

    def exchange_context(
        self, selection: CoreCaptureSelection, bearer: SecretStr
    ) -> CoreMountToken:
        try:
            selection = CoreCaptureSelection.model_validate(selection.model_dump())
            raw = bearer.get_secret_value()
            if (
                not 1 <= len(raw) <= 8192
                or not raw.isascii()
                or not raw.isprintable()
                or any(c.isspace() for c in raw)
            ):
                raise ValueError
            data, _ = self._request(
                "/embed/v1/context-tokens/exchange",
                {
                    "requested_surface": "provider_assistant",
                    "record_ref": selection.appointment_ref,
                },
                {"Authorization": "Bearer " + raw, "X-Cosmaneura-Embed-Version": "1.0"},
                201,
                ("X-Cosmaneura-Embed-Version", "1.0"),
            )
            token = CoreMountToken.model_validate(data)
            now = self._now()
            if (
                not now - timedelta(seconds=30) <= token.issued_at <= now + timedelta(seconds=5)
                or not token.issued_at < token.refresh_after < token.expires_at
                or token.expires_at <= now
            ):
                raise ValueError
            return token
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CoreAdmissionUnavailable("core_capture_context_invalid") from None

    def resolve_context(
        self, selection: CoreCaptureSelection, token: CoreMountToken
    ) -> CoreInteractionCredential:
        try:
            token = CoreMountToken.model_validate(token.model_dump())
            if token.expires_at <= self._now():
                raise ValueError
            turn = uuid4()
            data, headers = self._request(
                "/service/v1/agent/mount-context/resolve",
                None,
                {
                    **self._workload_headers(),
                    "X-Cosmaneura-Mount-Context": token.context_token.get_secret_value(),
                    "X-Cosmaneura-Client-Turn-ID": str(turn),
                },
                200,
            )
            context = _ResolvedContext.model_validate(data)
            if (
                context.actor_id != selection.expected_actor_ref
                or context.tenant_id != selection.expected_tenant_ref
                or headers.get("X-Cosmaneura-Client-Turn-ID") != str(turn)
            ):
                raise ValueError
            return CoreInteractionCredential(
                mount_context_token=token.context_token,
                interaction_ref=headers["X-Cosmaneura-Interaction-Ref"],
                client_turn_id=turn,
            )
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError, KeyError):
            raise CoreAdmissionUnavailable("core_capture_context_invalid") from None

    def admit_capture(
        self,
        binding: CoreCaptureBindingSnapshot,
        credential: CoreInteractionCredential,
        attestation: CoreConsentAttestation | None,
        idempotency_key: str,
        *, configured_capture: ConfiguredCaptureSelection | None = None, expected_session_id: UUID | None = None,
    ) -> CoreCaptureAdmissionSnapshot:
        try:
            binding = CoreCaptureBindingSnapshot.model_validate(binding.model_dump())
            credential = CoreInteractionCredential.model_validate(credential.model_dump())
            if expected_session_id is not None and (attestation is not None or configured_capture is not None):
                raise ValueError
            if configured_capture is not None:
                configured_capture = ConfiguredCaptureSelection.model_validate(configured_capture.model_dump())
            if attestation is not None:
                attestation = CoreConsentAttestation.model_validate(attestation.model_dump())
            if (
                not 8 <= len(idempotency_key) <= 100
                or not idempotency_key.isascii()
                or any(c.isspace() for c in idempotency_key)
            ):
                raise ValueError
            nonce = uuid4()
            data, _ = self._request(
                "/service/v1/agent/scribe/capture-admissions",
                {
                    "binding_ref": binding.binding_ref,
                    "workspace_id": str(binding.workspace_id),
                    "request_nonce": str(nonce),
                    "attestation": attestation.model_dump(mode="json") if attestation else None,
                    **({"configured_capture": configured_capture.model_dump(mode="json")} if configured_capture is not None else {}),
                    **({"expected_session_id": str(expected_session_id)} if expected_session_id is not None else
                       {"resume_current": True} if attestation is None and configured_capture is None else {}),
                },
                {
                    **self._workload_headers(),
                    "X-Cosmaneura-Capture-Version": "1",
                    "Idempotency-Key": idempotency_key,
                    "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                    "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                    "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id),
                },
                200,
                ("X-Cosmaneura-Capture-Version", "1"),
            )
            receipt = CoreCaptureAdmissionSnapshot.model_validate(data)
            now = self._now()
            if (
                (expected_session_id is not None and receipt.session_id != expected_session_id)
                or (configured_capture is not None and receipt.configured_capture != configured_capture)
                or receipt.binding_ref != binding.binding_ref
                or receipt.workspace_id != binding.workspace_id
                or receipt.appointment_ref != binding.appointment_ref
                or receipt.request_nonce != nonce
                or not now - timedelta(seconds=30)
                <= receipt.checked_at
                <= now + timedelta(seconds=5)
            ):
                raise ValueError
            return receipt
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None

    def perform_capture_operation(
        self, binding, credential, session_id, operation, idempotency_key,
        *, capture_profile: protocol.CaptureProfileReceipt | None = None,
    ):
        try:
            operation = protocol.OPERATION_ADAPTER.validate_python(
                operation.model_dump(mode="json")
            )
            binding = CoreCaptureBindingSnapshot.model_validate(binding.model_dump())
            credential = CoreInteractionCredential.model_validate(credential.model_dump())
            session_id = UUID(str(session_id))
            if not 8 <= len(idempotency_key) <= 100 or not all(
                33 <= ord(c) <= 126 for c in idempotency_key
            ):
                raise ValueError
            profile_id = getattr(operation, "profile_receipt_id", None)
            if profile_id is None:
                if capture_profile is not None:
                    raise ValueError
            else:
                if capture_profile is None:
                    raise ValueError
                profile = protocol.CaptureProfileReceipt.model_validate(
                    capture_profile.model_dump(mode="json")
                )
                if (
                    profile.session_id != session_id
                    or profile.receipt_id != profile_id
                    or profile.created_at > self._now() + timedelta(seconds=5)
                    or isinstance(operation, protocol.ReserveChunks) and (
                        operation.payload.channel not in profile.request.channels
                        or operation.payload.first_sequence_number + operation.payload.count
                        > profile.maximum_chunks_per_channel
                    )
                ):
                    raise ValueError
            nonce = uuid4()
            data, _ = self._request(
                "/service/v1/agent/scribe/capture-operations",
                {
                    "binding_ref": binding.binding_ref,
                    "workspace_id": str(binding.workspace_id),
                    "request_nonce": str(nonce),
                    "operation": operation.model_dump(mode="json"),
                },
                {
                    **self._workload_headers(),
                    "X-Cosmaneura-Capture-Version": "1",
                    "Idempotency-Key": idempotency_key,
                    "X-Cosmaneura-Mount-Context": credential.mount_context_token.get_secret_value(),
                    "X-Cosmaneura-Interaction-Ref": credential.interaction_ref,
                    "X-Cosmaneura-Client-Turn-ID": str(credential.client_turn_id),
                },
                200,
                ("X-Cosmaneura-Capture-Version", "1"),
                max_bytes=(
                    MAX_CREATOR_REVIEW_BYTES + 4096
                    if operation.kind == "creator_review"
                    else MAX_CAPTURE_SOURCE_BYTES + 4096
                    if operation.kind in {"capture_source", "correct_capture_source"}
                    else MAX_WORKING_BYTES + 4096
                    if operation.kind in {"working_transcript", "correct_transcript"}
                    else MAX_RECOVERY_STATE_BYTES + 4096
                    if operation.kind == "capture_recovery_state"
                    else MAX_CAPTURE_SOURCE_BYTES + 4096
                    if operation.kind == "transcript"
                    else 131072
                    if operation.kind == "reserve_chunks"
                    else 16384
                ),
            )
            envelope = _OperationEnvelope.model_validate(data)
            now = self._now()
            if (
                envelope.binding_ref != binding.binding_ref
                or envelope.workspace_id != binding.workspace_id
                or envelope.request_nonce != nonce
                or envelope.operation != operation.kind
                or not now - timedelta(seconds=30)
                <= envelope.checked_at
                <= now + timedelta(seconds=5)
            ):
                raise ValueError
            if isinstance(operation, protocol.NativeSourceStart):
                return validate_native_start(operation, envelope.receipt, session_id, binding.actor_ref, now)
            if isinstance(operation, protocol.NativeSourceExtension):
                return validate_native_extension(operation, envelope.receipt, session_id, binding.actor_ref, now)
            receipt_types = {
                "native_recording_context": protocol.NativeRecordingContext,
                "creator_review": CreatorReviewView,
                "decide_translation": CreatorDecisionReceipt,
                "encryption_key": protocol.EncryptionKey,
                "capabilities": protocol.LongVisitCapabilities if profile_id is not None else protocol.Capabilities,
                "capture_profile": protocol.CaptureProfileReceipt,
                "select_capture_profile": protocol.CaptureProfileReceipt,
                "bind_key": protocol.KeyReceipt,
                "issue_lease": protocol.LeaseReceipt,
                "renew_lease": protocol.LeaseReceipt,
                "capture_lease_state": protocol.LeaseState,
                "reserve_chunks": protocol.ReservationReceipt,
                "authorize_upload": protocol.UploadReceipt,
                "chunk_receipt": protocol.ChunkReceipt,
                "register_chunk": protocol.RegisteredChunk,
                "complete": ScribeSessionReceipt,
                "transcription_status": protocol.TranscriptionStatus,
                "transcript": protocol.SourceTranscript,
                "working_transcript": CaptureWorkingTranscript,
                "correct_transcript": CaptureWorkingTranscript,
                "recover_capture": CaptureRecoveryReceipt,
                "capture_recovery_state": CaptureRecoveryState,
                "capture_source": CaptureSourceEnvelope,
                "correct_capture_source": CaptureSourceEnvelope,
            }
            receipt = receipt_types[operation.kind].model_validate(envelope.receipt)
            if getattr(receipt, "session_id", session_id) != session_id:
                raise ValueError
            if isinstance(receipt, protocol.NativeRecordingContext) and receipt.workspace_id != binding.workspace_id:
                raise ValueError
            if isinstance(operation, protocol.ReserveChunks) and profile_id is not None:
                assert isinstance(receipt, protocol.ReservationReceipt)
                expected = operation.payload
                if (
                    tuple(item.sequence_number for item in receipt.reservations)
                    != tuple(range(expected.first_sequence_number, expected.first_sequence_number + expected.count))
                    or len({item.object_id for item in receipt.reservations}) != expected.count
                    or any(item.session_id != session_id or item.channel != expected.channel
                           for item in receipt.reservations)
                ):
                    raise ValueError
            if isinstance(receipt, protocol.CaptureProfileReceipt) and (
                receipt.created_at > now + timedelta(seconds=5)
                or isinstance(operation, protocol.SelectCaptureProfile)
                and receipt.request != operation.payload
            ):
                raise ValueError
            if isinstance(receipt, CaptureRecoveryReceipt):
                if (
                    not isinstance(operation, protocol.RecoverCapture)
                    or receipt.request_sha256 != canonical_hash(operation.payload)
                    or receipt.lease.issued_at > now + timedelta(seconds=5)
                ):
                    raise ValueError
            if isinstance(receipt, CaptureRecoveryState):
                if (
                    receipt.history.session_id != session_id
                    or len(receipt.model_dump_json().encode("utf-8")) > MAX_RECOVERY_STATE_BYTES
                    or any(row.lease.issued_at > now + timedelta(seconds=5)
                           for row in receipt.history.recoveries)
                    or (receipt.current_lease is not None
                        and receipt.current_lease.issued_at > now + timedelta(seconds=5))
                ):
                    raise ValueError
            if isinstance(receipt, CaptureSourceEnvelope):
                if (len(receipt.model_dump_json().encode("utf-8")) > MAX_CAPTURE_SOURCE_BYTES
                    or receipt.raw_transcript.created_at > now + timedelta(seconds=5)
                    or receipt.working_transcript.created_at > now + timedelta(seconds=5)
                    or any(row.lease.issued_at > now + timedelta(seconds=5)
                           for row in receipt.recovery_history.recoveries)):
                    raise ValueError
            if isinstance(operation, (protocol.CorrectTranscript, protocol.CorrectCaptureSource)):
                working = receipt.working_transcript if isinstance(receipt, CaptureSourceEnvelope) else receipt
                assert isinstance(working, CaptureWorkingTranscript)
                expected = operation.payload
                actual = {s.source_segment_id: s for s in working.working_source.segments}
                if (
                    working.raw_transcript_id != expected.raw_transcript_id
                    or working.raw_transcript_sha256 != expected.raw_transcript_sha256
                    or working.previous_working_sha256 != expected.expected_working_sha256
                    or working.working_source.source_transcript_version != expected.expected_working_version + 1
                    or any(e.source_segment_id not in actual or actual[e.source_segment_id].content != e.content
                           or actual[e.source_segment_id].speaker_role != e.speaker_role for e in expected.corrections)
                ):
                    raise ValueError
            if isinstance(receipt, ScribeSessionReceipt) and receipt.id != session_id:
                raise ValueError
            if (
                isinstance(receipt, protocol.ChunkReceipt)
                and receipt.reservation.session_id != session_id
            ):
                raise ValueError
            return receipt
        except ConnectorUnavailable:
            raise
        except (ValueError, TypeError, AttributeError, KeyError):
            raise CoreAdmissionUnavailable("core_capture_receipt_invalid") from None
