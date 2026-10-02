"""Closed human calendar-source contract; all labels and data are invented."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.api.google_calendar_schemas import CALENDAR_COMMAND, ReviewCalendar
from cosmas_os.application import google_calendar as calendar
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ports.google_calendar import (
    GoogleCalendarAccount,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarWindow,
)

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


def observed(event):
    return GoogleCalendarObservation(kind="calendar", account=GoogleCalendarAccount(label="Invented café 🫀", email="owner@example.invalid"),
        items=(event,), more=False, observed_at=NOW, window=GoogleCalendarWindow(starts_at=NOW, ends_at=NOW + timedelta(days=7)))


def timed(**changes):
    return GoogleCalendarEvent(**{"id": "invented_event", "subject": "Invented café 🫀", "starts_at": "2026-10-31T13:00:00Z",
        "ends_at": "2026-10-31T14:00:00Z", "all_day": False, "cancelled": False, **changes})


@pytest.mark.parametrize("command", [
    {"action": "observe", "idempotency_key": "observe-1", "time_min": "2027-01-01"},
    {"action": "observe", "idempotency_key": "observe-1", "maxResults": 50},
    {"action": "observe", "idempotency_key": "observe-1", "account_id": str(uuid4())},
    {"action": "observe", "idempotency_key": "observe-1", "url": "https://example.invalid"},
    {"action": "observe", "idempotency_key": "observe-1", "event_id": "invented_event"},
    {"action": "read", "idempotency_key": "observe-1"},
    {"action": "inspect", "observation_id": "not-a-uuid"},
    {"action": "resolve", "idempotency_key": "short"},
])
def test_closed_commands_reject_browser_range_and_provider_inputs(command):
    with pytest.raises(ValidationError):
        CALENDAR_COMMAND.validate_python(command)


def review_body(**changes):
    return dict(expected_revision=1, idempotency_key="review-1", observation_id=str(uuid4()), observation_sha256="a" * 64,
        event_id="invented_event", event_sha256="b" * 64, reviewed_visit=True, reviewed_exact_summary=True,
        reviewed_untrusted_source=True, **changes)


@pytest.mark.parametrize("field", ["reviewed_visit", "reviewed_exact_summary", "reviewed_untrusted_source"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_review_requires_literal_human_acknowledgments(field, value):
    body = review_body()
    body[field] = value
    with pytest.raises(ValidationError):
        ReviewCalendar.model_validate(body)


@pytest.mark.parametrize("field,value", [("expected_revision", True), ("expected_revision", "1"),
    ("patient_link_id", str(uuid4())), ("content", "Invented altered content"), ("event_id", "a/b")])
def test_review_cannot_replace_server_owned_visit_or_content(field, value):
    body = review_body()
    body[field] = value
    with pytest.raises(ValidationError):
        ReviewCalendar.model_validate(body)


def test_utf8_content_and_ascii_event_hash_are_distinct_exact_contracts():
    event = timed()
    observation = observed(event)
    content = calendar.source_content(observation, event)
    assert "Invented café 🫀" in content and "Status: not marked cancelled" in content
    assert content.endswith("This observed summary does not establish current availability or a booking.")
    assert "confirmed" not in content and "tentative" not in content
    assert calendar.event_hash(event) == payload_hash(event.model_dump(mode="json"))
    assert calendar.event_hash(event) != calendar._payload_digest(event.model_dump(mode="json"))
    payload = observation.model_dump(mode="json")
    assert calendar._payload_digest(payload) == hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() != payload_hash({"content": content})


def test_timed_source_authority_ends_at_exclusive_event_end_or_window_end():
    event = timed()
    assert calendar.valid_until(observed(event), event) == datetime(2026, 10, 31, 14, tzinfo=UTC)
    longer = timed(ends_at="2026-11-10T14:00:00Z")
    assert calendar.valid_until(observed(longer), longer) == NOW + timedelta(days=7)


def test_all_day_source_uses_conservative_earliest_end_without_inventing_timezone():
    event = GoogleCalendarEvent(id="date_only", subject="Invented all-day", starts_at="2026-10-31", ends_at="2026-11-03", all_day=True, cancelled=False)
    assert calendar.valid_until(observed(event), event) == datetime(2026, 11, 2, tzinfo=UTC)
    content = calendar.source_content(observed(event), event)
    assert "Ends (exclusive): 2026-11-03\nAll day: yes" in content
    assert "timezone" not in content


def test_all_day_maximum_year_expiry_does_not_overflow():
    event = GoogleCalendarEvent(id="far_date", subject="Invented", starts_at="9999-12-30", ends_at="9999-12-31", all_day=True, cancelled=False)
    window = GoogleCalendarWindow(starts_at=datetime(9999, 12, 24, tzinfo=UTC), ends_at=datetime(9999, 12, 31, tzinfo=UTC))
    observation = GoogleCalendarObservation(kind="calendar", account=GoogleCalendarAccount(label="Invented", email="owner@example.invalid"),
        items=(event,), more=False, observed_at=window.starts_at, window=window)
    assert calendar.valid_until(observation, event) == datetime(9999, 12, 30, tzinfo=UTC)
