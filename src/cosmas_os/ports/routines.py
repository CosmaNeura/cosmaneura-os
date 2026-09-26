"""Bounded local work briefs: civil-time schedules, never external authority."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from cosmas_os.ports.scribe_capture import ProtectedModel

ClockTime = Annotated[str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]


class BriefSchedule(ProtectedModel):
    kind: Literal["practice_work_brief"] = "practice_work_brief"
    enabled: bool = Field(strict=True)
    timezone: str = Field(min_length=1, max_length=80)
    at: ClockTime
    weekdays: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(min_length=1, max_length=7)
    quiet_start: ClockTime | None = None
    quiet_end: ClockTime | None = None
    max_runs_per_seven_days: int = Field(default=5, strict=True, ge=1, le=7)

    @model_validator(mode="after")
    def valid_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose an IANA time zone") from None
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Choose distinct weekdays")
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("Quiet hours need a start and end")
        if self.quiet_start is not None and self.quiet_start == self.quiet_end:
            raise ValueError("Pause the routine instead of setting all-day quiet hours")
        if self.is_quiet(self.at):
            raise ValueError("Choose a scheduled time outside quiet hours")
        return self

    def is_quiet(self, clock: str) -> bool:
        start, end = self.quiet_start, self.quiet_end
        if start is None or end is None:
            return False
        return start <= clock < end if start < end else clock >= start or clock < end

    def occurrence(self, day: date) -> datetime | None:
        if day.isoweekday() not in self.weekdays:
            return None
        naive = datetime.combine(day, time.fromisoformat(self.at))
        zone = ZoneInfo(self.timezone)
        # A repeated civil time means its first occurrence only. A missing
        # spring-forward time is skipped rather than silently moved.
        utc = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != naive:
            return None
        return utc

    def due(self, now: datetime, activated_at: datetime) -> tuple[str, datetime | None]:
        if now.tzinfo is None or activated_at.tzinfo is None:
            raise ValueError("An aware clock is required")
        if not self.enabled:
            return "paused", None
        local = now.astimezone(ZoneInfo(self.timezone))
        occurrence = self.occurrence(local.date())
        if occurrence is None or occurrence < activated_at or now < occurrence:
            return "waiting", occurrence
        # Restart catch-up is bounded and never replays a previous local day.
        if now - occurrence > timedelta(hours=6):
            return "missed", occurrence
        if self.is_quiet(local.strftime("%H:%M")):
            return "quiet_hours", occurrence
        return "due", occurrence

    def next_occurrence(self, now: datetime) -> datetime | None:
        day = now.astimezone(ZoneInfo(self.timezone)).date()
        for offset in range(15):
            occurrence = self.occurrence(day + timedelta(days=offset))
            if occurrence is not None and occurrence > now:
                return occurrence
        return None
