"""Closed primary-calendar summaries; date-only events have no inferred timezone."""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AccountId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,1024}$")]
PlainLabel = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]*$")]
_INSTANT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)")


class ClosedCalendarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("google_calendar_time_invalid")
    return value


class GoogleCalendarBinding(ClosedCalendarModel):
    account_id: AccountId
    binding_digest: Digest
    connected_at: datetime
    grant_sha256: Digest

    @model_validator(mode="after")
    def aware_connection(self):
        aware(self.connected_at)
        return self


class GoogleCalendarWindow(ClosedCalendarModel):
    """The exact UTC instants sent as timeMin/timeMax, not a rolling view."""

    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def exact_seven_days(self):
        if (aware(self.starts_at).utcoffset() != timedelta(0)
                or aware(self.ends_at).utcoffset() != timedelta(0)
                or self.ends_at - self.starts_at != timedelta(days=7)):
            raise ValueError("google_calendar_window_invalid")
        return self


class GoogleCalendarEvent(ClosedCalendarModel):
    id: EventId
    subject: PlainLabel = Field(max_length=998)
    starts_at: str
    ends_at: str
    all_day: bool
    # False means only "not marked cancelled", never confirmed or available.
    cancelled: bool

    def bounds(self) -> tuple[date, date] | tuple[datetime, datetime]:
        if self.all_day:
            values = (date.fromisoformat(self.starts_at), date.fromisoformat(self.ends_at))
            if any(value.isoformat() != raw for value, raw in zip(values, (self.starts_at, self.ends_at), strict=True)):
                raise ValueError("google_calendar_event_invalid")
            return values
        if any(_INSTANT.fullmatch(raw) is None for raw in (self.starts_at, self.ends_at)):
            raise ValueError("google_calendar_event_invalid")
        return (datetime.fromisoformat(self.starts_at).astimezone(UTC),
                datetime.fromisoformat(self.ends_at).astimezone(UTC))

    @model_validator(mode="after")
    def positive_exclusive_interval(self):
        starts_at, ends_at = self.bounds()
        if ends_at <= starts_at:
            raise ValueError("google_calendar_event_invalid")
        return self


class GoogleCalendarAccount(ClosedCalendarModel):
    label: PlainLabel = Field(min_length=1, max_length=256)
    email: PlainLabel = Field(min_length=1, max_length=320)


class GoogleCalendarObservation(ClosedCalendarModel):
    """Frozen bounded result; all-day bounds remain calendar dates, not UTC."""

    kind: Literal["calendar"]
    account: GoogleCalendarAccount
    items: tuple[GoogleCalendarEvent, ...] = Field(max_length=25)
    more: bool
    observed_at: datetime
    window: GoogleCalendarWindow

    @model_validator(mode="after")
    def bounded_observation(self):
        if (not self.window.starts_at <= aware(self.observed_at) < self.window.ends_at
                or len({event.id for event in self.items}) != len(self.items)):
            raise ValueError("google_calendar_observation_invalid")
        for event in self.items:
            if not event.all_day:
                starts_at, ends_at = event.bounds()
                if not isinstance(starts_at, datetime) or not isinstance(ends_at, datetime):
                    raise ValueError("google_calendar_event_invalid")
                if ends_at <= self.window.starts_at or starts_at >= self.window.ends_at:
                    raise ValueError("google_calendar_event_outside_window")
        return self


class GoogleCalendarRead(ClosedCalendarModel):
    observation: GoogleCalendarObservation
    custody: GoogleCalendarBinding
