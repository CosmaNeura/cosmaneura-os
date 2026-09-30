"""Proposed W8 first-party binding read. A snapshot is never capture authority.

The Core receiver must reauthorize each admission/read/correction independently.
No browser, model, or retained receipt may select the expected identity mapping.
"""

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, SecretStr, field_validator

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_protocol import CaptureOperation, CaptureProfileReceipt
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreNoteSelection, CoreTemplateReceipt
from cosmas_os.ports.encounter_prep import CorePrepReceipt
from cosmas_os.ports.scribe_capture import ProtectedModel

AppointmentRef = Annotated[str, Field(pattern=r"^appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
ActorRef = Annotated[str, Field(pattern=r"^authority_actor_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
TenantRef = Annotated[str, Field(pattern=r"^authority_tenant_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
BindingRef = Annotated[str, Field(pattern=r"^scribe_capture_binding_[0-7][0-9a-hjkmnp-tv-z]{25}$")]


class CoreCaptureSelection(ProtectedModel):
    """Expected scope from a reviewed server mapping, not a client request body."""

    workspace_id: UUID
    appointment_ref: AppointmentRef
    expected_actor_ref: ActorRef
    expected_tenant_ref: TenantRef


class CoreInteractionCredential(ProtectedModel):
    mount_context_token: SecretStr
    interaction_ref: str = Field(min_length=16, max_length=256, pattern=r"^[A-Za-z0-9._~-]+$")
    client_turn_id: UUID

    @field_validator("mount_context_token")
    @classmethod
    def bounded_token(cls, value):
        token = value.get_secret_value()
        if not 16 <= len(token) <= 8192 or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
            raise ValueError("invalid context credential")
        return value


class CoreCaptureBindingSnapshot(ProtectedModel):
    contract_version: Literal["1"]
    binding_ref: BindingRef
    workspace_id: UUID
    appointment_ref: AppointmentRef
    actor_ref: ActorRef
    tenant_ref: TenantRef
    request_nonce: UUID
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scope check time requires an offset")
        return value


class CoreCaptureBindingPort(Protocol):
    def resolve_binding(
        self, selection: CoreCaptureSelection, credential: CoreInteractionCredential
    ) -> CoreCaptureBindingSnapshot: ...


class CoreMountToken(ProtectedModel):
    context_token: SecretStr
    token_type: Literal["Bearer"]
    issued_at: AwareDatetime
    refresh_after: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("context_token")
    @classmethod
    def bounded_token(cls, value):
        return CoreInteractionCredential.bounded_token(value)


class CoreConsentAttestation(ProtectedModel):
    modality: Literal["in_person", "virtual", "phone"]
    participant_regions: tuple[Annotated[str, Field(pattern=r"^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$")], ...] = Field(max_length=16)
    # Match Core: empty location metadata does not waive explicit recording consent.
    method: Literal["verbal_attestation"]
    all_parties_consented: Literal[True]
    granted_at: AwareDatetime

    @field_validator("all_parties_consented", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("Explicit consent required")
        return value


class ConfiguredCaptureSelection(ProtectedModel):
    schema_version: Literal["1.0"]
    language_mode: Literal["en-US", "en-US+es-US"]


class CoreCaptureAdmissionSnapshot(ProtectedModel):
    contract_version: Literal["1"]
    operation_ref: Annotated[str, Field(pattern=r"^scribe_admission_[0-7][0-9a-hjkmnp-tv-z]{25}$")]
    binding_ref: BindingRef
    workspace_id: UUID
    appointment_ref: AppointmentRef
    consent_record_id: UUID
    session_id: UUID
    status: Literal["admitted"]
    configured_capture: ConfiguredCaptureSelection | None = None
    request_nonce: UUID
    checked_at: AwareDatetime


class CoreCaptureAdmissionPort(CoreCaptureBindingPort, Protocol):
    def provider_encounter(self, binding: CoreCaptureBindingSnapshot,
        credential: CoreInteractionCredential, idempotency_key: str) -> BaseModel: ...
    def encounter_context(self, binding: CoreCaptureBindingSnapshot,
        credential: CoreInteractionCredential) -> CorePrepReceipt: ...
    def exchange_context(self, selection: CoreCaptureSelection, bearer: SecretStr) -> CoreMountToken: ...
    def resolve_context(self, selection: CoreCaptureSelection, token: CoreMountToken) -> CoreInteractionCredential: ...
    def admit_capture(
        self, binding: CoreCaptureBindingSnapshot, credential: CoreInteractionCredential,
        attestation: CoreConsentAttestation | None, idempotency_key: str,
        *, configured_capture: ConfiguredCaptureSelection | None = None, expected_session_id: UUID | None = None,
    ) -> CoreCaptureAdmissionSnapshot: ...
    def perform_capture_operation(
        self, binding: CoreCaptureBindingSnapshot, credential: CoreInteractionCredential,
        session_id: UUID, operation: CaptureOperation, idempotency_key: str,
        *, capture_profile: CaptureProfileReceipt | None = None,
    ) -> BaseModel: ...
    def capture_note(
        self, binding: CoreCaptureBindingSnapshot, credential: CoreInteractionCredential,
        session_id: UUID, selection: CoreNoteSelection,
    ) -> CoreDraftReceipt | CoreTemplateReceipt: ...
    def close(self) -> None: ...


class DisabledCoreCaptureBinding:
    def resolve_binding(self, selection, credential):
        raise ConnectorUnavailable("core_capture_connection_required")


def build_core_capture_binding() -> CoreCaptureBindingPort:
    # Receiver, reviewed server mapping, and current-context acquisition remain unqualified.
    return DisabledCoreCaptureBinding()
