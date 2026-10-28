"""Invented calendar bytes only: no Atlas account, feed, patient, or network."""

import builtins
import hashlib
import json
import socket
from dataclasses import asdict
from datetime import date, timedelta
from typing import NoReturn
from urllib.request import OpenerDirector

import pytest
from icalendar.timezone import tzp

from cosmas_os.adapters.calendar_file_import import (
    MAX_BYTES,
    CalendarFileImportError,
    CalendarImportWindow,
    parse_calendar_file,
)

WINDOW = CalendarImportWindow(date(2026, 10, 25), date(2026, 11, 1), "America/New_York")
FALL = CalendarImportWindow(date(2026, 11, 1), date(2026, 11, 8), "America/New_York")
SPRING = CalendarImportWindow(date(2026, 3, 8), date(2026, 3, 15), "America/New_York")


def event(*, uid="invented-1", start="20261025T130000Z", end="20261025T133000Z",
          title="Example appointment", extra="", params="") -> str:
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART{params}:{start}\r\n"
            f"DTEND{params}:{end}\r\nSUMMARY:{title}\r\n{extra}END:VEVENT\r\n")


def calendar(*events: str, extra="") -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:invented\r\n"
            + extra + "".join(events) + "END:VCALENDAR\r\n").encode()


def eastern(*, standard="-0500", daylight="-0400", name="America/New_York",
            daylight_rule="FREQ=YEARLY;BYMONTH=3;BYDAY=2SU") -> str:
    return (f"BEGIN:VTIMEZONE\r\nTZID:{name}\r\n"
            "BEGIN:STANDARD\r\nDTSTART:20071104T020000\r\n"
            f"TZOFFSETFROM:-0400\r\nTZOFFSETTO:{standard}\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\nEND:STANDARD\r\n"
            "BEGIN:DAYLIGHT\r\nDTSTART:20070311T020000\r\n"
            f"TZOFFSETFROM:-0500\r\nTZOFFSETTO:{daylight}\r\n"
            f"RRULE:{daylight_rule}\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n")


def refused(raw: bytes, code: str, window=WINDOW) -> None:
    with pytest.raises(CalendarFileImportError) as caught:
        parse_calendar_file(raw, window)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert caught.value.args == (code,)


def test_minimal_projection_has_no_vendor_identity_or_retained_raw_bytes():
    secret = "https://example.invalid/private-feed/invented-secret"
    extra = (f"DESCRIPTION:{secret}\r\nURL:{secret}\r\nATTACH:{secret}\r\n"
             f"ATTENDEE:mailto:invented@example.invalid\r\nORGANIZER:{secret}\r\n"
             f"X-PRIVATE:{secret}\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\n"
             f"DESCRIPTION:{secret}\r\nEND:VALARM\r\n")
    raw = calendar(event(uid=secret, extra=extra), extra=f"SOURCE:{secret}\r\nX-WR-CALNAME:Atlas.md\r\n")
    result = parse_calendar_file(raw, WINDOW)
    data = asdict(result)
    assert set(data) == {"byte_sha256", "window", "items", "total_events", "matching_events", "more", "coverage"}
    assert result.byte_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.coverage == "file_window_only"
    assert not result.more
    row = result.items[0]
    assert set(asdict(row)) == {"item_index", "title", "title_truncated", "starts_at", "ends_at", "all_day", "cancelled"}
    assert row.title == "Example appointment"
    assert row.starts_at == "2026-10-25T13:00:00Z"
    encoded = json.dumps(data, default=str)
    for forbidden in (secret, "invented@example.invalid", "Atlas", "VCALENDAR", "UID", "DESCRIPTION"):
        assert forbidden not in encoded
    assert "Example appointment" not in repr(result)
    assert "Example appointment" not in repr(row)


def test_empty_file_calendar_is_explicitly_not_provider_completeness():
    result = parse_calendar_file(calendar(), WINDOW)
    assert result.items == ()
    assert (result.total_events, result.matching_events, result.more) == (0, 0, False)
    assert result.coverage == "file_window_only"


