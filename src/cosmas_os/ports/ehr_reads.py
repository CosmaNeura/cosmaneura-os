"""Closed private EHR snapshot shapes and their deliberately smaller display projection."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ProviderId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]
Status = Literal["Scheduled", "Confirmed", "Checked Out", "Cancelled", "With Doctor",
                 "In Room", "Checked In", "In Room - Vitals Taken", "Not Seen", "Billed"]
Coverage = Literal["end_of_results", "more_rows_available"]


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


class Window(Protected):
    starts_at: datetime
    ends_at: datetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("aware_time_required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7):
            raise ValueError("bounded_window_required")
        return self


class Practice(Protected):
    label: str = Field(strict=True, min_length=1, max_length=200)
    timezone: str = Field(strict=True, min_length=1, max_length=100)

    @field_validator("timezone")
    @classmethod
    def timezone_known(cls, value):
        ZoneInfo(value)
        return value


class PatientDisplay(Protected):
    first_name: str = Field(strict=True, min_length=1, max_length=70)
    last_name: str = Field(strict=True, min_length=1, max_length=70)
    birth_date: date


class WindowItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    selectable: bool = Field(strict=True)


class VerifiedItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    patient: PatientDisplay


class CommonObservation(Protected):
    provider: Literal["elation"] = "elation"
    mode: Literal["synthetic"] = "synthetic"
    practice: Practice
    observed_at: datetime
    window: Window
    coverage: Coverage


class WindowObservation(CommonObservation):
    kind: Literal["window"]
    items: tuple[WindowItem, ...] = Field(max_length=25)


class VerifiedObservation(CommonObservation):
    kind: Literal["verified_visit"]
    item: VerifiedItem


class ProblemDisplay(Protected):
    description: str = Field(strict=True, min_length=1, max_length=200)
    status: Literal["Active", "Controlled", "Resolved"]
    start_date: date
    resolved_date: date | None
    verification_status: Literal["confirmed", "differential", "entered_in_error", "provisional", "refuted", "unconfirmed", ""] | None

    @field_validator("description")
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("invalid_problem_description")
        return value


    @model_validator(mode="after")
    def resolved_status(self):
        if self.resolved_date is not None and self.status != "Resolved":
            raise ValueError("invalid_problem_resolution")
        return self


class ProblemList(Protected):
    coverage: Literal["end_of_results", "more_rows_available", "unknown"]
    total_count: int | None = Field(strict=True, ge=0, le=2147483647)
    items: tuple[ProblemDisplay, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def consistent_count(self):
        count = len(self.items)
        if (self.total_count is not None and self.total_count < count
                or self.coverage == "end_of_results" and self.total_count is not None and self.total_count != count
                or self.coverage == "more_rows_available" and (not count or self.total_count is not None and self.total_count <= count)):
            raise ValueError("invalid_problem_coverage")
        return self


class ProblemsItem(VerifiedItem):
    problems: ProblemList


class VerifiedParent(Protected):
    observation_id: UUID
    source_sha256: Digest
    item_sha256: Digest


class ProblemsObservation(CommonObservation):
    kind: Literal["verified_problems"]
    parent: VerifiedParent
    item: ProblemsItem


class PrivateAppointment(Protected):
    appointment_id: ProviderId
    patient_id: ProviderId | None
    physician_id: ProviderId
    starts_at: datetime
    ends_at: datetime
    status: Status | None
    scheduled_date_raw: str = Field(strict=True, min_length=1, max_length=40)
    deleted_at: datetime | None


class PrivatePatient(PatientDisplay):
    patient_id: ProviderId
    primary_physician_id: ProviderId
    deleted_at: datetime | None


class PrivateItem(Protected):
    handle: UUID
    appointment: PrivateAppointment
    patient: PrivatePatient | None


class PrivateSnapshot(Protected):
    transport: Literal["mock", "vendor_sandbox"] = "mock"
    binding_sha256: Digest
    request_sha256: Digest
    items: tuple[PrivateItem, ...] = Field(max_length=25)
    provider_sources: tuple[Digest, ...] = Field(min_length=1, max_length=2)


class PrivateProblem(ProblemDisplay):
    problem_id: ProviderId
    patient_id: ProviderId
    practice_id: ProviderId


class ProblemsPrivateSnapshot(PrivateSnapshot):
    provider_sources: tuple[Digest, ...] = Field(min_length=3, max_length=3)
    problems: tuple[PrivateProblem, ...] = Field(max_length=25)


TebraStatus = Literal["Confirmed", "Check-in", "No-show", "Check-out", "Rescheduled", "Scheduled", "Cancelled"]


class TebraPatientDisplay(Protected):
    full_name: str = Field(strict=True, min_length=1, max_length=255)
    birth_date: date


class TebraWindowItem(WindowItem):
    status: TebraStatus


class TebraVerifiedItem(Protected):
    handle: UUID
    sha256: Digest
    starts_at: datetime
    ends_at: datetime
    status: TebraStatus
    patient: TebraPatientDisplay


class TebraCommonObservation(Protected):
    provider: Literal["tebra"]
    mode: Literal["synthetic"]
    practice: Practice
    observed_at: datetime
    window: Window
    coverage: Literal["returned_rows_only"]


class TebraWindowObservation(TebraCommonObservation):
    kind: Literal["window"]
    items: tuple[TebraWindowItem, ...] = Field(max_length=25)


class TebraVerifiedObservation(TebraCommonObservation):
    kind: Literal["verified_visit"]
    item: TebraVerifiedItem


class TebraPrivateAppointment(Protected):
    appointment_id: ProviderId
    patient_id: ProviderId
    starts_at: datetime
    ends_at: datetime
    status: TebraStatus


class TebraPrivatePatient(TebraPatientDisplay):
    patient_id: ProviderId


class TebraPrivateItem(Protected):
    handle: UUID
    appointment: TebraPrivateAppointment
    patient: TebraPrivatePatient | None


class TebraPrivateSnapshot(Protected):
    transport: Literal["mock"]
    binding_sha256: Digest
    request_sha256: Digest
    items: tuple[TebraPrivateItem, ...] = Field(max_length=25)
    provider_sources: tuple[Digest, ...] = Field(min_length=1, max_length=2)


class SnapshotPayload(Protected):
    public: WindowObservation | VerifiedObservation | ProblemsObservation | TebraWindowObservation | TebraVerifiedObservation
    private: ProblemsPrivateSnapshot | PrivateSnapshot | TebraPrivateSnapshot

    @model_validator(mode="before")
    @classmethod
    def private_provider(cls, value):
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("kind") == "verified_problems":
            return {**value, "private": ProblemsPrivateSnapshot.model_validate(value["private"])}
        if isinstance(value, dict) and isinstance(value.get("public"), dict) and value["public"].get("provider") == "tebra":
            return {**value, "private": TebraPrivateSnapshot.model_validate(value["private"])}
        return value

    @model_validator(mode="after")
    def same_provider(self):
        if isinstance(self.public, ProblemsObservation) != isinstance(self.private, ProblemsPrivateSnapshot):
            raise ValueError("problem_payload_mismatch")
        if (self.public.provider == "tebra") != isinstance(self.private, TebraPrivateSnapshot):
            raise ValueError("provider_payload_mismatch")
        return self
