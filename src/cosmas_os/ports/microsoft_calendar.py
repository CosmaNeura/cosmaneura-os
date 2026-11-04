"""Closed Graph calendar summaries; all-day flags retain explicit UTC instants."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AccountId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_+=/-]{1,2048}$")]
PlainLabel = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]*$")]
_INSTANT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)")


class ClosedCalendarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("microsoft_calendar_time_invalid")
    return value


class MicrosoftCalendarBinding(ClosedCalendarModel):
    account_id: AccountId
    binding_digest: Digest
    connected_at: datetime
    grant_sha256: Digest

    @model_validator(mode="after")
    def aware_connection(self):
        aware(self.connected_at)
        return self


class MicrosoftCalendarWindow(ClosedCalendarModel):
    """The exact UTC startDateTime/endDateTime query, not a rolling view."""

    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def exact_seven_days(self):
        if (aware(self.starts_at).utcoffset() != timedelta(0)
                or aware(self.ends_at).utcoffset() != timedelta(0)
                or self.ends_at - self.starts_at != timedelta(days=7)):
            raise ValueError("microsoft_calendar_window_invalid")
        return self


class MicrosoftCalendarEvent(ClosedCalendarModel):
    id: EventId
    subject: PlainLabel = Field(max_length=998)
    starts_at: str
    ends_at: str
    all_day: bool
    # False means only "not marked cancelled", never confirmed or available.
    cancelled: bool

    def bounds(self) -> tuple[datetime, datetime]:
        if any(_INSTANT.fullmatch(raw) is None for raw in (self.starts_at, self.ends_at)):
            raise ValueError("microsoft_calendar_event_invalid")
        return (datetime.fromisoformat(self.starts_at).astimezone(UTC),
                datetime.fromisoformat(self.ends_at).astimezone(UTC))

    @model_validator(mode="after")
    def positive_exclusive_interval(self):
        starts_at, ends_at = self.bounds()
        if ends_at <= starts_at:
            raise ValueError("microsoft_calendar_event_invalid")
        return self


class MicrosoftCalendarAccount(ClosedCalendarModel):
    label: PlainLabel = Field(min_length=1, max_length=256)
    email: PlainLabel = Field(min_length=1, max_length=320)


class MicrosoftCalendarObservation(ClosedCalendarModel):
    """Frozen bounded result; even all-day events keep the Graph UTC instants."""

    kind: Literal["calendar"]
    account: MicrosoftCalendarAccount
    items: tuple[MicrosoftCalendarEvent, ...] = Field(max_length=25)
    more: bool
    observed_at: datetime
    window: MicrosoftCalendarWindow

    @model_validator(mode="after")
    def bounded_observation(self):
        if (not self.window.starts_at <= aware(self.observed_at) < self.window.ends_at
                or len({event.id for event in self.items}) != len(self.items)):
            raise ValueError("microsoft_calendar_observation_invalid")
        for event in self.items:
            starts_at, ends_at = event.bounds()
            if ends_at <= self.window.starts_at or starts_at >= self.window.ends_at:
                raise ValueError("microsoft_calendar_event_outside_window")
        return self


class MicrosoftCalendarRead(ClosedCalendarModel):
    observation: MicrosoftCalendarObservation
    custody: MicrosoftCalendarBinding
