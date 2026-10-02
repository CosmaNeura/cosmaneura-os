"""Dormant receiver-owned patient lookup; correspondence is never a booking grant.

Names and optional DOB are explicit human search facts. Only the receiver can
resolve an opaque choice to a patient. No local Box/visit identifier crosses
this contract, and a verified identity still needs a separate human review.
"""

import hashlib
import json
import re
from datetime import UTC, date, timedelta
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scribe_capture import ProtectedModel

Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
MAX_PREVIEW_BYTES = 8192
MAX_VERIFY_BYTES = 2048


def patient_digest(domain: str, value: dict) -> str:
    raw = json.dumps([domain, value], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class AppointmentPatientSelector(ProtectedModel):
    kind: Literal["appointment"]
    # Resolved from the current imported Scheduling visit, never a browser UUID.
    appointment_ref: UUID


class SearchPatientSelector(ProtectedModel):
    kind: Literal["search"]
    query: str = Field(strict=True, min_length=1, max_length=120)
    birth_date: date | None

    @field_validator("birth_date", mode="before")
    @classmethod
    def explicit_date(cls, value):
        return _birth_date(value)

    @field_validator("query")
    @classmethod
    def explicit_text(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid_patient_search")
        return value


PatientSelector = Annotated[AppointmentPatientSelector | SearchPatientSelector, Field(discriminator="kind")]


def _birth_date(value):
    if value is not None and not (type(value) is date or
        isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
        raise ValueError("invalid_patient_birth_date")
    return value


class PatientPreviewRequest(ProtectedModel):
    request_nonce: UUID
    expected_actor_id: UUID
    selector: PatientSelector
    limit: int = Field(strict=True, ge=5, le=5)


class PatientChoice(ProtectedModel):
    choice_ref: UUID
    display_name: str = Field(strict=True, min_length=1, max_length=120)
    birth_date: date | None
    # Receiver-owned monotonic revision: visible text alone cannot detect ABA.
    subject_revision: int = Field(strict=True, ge=1, le=9_223_372_036_854_775_807)
    identity_sha256: Digest

    @field_validator("birth_date", mode="before")
    @classmethod
    def explicit_date(cls, value):
        return _birth_date(value)

    @field_validator("display_name")
    @classmethod
    def safe_identity(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid_patient_identity")
        return value

    @model_validator(mode="after")
    def exact_identity(self):
        if self.identity_sha256 != patient_digest("cosmas-scheduling-patient-identity.v1",
            self.model_dump(mode="json", exclude={"identity_sha256"})):
            raise ValueError("invalid_patient_identity")
        return self


class PatientPreview(ProtectedModel):
    contract_version: Literal["1"]
    request_nonce: UUID
    practice_id: UUID
    actor_id: UUID
    checked_at: AwareDatetime
    lookup_ref: UUID
    expires_at: AwareDatetime
    choices: tuple[PatientChoice, ...] = Field(max_length=5)
    more: bool = Field(strict=True)
    preview_sha256: Digest

    @model_validator(mode="after")
    def exact_preview(self):
        if (not self.checked_at < self.expires_at <= self.checked_at + timedelta(minutes=5)
            or len({v.choice_ref for v in self.choices}) != len(self.choices)
            or self.more and len(self.choices) != 5
            or self.preview_sha256 != patient_digest("cosmas-scheduling-patient-preview.v1",
                self.model_dump(mode="json", exclude={"preview_sha256"}))):
            raise ValueError("invalid_patient_preview")
        return self


class PatientVerifyRequest(ProtectedModel):
    request_nonce: UUID
    expected_actor_id: UUID
    lookup_ref: UUID
    choice_ref: UUID
    identity_sha256: Digest


class PatientVerification(ProtectedModel):
    contract_version: Literal["1"]
    request_nonce: UUID
    practice_id: UUID
    actor_id: UUID
    lookup_ref: UUID
    patient_id: UUID
    identity: PatientChoice
    verified_at: AwareDatetime
    expires_at: AwareDatetime
    verification_sha256: Digest

    @model_validator(mode="after")
    def exact_verification(self):
        if (not self.verified_at < self.expires_at <= self.verified_at + timedelta(minutes=5)
            or self.verification_sha256 != patient_digest("cosmas-scheduling-patient-verification.v1",
                self.model_dump(mode="json", exclude={"verification_sha256"}))):
            raise ValueError("invalid_patient_verification")
        return self


def validate_preview(selection, request, value, now):
    if (selection.expected_actor_id is None or request.expected_actor_id != selection.expected_actor_id
        or value.request_nonce != request.request_nonce or value.practice_id != selection.practice_id
        or value.actor_id != selection.expected_actor_id
        or not now - timedelta(seconds=30) <= value.checked_at <= now + timedelta(seconds=5)
        or value.expires_at <= now
        or any(v.birth_date and v.birth_date > now.astimezone(UTC).date() for v in value.choices)):
        raise ConnectorUnavailable("scheduling_patient_receipt_invalid")


def validate_verification(selection, request, preview, value, now):
    choice = next((v for v in preview.choices if v.choice_ref == request.choice_ref), None)
    if (choice is None or choice.identity_sha256 != request.identity_sha256
        or request.expected_actor_id != selection.expected_actor_id
        or preview.practice_id != selection.practice_id or preview.actor_id != selection.expected_actor_id
        or request.lookup_ref != preview.lookup_ref or preview.expires_at <= now
        or value.request_nonce != request.request_nonce or value.lookup_ref != request.lookup_ref
        or value.practice_id != selection.practice_id or value.actor_id != selection.expected_actor_id
        or value.identity != choice or not now - timedelta(seconds=30) <= value.verified_at <= now + timedelta(seconds=5)
        or value.expires_at <= now):
        raise ConnectorUnavailable("scheduling_patient_receipt_invalid")


class SchedulingPatientSetupPort(Protocol):
    def preview(self, selection: SchedulingSelection, request: PatientPreviewRequest) -> PatientPreview: ...

    def verify(self, selection: SchedulingSelection, request: PatientVerifyRequest,
               preview: PatientPreview) -> PatientVerification: ...


class UnconnectedSchedulingPatientSetup:
    def preview(self, selection, request):
        raise ConnectorUnavailable("scheduling_patient_setup_unavailable")

    def verify(self, selection, request, preview):
        raise ConnectorUnavailable("scheduling_patient_setup_unavailable")


def build_scheduling_patient_setup() -> SchedulingPatientSetupPort:
    return UnconnectedSchedulingPatientSetup()