def test_whole_file_validates_then_only_first_25_are_projected():
    rows = [event(uid=f"invented-{i}", start=f"202610{25+i//24:02d}T{i%24:02d}0000Z",
                  end=f"202610{25+i//24:02d}T{i%24:02d}3000Z") for i in range(60)]
    result = parse_calendar_file(calendar(*reversed(rows)), WINDOW)
    assert result.total_events == 60
    # The window starts at 04:00 UTC, so its first four events are excluded.
    assert result.matching_events == 56
    assert len(result.items) == 25 and result.more
    assert result.items[0].starts_at == "2026-10-25T04:00:00Z"
    assert result.items[0].item_index == 55


def test_event_cap_checks_events_even_outside_window():
    rows = [event(uid=f"invented-{i}", start="20260101T120000Z", end="20260101T123000Z")
            for i in range(501)]
    refused(calendar(*rows), "calendar_event_limit")
    result = parse_calendar_file(calendar(*rows[:500]), WINDOW)
    assert result.total_events == 500 and result.matching_events == 0


@pytest.mark.parametrize("raw", [b"", b"not a calendar", b"\xff", b"PK\x03\x04", b"{}"])
def test_invalid_input_is_closed(raw):
    refused(raw, "calendar_file_invalid")


def test_raw_size_is_checked_before_decoding_or_tokenizing():
    refused(b"\xff" * (MAX_BYTES + 1), "calendar_file_too_large")


def test_exact_one_mib_limit_can_be_consumed_without_retaining_filler():
    base = calendar(event())
    line = b"X-IGNORE:" + b"a" * 1000 + b"\r\n"
    count, remainder = divmod(MAX_BYTES - len(base), len(line))
    filler = line * count
    # A final bounded X property makes the input exactly 1 MiB.
    if remainder < len(b"X-I:\r\n"):
        filler = line * (count - 1)
        remainder += len(line)
    filler += b"X-I:" + b"b" * (remainder - len(b"X-I:\r\n")) + b"\r\n"
    raw = base.replace(b"END:VCALENDAR", filler + b"END:VCALENDAR")
    assert len(raw) == MAX_BYTES
    assert parse_calendar_file(raw, WINDOW).matching_events == 1


@pytest.mark.parametrize("raw", [
    calendar(event()) + calendar(event(uid="invented-2")),
    calendar(event()).replace(b"END:VEVENT", b"END:VTODO"),
    calendar(event()).replace(b"VERSION:2.0", b"VERSION:2.0\r\nVERSION:2.0"),
    calendar(event()).replace(b"VERSION:2.0", b"VERSION:1.0"),
    calendar(event()).replace(b"END:VCALENDAR\r\n", b""),
    calendar(event()).replace(b"BEGIN:VEVENT", b"BEGIN:VEVENT\r\nBEGIN:VEVENT"),
    calendar(event(), extra="METHOD:REQUEST\r\n"),
    calendar(event(), extra="METHOD:CANCEL\r\n"),
    calendar(event(), extra="BEGIN:VTODO\r\nEND:VTODO\r\n"),
])
def test_invalid_or_unsupported_envelope(raw):
    refused(raw, "calendar_file_invalid")


def test_publish_is_accepted_without_sending_or_processing_invitations():
    assert parse_calendar_file(calendar(event(), extra="METHOD:PUBLISH\r\n"), WINDOW).items


def test_folded_utf8_title_is_unfolded_before_projection():
    raw = calendar(event(title="Example\\, visit\r\n  with café\\nfollow-up"))
    assert parse_calendar_file(raw, WINDOW).items[0].title == "Example, visit with café follow-up"


def test_folding_can_split_a_utf8_codepoint():
    raw = calendar(event(title="Café appointment")).replace(b"\xc3\xa9", b"\xc3\r\n \xa9")
    assert parse_calendar_file(raw, WINDOW).items[0].title == "Café appointment"


