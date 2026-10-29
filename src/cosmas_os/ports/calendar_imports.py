"""Closed retained calendar-file projections, independent of provider identity."""

import re
import unicodedata
from datetime import UTC, date, datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cosmas_os.adapters.calendar_file_import import CalendarImportWindow

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ReportedSource = Literal["atlas_md", "other_calendar"]
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_ENCODED = re.compile(r"%[0-9a-fA-F]{2}|&[^\s;]+;")
_URI = re.compile(r"(?:[a-z][a-z0-9+.-]*:(?=\S)|[a-z][a-z0-9+.-]*\s*:\s*//|//|\\\\|\bwww\.)", re.I)


class Protected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def __repr__(self):
        return f"{type(self).__name__}(<protected>)"

    __str__ = __repr__


class Window(Protected):
    starts_on: str = Field(strict=True)
    ends_on: str = Field(strict=True)
    timezone: str = Field(strict=True, min_length=1, max_length=128)

    def parser_window(self) -> CalendarImportWindow:
        return CalendarImportWindow(date.fromisoformat(self.starts_on), date.fromisoformat(self.ends_on), self.timezone)

    @model_validator(mode="after")
    def valid_window(self):
        if not _DATE.fullmatch(self.starts_on) or not _DATE.fullmatch(self.ends_on):
            raise ValueError("calendar_window_invalid")
        self.parser_window()
        return self


class Item(Protected):
    item_index: int = Field(strict=True, ge=0, lt=500)
    title: str = Field(strict=True, max_length=300)
    title_truncated: bool = Field(strict=True)
    starts_at: str = Field(strict=True, max_length=20)
    ends_at: str = Field(strict=True, max_length=20)
    all_day: bool = Field(strict=True)
    cancelled: bool = Field(strict=True)

    @field_validator("title")
    @classmethod
    def retained_title(cls, value):
        # The SQL ledger enforces this same conservative retained-text subset.
        # Full source title URI checks happened before any parser truncation.
        normalized = unicodedata.normalize("NFKC", value)
        if (any(unicodedata.category(char).startswith("C") for char in value + normalized)
                or _ENCODED.search(normalized) or _URI.search(normalized)):
            raise ValueError("calendar_event_invalid")
        return value

    def bounds(self) -> tuple[date, date] | tuple[datetime, datetime]:
        if self.all_day:
            return date.fromisoformat(self.starts_at), date.fromisoformat(self.ends_at)
        return datetime.fromisoformat(self.starts_at), datetime.fromisoformat(self.ends_at)

    @model_validator(mode="after")
    def valid_bounds(self):
        pattern = _DATE if self.all_day else _STAMP
        if not pattern.fullmatch(self.starts_at) or not pattern.fullmatch(self.ends_at):
            raise ValueError("calendar_event_invalid")
        start, end = self.bounds()
        if not 1900 <= start.year <= end.year <= 2100 or end <= start:
            raise ValueError("calendar_event_invalid")
        if self.title_truncated and len(self.title) != 300:
            raise ValueError("calendar_event_invalid")
        return self


class SnapshotPayload(Protected):
    imported_at: str = Field(strict=True, max_length=20)
    reported_source: ReportedSource
    window: Window
    items: tuple[Item, ...] = Field(max_length=25)
    total_events: int = Field(strict=True, ge=0, le=500)
    matching_events: int = Field(strict=True, ge=0, le=500)
    more: bool = Field(strict=True)
    coverage: Literal["file_window_only"]

    @model_validator(mode="after")
    def bounded(self):
        if not _STAMP.fullmatch(self.imported_at):
            raise ValueError("calendar_import_invalid")
        datetime.fromisoformat(self.imported_at)
        if (self.matching_events > self.total_events
                or len(self.items) != min(self.matching_events, 25)
                or self.more != (self.matching_events > 25)
                or len({item.item_index for item in self.items}) != len(self.items)):
            raise ValueError("calendar_import_invalid")
        window = self.window.parser_window()
        start, end = window.bounds()
        keys = []
        for item in self.items:
            if item.item_index >= self.total_events:
                raise ValueError("calendar_import_invalid")
            a, b = item.bounds()
            if isinstance(a, datetime) and isinstance(b, datetime):
                valid = a < end and b > start
                order = a
            else:
                valid = a < window.ends_on and b > window.starts_on
                order = datetime.combine(a, time(), ZoneInfo.no_cache(window.timezone)).astimezone(UTC)
            if not valid:
                raise ValueError("calendar_import_invalid")
            keys.append((order, item.item_index))
        if keys != sorted(keys):
            raise ValueError("calendar_import_invalid")
        return self
