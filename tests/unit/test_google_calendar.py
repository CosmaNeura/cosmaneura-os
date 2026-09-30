from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cosmas_os.adapters.google_calendar import boundary, read_calendar


def event(**changes):
    return {"id": "invented_event", "summary": "Invented visit", "status": "confirmed",
            "start": {"dateTime": "2026-10-31T13:00:00-04:00"},
            "end": {"dateTime": "2026-10-31T14:00:00-04:00"}, **changes}


def read(items, **response):
    audits = []
    service = SimpleNamespace(now=lambda: datetime(2026, 10, 30, 12, tzinfo=UTC),
        _request=lambda *a, **k: {"items": items, **response},
        _read_current=lambda *a, **k: audits.append(k.get("audit")),
        _text=lambda value, limit: value if isinstance(value, str) and len(value) <= limit else (_ for _ in ()).throw(ValueError()))
    result = read_calendar(service, None, {"token": "invented", "label": "Invented", "email": "invented@example.invalid"}, "", "")
    assert audits == [False, False, "calendar"]
    return result


def test_timed_and_all_day_dates_survive_dst_without_exposing_event_details():
    value = read([event(), event(id="all_day", start={"date": "2026-11-01"}, end={"date": "2026-11-03"})],
                 nextPageToken="opaque-not-followed")
    assert value["items"][0]["starts_at"] == "2026-10-31T17:00:00+00:00"
    assert value["items"][1]["starts_at"] == "2026-11-01"
    assert value["items"][1]["ends_at"] == "2026-11-03" and value["items"][1]["all_day"]
    assert value["more"] is True


@pytest.mark.parametrize("items", [
    [event(), event()], [event()] * 26,
    [event(start={"dateTime": "2026-10-31T13:00:00"})],
    [event(start={"date": "2026-02-30"}, end={"date": "2026-03-01"})],
    [event(end={"date": "2026-11-01"})],
    [event(end={"dateTime": "2026-10-31T12:00:00-04:00"})],
    [event(start={"dateTime": "2027-01-01T12:00:00Z"}, end={"dateTime": "2027-01-01T13:00:00Z"})],
    [event(description="Must not enter the projected response")],
])
def test_malformed_duplicate_over_limit_or_out_of_window_events_are_rejected(items):
    with pytest.raises(ValueError):
        read(deepcopy(items))


def test_all_day_keeps_the_exact_date_and_rejects_ambiguous_boundaries():
    assert boundary({"date": "2026-11-01"})[:2] == ("2026-11-01", True)
    with pytest.raises(ValueError):
        boundary({"date": "2026-11-01", "dateTime": "2026-11-01T00:00:00Z"})
