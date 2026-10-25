"""Bounded, local calendar-file projection; no provider or patient identity claims.

The caller owns authorization, encrypted custody, import time, and review lifecycle.
This module neither stores raw bytes nor logs them. Errors have closed codes only;
callers must not log arguments, locals, or an exception traceback containing input.
The optional ``calendar-import`` extra supplies the pinned BSD-licensed tokenizer.
We deliberately avoid Calendar.from_ical: it caches file-provided timezone names.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING, Literal, NoReturn
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from icalendar.parser.parameter import Parameters

MAX_BYTES = 1024 * 1024
MAX_EVENTS = 500
MAX_ITEMS = 25
MAX_TITLE = 300
MAX_LINE = 16 * 1024
MAX_LINES = 20_000
MAX_TIMEZONES = 8
MAX_OBSERVANCES = 8
MAX_COMPONENTS = 1100
_DATE = re.compile(r"[0-9]{8}")
_DATETIME = re.compile(r"[0-9]{8}T[0-9]{6}Z?")
_OFFSET = re.compile(r"([+-])([0-9]{2})([0-9]{2})")
_ZONE = re.compile(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*")
_URI = re.compile(r"(?:[a-z][a-z0-9+.-]*:(?=\S)|[a-z][a-z0-9+.-]*\s*:\s*//|//|\\\\|\bwww\.)", re.I)
_RECURRENCE = frozenset({"RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID"})

ErrorCode = Literal[
    "calendar_file_too_large", "calendar_file_invalid", "calendar_window_invalid",
    "calendar_event_limit", "calendar_structure_limit", "calendar_duplicate_uid",
    "calendar_recurrence_unsupported", "calendar_floating_time", "calendar_timezone_invalid",
    "calendar_timezone_conflict", "calendar_uri_in_title", "calendar_event_invalid",
    "calendar_parser_unavailable",
]


class CalendarFileImportError(ValueError):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)


def _fail(code: ErrorCode) -> NoReturn:
    raise CalendarFileImportError(code)


def _zone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or len(name) > 128 or not _ZONE.fullmatch(name):
        _fail("calendar_timezone_invalid")
    try:
        # Do not retain an untrusted file's identifiers in ZoneInfo's global cache.
        return ZoneInfo.no_cache(name)
    except (ValueError, ZoneInfoNotFoundError):
        _fail("calendar_timezone_invalid")


@dataclass(frozen=True)
class CalendarImportWindow:
    """Seven local calendar dates, including 167/169-hour DST weeks."""

    starts_on: date
    ends_on: date
    timezone: str

    def __post_init__(self) -> None:
        if (type(self.starts_on) is not date or type(self.ends_on) is not date
                or self.ends_on - self.starts_on != timedelta(days=7)
                or not 1900 <= self.starts_on.year <= self.ends_on.year <= 2100):
            _fail("calendar_window_invalid")
        try:
            zone = _zone(self.timezone)
            for day in (self.starts_on, self.ends_on):
                _local(datetime.combine(day, time()), zone)
        except CalendarFileImportError:
            _fail("calendar_window_invalid")

    def bounds(self) -> tuple[datetime, datetime]:
        zone = _zone(self.timezone)
        return (datetime.combine(self.starts_on, time(), zone).astimezone(UTC),
                datetime.combine(self.ends_on, time(), zone).astimezone(UTC))


@dataclass(frozen=True, repr=False)
class CalendarImportItem:
    """item_index is only an ordinal within this exact file, never a vendor ID."""

    item_index: int
    title: str
    title_truncated: bool
    starts_at: str
    ends_at: str
    all_day: bool
    cancelled: bool  # False means only not marked CANCELLED, never verified/available.


@dataclass(frozen=True, repr=False)
class CalendarImportResult:
    byte_sha256: str  # Protected custody commitment; do not put in ordinary logs.
    window: CalendarImportWindow
    items: tuple[CalendarImportItem, ...]
    total_events: int
    matching_events: int
    more: bool
    coverage: Literal["file_window_only"] = "file_window_only"


@dataclass(repr=False)
class _Property:
    params: Parameters
    value: str


@dataclass(repr=False)
class _Component:
    name: str
    props: dict[str, list[_Property]] = field(default_factory=dict)
    children: list[_Component] = field(default_factory=list)

    def one(self, name: str, *, required: bool = False) -> _Property | None:
        values = self.props.get(name, [])
        if len(values) > 1 or (required and not values):
            _fail("calendar_file_invalid")
        return values[0] if values else None


def _envelope(raw: bytes) -> _Component:
    from icalendar.parser.content_line import Contentline
    from icalendar.parser.parameter import q_split

    # Bound before tokenizer/component construction. Folded lines have their own cap.
    if re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", raw):
        _fail("calendar_file_invalid")
    physical = raw.replace(b"\r\n", b"\n").split(b"\n")
    if len(physical) > MAX_LINES or b"\r" in raw.replace(b"\r\n", b""):
        _fail("calendar_structure_limit")
    lines: list[bytes] = []
    for line in physical:
        if line.startswith((b" ", b"\t")):
            if not lines:
                _fail("calendar_file_invalid")
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
        if lines and len(lines[-1]) > MAX_LINE:
            _fail("calendar_structure_limit")
    root: _Component | None = None
    stack: list[_Component] = []
    event_count = zone_count = component_count = 0
    for raw_line in lines:
        # RFC 5545 folding can bisect a UTF-8 sequence: unfold bytes first.
        line = raw_line.decode("utf-8", "strict")
        content_line = Contentline(line)
        name, params, value = content_line.parts()
        # The library preserves case-sensitive TZIDs in its normal mode, but its
        # parameter mapping overwrites duplicate keys. Reject those before use.
        header = line[:content_line.value_separator_index()]
        keys = [part.split("=", 1)[0].upper() for part in q_split(header, ";")[1:]]
        if len(keys) != len(set(keys)):
            _fail("calendar_file_invalid")
        name = name.upper()
        if name == "BEGIN":
            component_count += 1
            if component_count > MAX_COMPONENTS:
                _fail("calendar_structure_limit")
            if params:
                _fail("calendar_file_invalid")
            kind = value.upper()
            parent = stack[-1].name if stack else None
            allowed = {None: {"VCALENDAR"}, "VCALENDAR": {"VEVENT", "VTIMEZONE"},
                       "VEVENT": {"VALARM"}, "VTIMEZONE": {"STANDARD", "DAYLIGHT"}}
            if kind not in allowed.get(parent, set()) or len(stack) >= 3:
                _fail("calendar_file_invalid")
            if kind == "VCALENDAR" and root is not None:
                _fail("calendar_file_invalid")
            event_count += kind == "VEVENT"
            zone_count += kind == "VTIMEZONE"
            if event_count > MAX_EVENTS:
                _fail("calendar_event_limit")
            if zone_count > MAX_TIMEZONES:
                _fail("calendar_structure_limit")
            component = _Component(kind)
            if stack:
                stack[-1].children.append(component)
                if parent == "VTIMEZONE" and len(stack[-1].children) > MAX_OBSERVANCES:
                    _fail("calendar_structure_limit")
            else:
                root = component
            stack.append(component)
        elif name == "END":
            if params or not stack or stack[-1].name != value.upper():
                _fail("calendar_file_invalid")
            stack.pop()
        else:
            if not stack:
                _fail("calendar_file_invalid")
            stack[-1].props.setdefault(name, []).append(_Property(params, value))
    if stack or root is None:
        _fail("calendar_file_invalid")
    version = root.one("VERSION", required=True)
    method = root.one("METHOD")
    if (version is None or version.params or version.value != "2.0"
            or method is not None and (method.params or method.value.upper() != "PUBLISH")):
        _fail("calendar_file_invalid")
    return root


def _naive(value: str) -> datetime:
    if not _DATETIME.fullmatch(value) or value.endswith("Z"):
        _fail("calendar_event_invalid")
    result = datetime.strptime(value, "%Y%m%dT%H%M%S")
    if not 1900 <= result.year <= 2100:
        _fail("calendar_event_invalid")
    return result


def _local(value: datetime, zone: tzinfo) -> datetime:
    first, second = value.replace(tzinfo=zone, fold=0), value.replace(tzinfo=zone, fold=1)
    # Do not choose one occurrence silently or invent a missing wall-clock time.
    if (first.utcoffset() != second.utcoffset()
            or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value):
        _fail("calendar_timezone_conflict")
    return first.astimezone(UTC)


def _offset(value: str) -> timedelta:
    match = _OFFSET.fullmatch(value)
    if match is None or value == "-0000" or int(match[2]) > 23 or int(match[3]) > 59:
        _fail("calendar_timezone_invalid")
    return timedelta(minutes=(1 if match[1] == "+" else -1)
                     * (60 * int(match[2]) + int(match[3])))


def _timezones(root: _Component, window: CalendarImportWindow) -> dict[str, tzinfo]:
    from dateutil.rrule import rrulestr
    from icalendar import Timezone, TimezoneDaylight, TimezoneStandard
    from icalendar.prop import vRecur
    from icalendar.timezone import TZP

    result: dict[str, tzinfo] = {}
    for source in root.children:
        if source.name != "VTIMEZONE":
            continue
        name = source.one("TZID", required=True)
        if name is None or name.params:
            _fail("calendar_timezone_invalid")
        trusted = _zone(name.value)
        if name.value in result or not source.children:
            _fail("calendar_timezone_conflict")
        zone = Timezone()
        zone.add("TZID", name.value)
        start, end = window.bounds()
        transitions: list[datetime] = []
        for child in source.children:
            part = TimezoneStandard() if child.name == "STANDARD" else TimezoneDaylight()
            for key in ("DTSTART", "TZOFFSETFROM", "TZOFFSETTO"):
                prop = child.one(key, required=True)
                if prop is None or prop.params:
                    _fail("calendar_timezone_invalid")
                part.add(key, _naive(prop.value) if key == "DTSTART" else _offset(prop.value))
            first = child.one("DTSTART", required=True)
            offset = child.one("TZOFFSETFROM", required=True)
            if first is None or offset is None:
                _fail("calendar_timezone_invalid")
            rule_start = _naive(first.value).replace(tzinfo=timezone(_offset(offset.value)))
            transitions.append(rule_start.astimezone(UTC))
            if set(child.props) - {"DTSTART", "TZOFFSETFROM", "TZOFFSETTO", "RRULE", "RDATE", "TZNAME", "COMMENT"}:
                _fail("calendar_timezone_invalid")
            rule, rdates = child.one("RRULE"), child.one("RDATE")
            if rule is not None and rdates is not None:
                _fail("calendar_timezone_invalid")
            if rule is not None:
                # At most one transition per year per observance. No SECONDLY,
                # COUNT explosions, Cartesian BY* products, or unlimited expansion.
                if rule.params or len(rule.value) > 200:
                    _fail("calendar_timezone_invalid")
                pairs = [piece.split("=", 1) for piece in rule.value.upper().split(";")]
                if any(len(pair) != 2 for pair in pairs) or len({pair[0] for pair in pairs}) != len(pairs):
                    _fail("calendar_timezone_invalid")
                rules = {pair[0]: pair[1] for pair in pairs}
                if (set(rules) - {"FREQ", "BYMONTH", "BYDAY", "BYMONTHDAY", "UNTIL"}
                        or rules.get("FREQ") != "YEARLY"
                        or not re.fullmatch(r"(?:[1-9]|1[0-2])", rules.get("BYMONTH", ""))
                        or ("BYDAY" in rules) == ("BYMONTHDAY" in rules)):
                    _fail("calendar_timezone_invalid")
                if "BYDAY" in rules and not re.fullmatch(r"-?[1-5](?:MO|TU|WE|TH|FR|SA|SU)", rules["BYDAY"]):
                    _fail("calendar_timezone_invalid")
                if "BYMONTHDAY" in rules and not re.fullmatch(r"-?(?:[1-9]|[12][0-9]|3[01])", rules["BYMONTHDAY"]):
                    _fail("calendar_timezone_invalid")
                if "UNTIL" in rules:
                    if not rules["UNTIL"].endswith("Z"):
                        _fail("calendar_timezone_invalid")
                    _naive(rules["UNTIL"][:-1])
                # Even an impossible date (February 31) must not make dateutil
                # search to year 9999 while trying to find its first occurrence.
                # This internal horizon covers every accepted event/window year.
                rules.setdefault("UNTIL", "21001231T235959Z")
                bounded_rule = ";".join(f"{key}={value}" for key, value in rules.items())
                part.add("RRULE", vRecur.from_ical(bounded_rule))
                transitions.extend(rrulestr(bounded_rule, dtstart=rule_start).between(
                    start - timedelta(days=2), end + timedelta(days=2), inc=True))
            if rdates is not None:
                values = rdates.value.split(",")
                if rdates.params or len(values) > 32:
                    _fail("calendar_timezone_invalid")
                part.add("RDATE", [_naive(value) for value in values])
                transitions.extend(_naive(value).replace(tzinfo=rule_start.tzinfo).astimezone(UTC)
                                   for value in values)
            zone.add_component(part)
        # Local provider: no global icalendar timezone cache and no raw file parse.
        declared = zone.to_tz(TZP("zoneinfo"), lookup_tzid=False)
        probes = [start + timedelta(hours=hour)
                  for hour in range(int((end - start).total_seconds() // 3600) + 1)]
        # Check either side of every declared transition, including sub-hour
        # changes that a fixed hourly sample could otherwise miss.
        probes.extend(transition + timedelta(seconds=delta)
                      for transition in transitions if start <= transition <= end
                      for delta in (-1, 0, 1))
        for probe in probes:
            if probe.astimezone(declared).utcoffset() != probe.astimezone(trusted).utcoffset():
                _fail("calendar_timezone_conflict")
        result[name.value] = declared
    return result


def _bounds(prop: _Property, zones: dict[str, tzinfo]) -> date | datetime:
    if set(prop.params) - {"VALUE", "TZID"}:
        _fail("calendar_event_invalid")
    value_type = prop.params.get("VALUE", "DATE-TIME")
    if not isinstance(value_type, str):
        _fail("calendar_event_invalid")
    value_type = value_type.upper()
    tzid = prop.params.get("TZID")
    if value_type == "DATE":
        if tzid is not None or not _DATE.fullmatch(prop.value):
            _fail("calendar_event_invalid")
        day = datetime.strptime(prop.value, "%Y%m%d").date()
        if not 1900 <= day.year <= 2100:
            _fail("calendar_event_invalid")
        return day
    if value_type != "DATE-TIME" or not _DATETIME.fullmatch(prop.value):
        _fail("calendar_event_invalid")
    if prop.value.endswith("Z"):
        if tzid is not None:
            _fail("calendar_timezone_conflict")
        return _naive(prop.value[:-1]).replace(tzinfo=UTC)
    if tzid is None:
        _fail("calendar_floating_time")
    if not isinstance(tzid, str):
        _fail("calendar_timezone_invalid")
    trusted = _zone(tzid)
    if tzid not in zones:
        _fail("calendar_timezone_invalid")
    naive = _naive(prop.value)
    instant = _local(naive, trusted)
    if instant.astimezone(zones[tzid]).replace(tzinfo=None) != naive:
        _fail("calendar_timezone_conflict")
    return instant


def _title(prop: _Property | None) -> tuple[str, bool]:
    if prop is None:
        return "", False
    if set(prop.params) - {"LANGUAGE", "ALTREP"}:
        _fail("calendar_event_invalid")
    text = prop.value
    if any(unicodedata.category(char).startswith("C") and char not in "\n\t" for char in text):
        _fail("calendar_event_invalid")
    # Check the ENTIRE title before truncation, including encoded URI separators.
    decoded = unicodedata.normalize("NFKC", text)
    for _ in range(4):
        next_value = html.unescape(unquote(decoded))
        if next_value == decoded:
            break
        decoded = next_value
    else:
        _fail("calendar_uri_in_title")
    if _URI.search(decoded):
        _fail("calendar_uri_in_title")
    title = " ".join(text.split())
    return title[:MAX_TITLE], len(title) > MAX_TITLE


def _project(raw: bytes, window: CalendarImportWindow) -> CalendarImportResult:
    root = _envelope(raw)
    zones = _timezones(root, window)
    seen: set[str] = set()
    found: list[tuple[datetime, CalendarImportItem]] = []
    total = 0
    start, end = window.bounds()
    for source in root.children:
        if source.name != "VEVENT":
            continue
        index = total
        total += 1
        if _RECURRENCE.intersection(source.props):
            _fail("calendar_recurrence_unsupported")
        uid = source.one("UID", required=True)
        if uid is None or uid.params or not uid.value or len(uid.value) > 1024:
            _fail("calendar_event_invalid")
        uid_text = uid.value
        if uid_text in seen:
            _fail("calendar_duplicate_uid")
        seen.add(uid_text)
        first, last = source.one("DTSTART", required=True), source.one("DTEND", required=True)
        if first is None or last is None or "DURATION" in source.props:
            _fail("calendar_event_invalid")
        a, b = _bounds(first, zones), _bounds(last, zones)
        if type(a) is not type(b) or b <= a:
            _fail("calendar_event_invalid")
        status = source.one("STATUS")
        if status is not None and (status.params or status.value.upper() not in {"TENTATIVE", "CONFIRMED", "CANCELLED"}):
            _fail("calendar_event_invalid")
        title, truncated = _title(source.one("SUMMARY"))
        all_day = type(a) is date
        if isinstance(a, datetime) and isinstance(b, datetime):
            matches = a < end and b > start
            order = a
            first_text, last_text = (value.isoformat().replace("+00:00", "Z") for value in (a, b))
        else:
            matches = a < window.ends_on and b > window.starts_on
            order = datetime.combine(a, time(), _zone(window.timezone)).astimezone(UTC)
            first_text, last_text = a.isoformat(), b.isoformat()
        if matches:
            found.append((order, CalendarImportItem(index, title, truncated, first_text,
                          last_text, all_day, status is not None and status.value.upper() == "CANCELLED")))
    found.sort(key=lambda pair: (pair[0], pair[1].item_index))
    return CalendarImportResult(hashlib.sha256(raw).hexdigest(), window,
                                tuple(item for _, item in found[:MAX_ITEMS]), total,
                                len(found), len(found) > MAX_ITEMS)


def parse_calendar_file(raw: bytes, window: CalendarImportWindow) -> CalendarImportResult:
    """Validate the whole bounded file, then return a minimal, deterministic page.

    Unsupported/broken events outside the chosen window also refuse the import.
    Success means only that this file was parsed; coverage never describes Atlas
    or any live calendar. No clock, filesystem write, network, or process I/O.
    """
    if type(raw) is not bytes or not raw:
        _fail("calendar_file_invalid")
    if len(raw) > MAX_BYTES:
        _fail("calendar_file_too_large")
    if not isinstance(window, CalendarImportWindow):
        _fail("calendar_window_invalid")
    try:
        return _project(raw, window)
    except CalendarFileImportError:
        raise
    except ImportError:
        raise CalendarFileImportError("calendar_parser_unavailable") from None
    except (ValueError, TypeError, KeyError, OverflowError, IndexError):
        raise CalendarFileImportError("calendar_file_invalid") from None
