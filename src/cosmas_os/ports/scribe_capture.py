"""Scoped Scribe v1 admission contract; application authorization precedes this port.

Tracks the Scribe consent/session wire, including uncollected location metadata. This port is
not a browser API, a permission grant, or an assertion that capture is connected.
"""

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

OpaqueReference = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
Modality = Literal["in_person", "virtual", "phone"]


class ProtectedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<protected>)"

    def __str__(self) -> str:
        return self.__repr__()


class ScribeEncounterBinding(ProtectedModel):
    """Server-owned mapping; never derive tenant/practitioner from browser input.

    Box and Scribe tenant are separate identifiers. The receiver integration must
    independently verify owner/encounter access and current processing authority.
    """

    box_id: UUID
    owner_id: UUID
    workspace_id: UUID
    tenant_id: UUID
    appointment_id: OpaqueReference
    practitioner_id: OpaqueReference
    patient_id: OpaqueReference


class ConsentAttestation(ProtectedModel):
    modality: Modality
    participant_regions: tuple[
        Annotated[str, Field(pattern=r"^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$")], ...
    ] = Field(max_length=20)
    # Empty means location was not collected; explicit all-party consent still applies.
    method: Literal["pre_visit_form", "verbal_attestation", "phone_ivr"]
    all_parties_consented: Literal[True]
    granted_at: datetime

    @field_validator("all_parties_consented", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("explicit consent required")
        return value

    @field_validator("granted_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("consent time needs an offset")
        return value

    @field_validator("participant_regions")
    @classmethod
    def unique_regions(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate consent region")
        return tuple(sorted(value))


class ScribeConsentReceipt(ConsentAttestation):
    id: UUID
    appointment_id: OpaqueReference
    practitioner_id: OpaqueReference
    patient_id: OpaqueReference
    policy_version: str = Field(min_length=1, max_length=128)
    evidence_object_id: UUID | None = None
    revoked_at: datetime | None = None


class ScribeSessionReceipt(ProtectedModel):
    id: UUID
    appointment_id: OpaqueReference
    practitioner_id: OpaqueReference
    patient_id: OpaqueReference
    consent_record_id: UUID
    modality: Modality
    ingest_mode: Literal["chunk_upload"]
    status: Literal[
        "created", "capturing", "uploaded", "processing", "transcript_ready", "handed_off", "failed"
    ]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session time needs an offset")
        return value


class ScribeAdmissionPort(Protocol):
    def record_consent(
        self, binding: ScribeEncounterBinding, attestation: ConsentAttestation, idempotency_key: str
    ) -> ScribeConsentReceipt: ...

    def create_session(
        self, binding: ScribeEncounterBinding, consent: ScribeConsentReceipt, idempotency_key: str
    ) -> ScribeSessionReceipt: ...


class DisabledScribeAdmission:
    def record_consent(self, binding, attestation, idempotency_key):
        raise ConnectorUnavailable("scribe_connection_required")

    def create_session(self, binding, consent, idempotency_key):
        raise ConnectorUnavailable("scribe_connection_required")


def build_scribe_admission() -> ScribeAdmissionPort:
    # No live runtime selection until receiver, identity and data-flow qualification.
    return DisabledScribeAdmission()