def test_unfolded_line_bound_and_line_count_are_checked():
    refused(calendar(event(title="A" * 16385)), "calendar_structure_limit")
    refused(calendar(event(title="A\r\n " + "B" * 16385)), "calendar_structure_limit")
    refused(calendar(event(), extra="X-IGNORE:x\r\n" * 20001), "calendar_structure_limit")


@pytest.mark.parametrize("extra", [
    "RRULE:FREQ=DAILY\r\n", "RDATE:20261026T130000Z\r\n", "EXDATE:20261025T130000Z\r\n",
    "RECURRENCE-ID:20261025T130000Z\r\n", "EXRULE:FREQ=YEARLY\r\n",
])
def test_event_recurrence_is_never_silently_truncated(extra):
    refused(calendar(event(extra=extra)), "calendar_recurrence_unsupported")


def test_invalid_event_after_first_page_or_outside_window_still_refuses():
    rows = [event(uid=f"invented-{i}") for i in range(26)]
    rows.append(event(uid="invented-invalid", start="20260101T120000", end="20260101T123000"))
    refused(calendar(*rows), "calendar_floating_time")


def test_duplicate_uid_and_different_sequence_are_not_overwritten():
    refused(calendar(event(), event(title="Changed", extra="SEQUENCE:9\r\n")), "calendar_duplicate_uid")
    refused(calendar(event(uid="invented\\,one"), event(uid="invented,one")), "calendar_duplicate_uid")


@pytest.mark.parametrize("change", [
    ("UID:invented-1", ""), ("UID:invented-1", "UID:"),
    ("DTSTART:20261025T130000Z", "DTSTART:20261025T130000Z\r\nDTSTART:20261025T140000Z"),
    ("DTEND:20261025T133000Z", ""),
    ("SUMMARY:Example appointment", "SUMMARY:one\r\nSUMMARY:two"),
])
def test_required_or_duplicate_properties_fail(change):
    raw = calendar(event()).replace(change[0].encode(), change[1].encode())
    with pytest.raises(CalendarFileImportError):
        parse_calendar_file(raw, WINDOW)


def test_duplicate_parameter_cannot_silently_replace_timezone():
    refused(calendar(event(params=";TZID=America/New_York;TZID=UTC")), "calendar_file_invalid")


@pytest.mark.parametrize("title", [
    "https://example.invalid/feed/secret", "webcal://example.invalid/feed/secret",
    "www.example.invalid/feed", "//example.invalid/feed", "file:///invented/feed",
    "mailto:example@example.invalid", "data:text/plain,secret", "https%3A%2F%2Fexample.invalid/feed",
    "https%253A%252F%252Fexample.invalid/feed", "https&#58;//example.invalid/feed",
    "https：//example.invalid/feed", "A" * 301 + " https://example.invalid/secret",
    "https : //example.invalid/secret",
])
def test_uri_in_entire_title_refuses_before_truncation(title):
    refused(calendar(event(title=title)), "calendar_uri_in_title")


def test_title_length_is_explicit_and_ordinary_colon_is_usable():
    result = parse_calendar_file(calendar(event(title="Visit: " + "A" * 300)), WINDOW)
    assert result.items[0].title == "Visit: " + "A" * 293
    assert result.items[0].title_truncated
    assert not parse_calendar_file(calendar(event(title="A" * 300)), WINDOW).items[0].title_truncated


@pytest.mark.parametrize("text", ["Example\x00visit", "Example\x1bvisit", "Example\u202evisit"])
def test_control_and_bidi_characters_are_not_rendered(text):
    with pytest.raises(CalendarFileImportError):
        parse_calendar_file(calendar(event(title=text)), WINDOW)


@pytest.mark.parametrize("status,cancelled", [("", False), ("TENTATIVE", False), ("CONFIRMED", False), ("CANCELLED", True)])
def test_cancellation_is_reported_without_inventing_booking_state(status, cancelled):
    extra = f"STATUS:{status}\r\n" if status else ""
    row = parse_calendar_file(calendar(event(extra=extra)), WINDOW).items[0]
    assert row.cancelled is cancelled
    assert "status" not in asdict(row)


