"""Scheduling read contracts; a selection is never an access grant.

The receiver owns staff membership, slots, booking conflicts and Google access.
OS uses a reviewed private-owner/practice/identity correspondence for its
explicitly injected synthetic workspace connection. The existing slot response does not attest that
Google was consulted and does not reserve an appointment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scribe_capture import ProtectedModel

MAX_AVAILABILITY_SLOTS = 4096


class SchedulingSelection(ProtectedModel):
    """Server-owned correspondence, after current workspace authorization.

    Box and Scheduling practice identifiers are distinct. They must not be
    equated from a browser selector, an email address or a model response.
    """

    box_id: UUID
    owner_id: UUID
    practice_id: UUID
    practitioner_id: UUID
    location_id: UUID
    appointment_type_id: UUID
    expected_actor_id: UUID | None = None


class _UtcRange(ProtectedModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class AvailabilityWindow(_UtcRange):
    @model_validator(mode="after")
    def bounded_window(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=31):
            raise ValueError("Scheduling requires a positive window of at most 31 days")
        return self


class AvailabilitySlot(_UtcRange):
    @model_validator(mode="after")
    def positive_slot(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Scheduling slot must have a positive duration")
        return self


class SchedulingAvailability(ProtectedModel):
    selection: SchedulingSelection
    window: AvailabilityWindow
    slots: tuple[AvailabilitySlot, ...] = Field(max_length=MAX_AVAILABILITY_SLOTS)
    observed_at: AwareDatetime
    google_calendar_coverage: Literal["not_attested"] = "not_attested"
    appointment_reserved: Literal[False] = False

    @model_validator(mode="after")
    def slots_match_window(self):
        identities = {(slot.starts_at, slot.ends_at) for slot in self.slots}
        if len(identities) != len(self.slots) or any(
            not self.window.starts_at <= slot.starts_at < slot.ends_at <= self.window.ends_at
            for slot in self.slots
        ):
            raise ValueError("Scheduling returned inconsistent slots")
        return self


class SchedulingAvailabilityPort(Protocol):
    def availability(
        self, selection: SchedulingSelection, window: AvailabilityWindow,
    ) -> SchedulingAvailability: ...

    def verified_availability(
        self, selection: SchedulingSelection, window: AvailabilityWindow,
    ) -> GoogleSchedulingAvailability: ...


class UnconnectedScheduling:
    def availability(self, selection, window):
        raise ConnectorUnavailable("scheduling_connection_unavailable")

    def verified_availability(self, selection, window):
        raise ConnectorUnavailable("scheduling_connection_unavailable")


def build_scheduling_availability() -> SchedulingAvailabilityPort:
    """No ambient activation; real staff identity acquisition remains unqualified."""
    return UnconnectedScheduling()


class GoogleCalendarCoverage(ProtectedModel):
    provider: Literal["google"]
    calendar_id: Literal["primary"]
    connection_id: UUID
    connected_at: AwareDatetime
    checked_at: AwareDatetime


class GoogleSchedulingAvailability(ProtectedModel):
    selection: SchedulingSelection
    window: AvailabilityWindow
    slots: tuple[AvailabilitySlot, ...] = Field(max_length=MAX_AVAILABILITY_SLOTS)
    observed_at: AwareDatetime
    google: GoogleCalendarCoverage

    @model_validator(mode="after")
    def consistent_read(self):
        SchedulingAvailability(selection=self.selection, window=self.window,
                               slots=self.slots, observed_at=self.observed_at)
        if self.selection.expected_actor_id is None or self.google.connected_at > self.google.checked_at:
            raise ValueError("Invalid verified Scheduling read")
        return self
