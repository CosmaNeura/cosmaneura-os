"""Exact appointment actions for the proposed Scheduling v1 operation receiver.

These values are not grants. The application must resolve current patient/staff
correspondence and verify the immutable F-8 decision before submitting an
operation. Scheduling still owns its calendar, appointment lifecycle and
conflict checks. The receiver extension is not yet implemented or activated.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    AvailabilitySlot,
    GoogleCalendarCoverage,
    SchedulingSelection,
)
from cosmas_os.ports.scribe_capture import ProtectedModel

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
AppointmentStatus = Literal["booked", "confirmed", "arrived", "fulfilled", "cancelled", "no_show"]
AppointmentAction = Literal["book", "reschedule", "cancel"]


class AppointmentSelection(SchedulingSelection):
    """Reviewed patient mapping in addition to the W11 staff correspondence."""

    patient_link_id: UUID
    patient_id: UUID

    @model_validator(mode="after")
    def reviewed_staff_actor(self):
        if self.expected_actor_id is None:
            raise ValueError("Appointment actions require a reviewed staff actor")
        return self


class AppointmentSnapshot(ProtectedModel):
    id: UUID
    # Receiver-owned monotonic revision, advanced by EVERY appointment mutation.
    # A hash of visible fields alone cannot detect a changed-then-restored record.
    version: int = Field(strict=True, ge=1, le=9_223_372_036_854_775_807)
    practitioner_id: UUID
    location_id: UUID
    appointment_type_id: UUID
    patient_id: UUID
    client_id: UUID | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: AppointmentStatus

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def utc_time(cls, value) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Appointment times require an explicit UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def positive_duration(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Appointment duration must be positive")
        return self

    def matches(self, selection: AppointmentSelection) -> bool:
        return all(getattr(self, name) == getattr(selection, name) for name in (
            "practitioner_id", "location_id", "appointment_type_id", "patient_id",
        ))


class ObservedAppointment(ProtectedModel):
    selection: AppointmentSelection
    appointment: AppointmentSnapshot
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def same_subject(self):
        if not self.appointment.matches(self.selection):
            raise ValueError("Appointment correspondence differs")
        return self


class AppointmentIntent(ProtectedModel):
    action: AppointmentAction
    selection: AppointmentSelection
    expected: AppointmentSnapshot | None = None
    slot: AvailabilitySlot | None = None
    google: GoogleCalendarCoverage | None = None
    expires_at: AwareDatetime

    @field_validator("expires_at", mode="before")
    @classmethod
    def utc_time(cls, value) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Appointment expiry requires an explicit UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def exact_action(self):
        if self.action == "book":
            if self.expected is not None:
                raise ValueError("Booking cannot select an existing appointment")
        elif (self.expected is None or not self.expected.matches(self.selection)
              or self.expected.status not in {"booked", "confirmed"}):
            raise ValueError("A current, matching active appointment is required")
        if self.action == "cancel":
            if self.slot is not None or self.google is not None:
                raise ValueError("Cancellation cannot select a replacement slot")
        else:
            if self.slot is None or self.google is None:
                raise ValueError("An exact slot and Google coverage are required")
            if (self.google.connected_at > self.google.checked_at
                or not self.google.checked_at < self.expires_at <= self.google.checked_at + timedelta(minutes=5)
                or self.slot.starts_at <= self.expires_at):
                raise ValueError("Booking authority requires bounded, current coverage")
            if self.expected and (self.slot.starts_at, self.slot.ends_at) == (
                self.expected.starts_at, self.expected.ends_at,
            ):
                raise ValueError("Rescheduling requires a different slot")
        return self

    def approval_hash(self) -> str:
        """Includes OS owner/patient mapping; an altered proposal needs review."""
        return payload_hash(self.model_dump(mode="json"))

    def receiver_payload(self) -> dict:
        """No Box, OS owner, or local patient-link identifiers leave this port."""
        return {
            "contract_version": "1", "action": self.action,
            "expected_actor_id": str(self.selection.expected_actor_id),
            "practitioner_id": str(self.selection.practitioner_id),
            "location_id": str(self.selection.location_id),
            "appointment_type_id": str(self.selection.appointment_type_id),
            "patient_id": str(self.selection.patient_id),
            "expected": self.expected.model_dump(mode="json") if self.expected else None,
            "slot": self.slot.model_dump(mode="json") if self.slot else None,
            "google": self.google.model_dump(mode="json") if self.google else None,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
        }


class AppointmentOperation(ProtectedModel):
    """Persisted F-8 operation identity, after application-level authorization.

    Matching a supplied hash is integrity checking, not proof of human approval.
    The application must check its actual Decision/AuditEvent records separately.
    """

    operation_id: UUID
    intent: AppointmentIntent
    approved_payload_hash: Digest

    @model_validator(mode="after")
    def unchanged_intent(self):
        if self.approved_payload_hash != self.intent.approval_hash():
            raise ValueError("Appointment approval changed")
        return self

    def request_payload(self) -> dict:
        return {"operation_id": str(self.operation_id), **self.intent.receiver_payload()}

    def request_hash(self) -> str:
        # Scope the receiver journal to the actual practice, never the OS Box.
        return payload_hash({"practice_id": str(self.intent.selection.practice_id),
                             "request": self.request_payload()})


class AppointmentResult(ProtectedModel):
    operation_id: UUID
    request_hash: Digest
    appointment: AppointmentSnapshot
    observed_at: AwareDatetime
    # Appointment persistence and calendar synchronization are different outcomes.
    calendar_state: Literal["pending", "synced", "failed", "disconnected"]

    def require_operation(self, operation: AppointmentOperation) -> None:
        intent = operation.intent
        actual = self.appointment
        if (self.operation_id != operation.operation_id or self.request_hash != operation.request_hash()
            or not actual.matches(intent.selection)):
            raise ValueError("Appointment operation receipt differs")
        before = intent.expected
        if intent.action == "book":
            if actual.status != "booked" or actual.version != 1 or actual.client_id is not None:
                raise ValueError("Booking receipt differs")
        elif before is None or (actual.id, actual.version, actual.client_id) != (
            before.id, before.version + 1, before.client_id,
        ):
            raise ValueError("Appointment revision differs")
        if intent.action == "cancel":
            assert before is not None
            if actual.status != "cancelled" or (actual.starts_at, actual.ends_at) != (
                before.starts_at, before.ends_at,
            ):
                raise ValueError("Cancellation receipt differs")
        else:
            assert intent.slot is not None
            if (actual.starts_at, actual.ends_at) != (intent.slot.starts_at, intent.slot.ends_at):
                raise ValueError("Appointment slot differs")
            if before is not None and actual.status != before.status:
                raise ValueError("Rescheduling changed appointment status")


class SchedulingAppointmentsPort(Protocol):
    def read_appointment(self, selection: AppointmentSelection, appointment_id: UUID) -> ObservedAppointment: ...
    def submit(self, operation: AppointmentOperation) -> AppointmentResult: ...
    def reconcile(self, operation: AppointmentOperation) -> AppointmentResult: ...


class UnconnectedAppointments:
    def read_appointment(self, selection, appointment_id):
        raise ConnectorUnavailable("scheduling_connection_unavailable")

    def submit(self, operation):
        raise ConnectorUnavailable("scheduling_connection_unavailable")

    def reconcile(self, operation):
        raise ConnectorUnavailable("scheduling_connection_unavailable")


def build_scheduling_appointments() -> SchedulingAppointmentsPort:
    return UnconnectedAppointments()
