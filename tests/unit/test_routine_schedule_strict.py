from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from cosmas_os.ports.routines import BriefSchedule

BASELINE = dict(
    enabled=True,
    timezone="America/New_York",
    at="09:00",
    weekdays=[1, 2, 3, 4, 5],
)


def build(**changes):
    return BriefSchedule.model_validate({**BASELINE, **changes})


def test_baseline_builds_with_defaults():
    schedule = build()
    assert schedule.enabled is True
    assert schedule.timezone == "America/New_York"
    assert schedule.at == "09:00"
    assert schedule.weekdays == [1, 2, 3, 4, 5]
    assert schedule.max_runs_per_seven_days == 5
    assert schedule.kind == "practice_work_brief"
    quiet = build(quiet_start="22:00", quiet_end="06:00")
    assert quiet.quiet_start == "22:00"
    assert quiet.quiet_end == "06:00"


def _reject(changes: dict, *, loc, error_type: str):
    with pytest.raises(ValidationError) as exc:
        BriefSchedule.model_validate({**BASELINE, **changes})
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == loc
    assert errors[0]["type"] == error_type


def test_reject_unknown_timezone():
    _reject({"timezone": "Not/AZone"}, loc=(), error_type="value_error")


def test_reject_empty_timezone():
    _reject({"timezone": ""}, loc=("timezone",), error_type="string_too_short")


def test_reject_enabled_string():
    _reject({"enabled": "true"}, loc=("enabled",), error_type="bool_type")


@pytest.mark.parametrize("value", ["24:00", "9:00"])
def test_reject_invalid_at(value):
    _reject({"at": value}, loc=("at",), error_type="string_pattern_mismatch")


def test_reject_weekday_below_range():
    _reject({"weekdays": [0]}, loc=("weekdays", 0), error_type="greater_than_equal")


def test_reject_weekday_above_range():
    _reject({"weekdays": [8]}, loc=("weekdays", 0), error_type="less_than_equal")


def test_reject_weekday_string():
    _reject({"weekdays": ["1"]}, loc=("weekdays", 0), error_type="int_type")


def test_reject_empty_weekdays():
    _reject({"weekdays": []}, loc=("weekdays",), error_type="too_short")


def test_reject_duplicate_weekdays():
    _reject({"weekdays": [1, 1]}, loc=(), error_type="value_error")


def test_reject_only_quiet_start():
    _reject({"quiet_start": "22:00"}, loc=(), error_type="value_error")


def test_reject_only_quiet_end():
    _reject({"quiet_end": "06:00"}, loc=(), error_type="value_error")


def test_reject_identical_quiet_hours():
    _reject(
        {"quiet_start": "22:00", "quiet_end": "22:00"},
        loc=(),
        error_type="value_error",
    )


def test_reject_at_inside_quiet_hours():
    _reject(
        {"at": "23:00", "quiet_start": "22:00", "quiet_end": "06:00"},
        loc=(),
        error_type="value_error",
    )


def test_reject_max_runs_too_low():
    _reject(
        {"max_runs_per_seven_days": 0},
        loc=("max_runs_per_seven_days",),
        error_type="greater_than_equal",
    )


def test_reject_max_runs_too_high():
    _reject(
        {"max_runs_per_seven_days": 8},
        loc=("max_runs_per_seven_days",),
        error_type="less_than_equal",
    )


def test_reject_extra_key():
    _reject({"x": 1}, loc=("x",), error_type="extra_forbidden")


def test_reject_wrong_kind():
    _reject({"kind": "other"}, loc=("kind",), error_type="literal_error")


def test_reject_missing_at():
    payload = {**BASELINE}
    del payload["at"]
    with pytest.raises(ValidationError) as exc:
        BriefSchedule.model_validate(payload)
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("at",)
    assert errors[0]["type"] == "missing"


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("21:59", False),
        ("22:00", True),
        ("23:30", True),
        ("00:00", True),
        ("05:59", True),
        ("06:00", False),
        ("12:00", False),
    ],
)
def test_is_quiet_overnight(clock, expected):
    schedule = build(quiet_start="22:00", quiet_end="06:00")
    assert schedule.is_quiet(clock) is expected


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("11:59", False),
        ("12:00", True),
        ("12:59", True),
        ("13:00", False),
    ],
)
def test_is_quiet_same_day(clock, expected):
    schedule = build(quiet_start="12:00", quiet_end="13:00")
    assert schedule.is_quiet(clock) is expected


def test_is_quiet_without_quiet_hours():
    assert build().is_quiet("12:00") is False


def test_occurrence_weekday_and_weekend():
    schedule = build()
    assert schedule.occurrence(date(2026, 11, 19)) == datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
    assert schedule.occurrence(date(2026, 11, 21)) is None


def test_due_states():
    schedule = build()
    activated = datetime(2026, 11, 1, tzinfo=UTC)
    due_at = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
    assert schedule.due(due_at, activated) == ("due", due_at)
    assert schedule.due(datetime(2026, 11, 19, 13, 59, tzinfo=UTC), activated)[0] == "waiting"
    assert schedule.model_copy(update={"enabled": False}).due(due_at, activated) == (
        "paused",
        None,
    )
    with pytest.raises(ValueError) as exc:
        schedule.due(datetime(2026, 11, 19, 14, 0), activated)
    assert str(exc.value) == "An aware clock is required"


def test_next_occurrence():
    schedule = build()
    assert schedule.next_occurrence(datetime(2026, 11, 19, 15, 0, tzinfo=UTC)) == (
        datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    )
    saturday_only = build(weekdays=[6])
    assert saturday_only.next_occurrence(datetime(2026, 11, 19, 15, 0, tzinfo=UTC)) == datetime(
        2026, 11, 21, 14, 0, tzinfo=UTC
    )