def test_unknown_status_fails_closed():
    refused(calendar(event(extra="STATUS:NEW-VENDOR-STATE\r\n")), "calendar_event_invalid")


def test_all_day_dates_remain_date_only_and_end_is_exclusive():
    result = parse_calendar_file(calendar(
        event(uid="past", start="20261024", end="20261025", params=";VALUE=DATE"),
        event(uid="inside", start="20261025", end="20261026", params=";VALUE=DATE"),
        event(uid="future", start="20261101", end="20261102", params=";VALUE=DATE")), WINDOW)
    assert result.matching_events == 1
    row = result.items[0]
    assert row.all_day and row.starts_at == "2026-10-25" and row.ends_at == "2026-10-26"
    assert row.item_index == 1


def test_timed_window_uses_overlap_and_exclusive_end():
    raw = calendar(event(uid="before", start="20261025T033000Z", end="20261025T040000Z"),
                   event(uid="overlap", start="20261025T033000Z", end="20261025T043000Z"),
                   event(uid="end", start="20261101T040000Z", end="20261101T043000Z"))
    assert [row.item_index for row in parse_calendar_file(raw, WINDOW).items] == [1]


@pytest.mark.parametrize("start,end,params", [
    ("20261025T130000Z", "20261025T130000Z", ""),
    ("20261025T140000Z", "20261025T130000Z", ""),
    ("20261025", "20261024", ";VALUE=DATE"),
    ("20260230T130000Z", "20261025T133000Z", ""),
    ("20261025T130000-0400", "20261025T133000-0400", ""),
    ("20261025T130060Z", "20261025T133000Z", ""),
])
def test_bad_or_nonpositive_event_bounds(start, end, params):
    with pytest.raises(CalendarFileImportError):
        parse_calendar_file(calendar(event(start=start, end=end, params=params)), WINDOW)


@pytest.mark.parametrize("window,hours", [(FALL, 169), (SPRING, 167), (WINDOW, 168)])
def test_seven_day_window_uses_local_dates_across_dst(window, hours):
    start, end = window.bounds()
    assert end - start == timedelta(hours=hours)


@pytest.mark.parametrize("end,zone", [(date(2026, 11, 2), "UTC"), (date(2026, 11, 1), "Unknown/Invented")])
def test_invalid_user_window(end, zone):
    with pytest.raises(CalendarFileImportError, match="calendar_window_invalid"):
        CalendarImportWindow(date(2026, 10, 25), end, zone)


def test_known_iana_timezone_requires_matching_embedded_definition():
    raw = calendar(event(start="20261025T090000", end="20261025T093000",
                         params=";TZID=America/New_York"), extra=eastern())
    assert parse_calendar_file(raw, WINDOW).items[0].starts_at == "2026-10-25T13:00:00Z"
    refused(calendar(event(start="20261025T090000", end="20261025T093000",
                           params=";TZID=America/New_York")), "calendar_timezone_invalid")


def test_dst_fallback_changes_utc_conversion_without_changing_wall_time():
    raw = calendar(event(uid="before", start="20261031T090000", end="20261031T093000", params=";TZID=America/New_York"),
                   event(uid="after", start="20261101T090000", end="20261101T093000", params=";TZID=America/New_York"), extra=eastern())
    window = CalendarImportWindow(date(2026, 10, 30), date(2026, 11, 6), "America/New_York")
    assert [row.starts_at for row in parse_calendar_file(raw, window).items] == [
        "2026-10-31T13:00:00Z", "2026-11-01T14:00:00Z"]


@pytest.mark.parametrize("start,end,window", [
    ("20261101T013000", "20261101T023000", FALL),
    ("20260308T023000", "20260308T033000", SPRING),
])
def test_ambiguous_or_missing_local_time_is_not_guessed(start, end, window):
    refused(calendar(event(start=start, end=end, params=";TZID=America/New_York"), extra=eastern()),
            "calendar_timezone_conflict", window)


def test_floating_time_is_not_resolved_from_untrusted_calendar_metadata():
    refused(calendar(event(start="20261025T090000", end="20261025T093000"),
                     extra="X-WR-TIMEZONE:America/New_York\r\n" + eastern()), "calendar_floating_time")


