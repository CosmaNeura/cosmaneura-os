"""Read-only schedule observations, never EHR or Core record write authority."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cosmas_os.ports.core_encounters import (
    ActorRef,
    Closed,
    ConnectionSnapshot,
    Digest,
    Label,
    TenantRef,
    digest,
)

VendorID = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,17}$")]

PAGE_SIZE = 25
MAX_RESPONSE_BYTES = 65_536


class AthenaScheduleRequest(Closed):
    action: Literal["connection", "appointments"]
    request_nonce: UUID
    expected_tenant_ref: TenantRef
    expected_actor_ref: ActorRef
    connection_sha256: Digest
    start_date: date | None = None
    end_date: date | None = None
    offset: int = Field(default=0, ge=0, le=10_000, strict=True)
    account_sha256: Digest | None = None

    @model_validator(mode="after")
    def bounded_window(self):
        if self.action == "connection":
            if (
                any(
                    v is not None
                    for v in (self.start_date, self.end_date, self.account_sha256)
                )
                or self.offset
            ):
                raise ValueError("invalid_athena_connection_request")
        elif (
            self.start_date is None
            or self.end_date is None
            or self.account_sha256 is None
            or not 0 <= (self.end_date - self.start_date).days < 31
        ):
            raise ValueError("invalid_athena_appointment_window")
        return self


class AthenaScheduleAccount(Closed):
    account_ref: UUID
    account_sha256: Digest
    department_label: Label
    department_timezone: str
    environment: Literal["preview", "production"]
    # Configuration readiness is intentionally distinct from a successful read.
    state: Literal["practice_enabled"] = "practice_enabled"
    access: Literal["appointments_read_only"] = "appointments_read_only"


class AthenaAppointment(Closed):
    appointment_ref: VendorID = Field(repr=False)
    patient_ref: VendorID = Field(repr=False)
    source_local_start: datetime
    department_timezone: str
    duration_minutes: int = Field(ge=1, le=1440, strict=True)
    source_status: Literal["f", "2", "3", "4", "x"]
    source_sha256: Digest

    @model_validator(mode="after")
    def local_time_only(self):
        if self.source_local_start.utcoffset() is not None:
            raise ValueError("athena_source_time_is_department_local")
        return self


class AthenaScheduleResponse(Closed):
    action: Literal["connection", "appointments"]
    request_nonce: UUID
    checked_at: AwareDatetime
    connection: ConnectionSnapshot
    account: AthenaScheduleAccount | None
    appointments: tuple[AthenaAppointment, ...] = Field(
        default=(), max_length=PAGE_SIZE
    )
    total_count: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    next_offset: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    complete: bool = Field(default=False, strict=True)
    truncated: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def consistent_projection(self):
        from zoneinfo import ZoneInfo

        if self.account is not None:
            ZoneInfo(self.account.department_timezone)
        if self.action == "connection":
            if self.appointments or self.total_count is not None or self.next_offset is not None or self.complete or self.truncated:
                raise ValueError("invalid_athena_connection_response")
        else:
            if self.account is None or self.total_count is None:
                raise ValueError("invalid_athena_appointment_response")
            if len({row.appointment_ref for row in self.appointments}) != len(self.appointments):
                raise ValueError("duplicate_athena_appointment")
            for row in self.appointments:
                content = row.model_dump(mode="json", exclude={"source_sha256"})
                if row.department_timezone != self.account.department_timezone or row.source_sha256 != digest({"account_sha256": self.account.account_sha256, **content}):
                    raise ValueError("invalid_athena_appointment_digest")
        return self


class AthenaCommand(Closed):
    """The renderer supplies a reviewed digest, never Core/vendor identities."""

    action: Literal["athena_connection", "athena_appointments"]
    request_nonce: UUID
    connection_sha256: Digest
    account_sha256: Digest | None = None
    start_date: date | None = None
    end_date: date | None = None
    offset: int | None = Field(default=None, ge=0, le=10_000, strict=True)

    @model_validator(mode="after")
    def exact_action(self):
        values = (self.account_sha256, self.start_date, self.end_date, self.offset)
        if self.action == "athena_connection":
            if any(v is not None for v in values):
                raise ValueError("invalid_athena_connection_command")
        elif (self.account_sha256 is None or self.offset is None
              or self.start_date is None or self.end_date is None
              or not 0 <= (self.end_date - self.start_date).days < 31):
            raise ValueError("invalid_athena_appointment_command")
        return self
