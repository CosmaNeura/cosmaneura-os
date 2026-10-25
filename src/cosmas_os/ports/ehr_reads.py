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


class SnapshotPayload(Protected):
    public: Annotated[WindowObservation | VerifiedObservation, Field(discriminator="kind")]
    private: PrivateSnapshot