@pytest.mark.parametrize("definition", [eastern(daylight="-0300"), eastern() + eastern()])
def test_conflicting_or_duplicate_timezone_refuses(definition):
    refused(calendar(event(), extra=definition), "calendar_timezone_conflict")


def test_subhour_timezone_disagreement_is_detected_even_with_only_utc_events():
    # Both ordinary hourly samples match; the declared transition is one minute late.
    definition = eastern().replace("DTSTART:20071104T020000", "DTSTART:20071104T020100")
    refused(calendar(event(start="20261101T140000Z", end="20261101T143000Z"), extra=definition),
            "calendar_timezone_conflict", FALL)


def test_timezone_rdates_are_bounded_and_a_matching_definition_works():
    definition = eastern().replace("RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "RDATE:20261101T020000").replace(
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "RDATE:20260308T020000")
    assert parse_calendar_file(calendar(event(), extra=definition), WINDOW).items
    too_many = definition.replace("RDATE:20260308T020000", "RDATE:" + ",".join(["20260308T020000"] * 33))
    refused(calendar(event(), extra=too_many), "calendar_timezone_invalid")


def test_timezone_component_and_nesting_limits():
    refused(calendar(event(), extra=eastern() * 9), "calendar_structure_limit")
    raw = calendar(event(extra="BEGIN:VALARM\r\nBEGIN:VALARM\r\nEND:VALARM\r\nEND:VALARM\r\n"))
    refused(raw, "calendar_file_invalid")


@pytest.mark.parametrize("rule", [
    "FREQ=SECONDLY", "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;COUNT=999999999",
    "FREQ=YEARLY;BYMONTH=3,4;BYDAY=2SU", "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;BYSECOND=1",
    "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;FREQ=YEARLY", "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;UNTIL=99991231T000000Z",
])
def test_timezone_recurrence_work_is_bounded_before_construction(rule):
    with pytest.raises(CalendarFileImportError):
        parse_calendar_file(calendar(event(), extra=eastern(daylight_rule=rule)), WINDOW)


def test_even_impossible_yearly_timezone_rules_have_an_explicit_horizon(monkeypatch):
    import dateutil.rrule

    original = dateutil.rrule.rrulestr
    checked = []

    def bounded(rule, *args, **kwargs):
        assert "UNTIL=21001231T235959Z" in rule
        checked.append(True)
        return original(rule, *args, **kwargs)

    monkeypatch.setattr(dateutil.rrule, "rrulestr", bounded)
    with pytest.raises(CalendarFileImportError):
        parse_calendar_file(calendar(event(), extra=eastern(daylight_rule="FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=31")), WINDOW)
    assert checked


def test_timezone_lookup_and_cache_never_see_arbitrary_file_identifier(monkeypatch):
    def forbidden(*args, **kwargs) -> NoReturn:
        pytest.fail("global timezone provider used")

    monkeypatch.setattr(tzp, "timezone", forbidden)
    monkeypatch.setattr(tzp, "cache_timezone_component", forbidden)
    assert parse_calendar_file(calendar(event(), extra=eastern()), WINDOW).items
    refused(calendar(event(), extra=eastern(name="Invented/Private-Feed-Identifier")), "calendar_timezone_invalid")


def test_success_and_failure_do_not_use_network_or_log_payload(monkeypatch, caplog, capsys):
    def forbidden(*args, **kwargs) -> NoReturn:
        pytest.fail("calendar parser attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(OpenerDirector, "open", forbidden)
    raw = calendar(event(extra="URL:https://example.invalid/invented-secret\r\n"), extra=eastern())
    assert parse_calendar_file(raw, WINDOW).items
    refused(calendar(event(title="https://example.invalid/invented-secret")), "calendar_uri_in_title")
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_missing_optional_parser_is_closed(monkeypatch):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("icalendar"):
            raise ImportError("invented dependency error")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    refused(calendar(event()), "calendar_parser_unavailable")
