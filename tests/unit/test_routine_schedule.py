from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from cosmas_os.ports.routines import BriefSchedule


def schedule(**changes):
    return BriefSchedule.model_validate({**dict(enabled=True, timezone="America/New_York",
        at="08:00", weekdays=[1, 2, 3, 4, 5], quiet_start="18:00", quiet_end="07:00"), **changes})


@pytest.mark.parametrize("field,value", [
    ("timezone", "../../etc/passwd"), ("timezone", "Invented/Zone"),
    ("at", "24:00"), ("at", "8:00"), ("weekdays", [1, 1]), ("weekdays", [True]),
    ("weekdays", [0]), ("weekdays", []), ("max_runs_per_seven_days", 0),
    ("max_runs_per_seven_days", 8), ("max_runs_per_seven_days", True),
    ("enabled", "true"), ("quiet_end", None), ("quiet_end", "18:00"),
    ("at", "19:00"), ("send_messages", True),
])
def test_reject_invalid_or_expanded_authority(field, value):
    config = dict(enabled=True, timezone="UTC", at="08:00", weekdays=[1, 2],
                  quiet_start="18:00", quiet_end="07:00")
    config[field] = value
    with pytest.raises(ValidationError):
        BriefSchedule.model_validate(config)


def test_spring_gap_skips_and_autumn_repeat_runs_first_only():
    config = BriefSchedule(enabled=True, timezone="America/New_York", at="02:30", weekdays=[7])
    assert config.occurrence(date(2026, 3, 8)) is None
    assert config.next_occurrence(datetime(2026, 3, 8, tzinfo=UTC)) == datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
    repeated = config.model_copy(update={"at": "01:30"})
    assert repeated.occurrence(date(2026, 11, 1)) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


def test_weekdays_activation_and_bounded_restart():
    config = schedule()
    activated = datetime(2026, 9, 20, tzinfo=UTC)
    due = datetime(2026, 9, 21, 12, tzinfo=UTC)
    assert config.due(due - timedelta(seconds=1), activated)[0] == "waiting"
    assert config.due(due, activated) == ("due", due)
    assert config.due(due + timedelta(hours=6), activated)[0] == "due"
    assert config.due(due + timedelta(hours=6, seconds=1), activated)[0] == "missed"
    assert config.due(due, due + timedelta(seconds=1))[0] == "waiting"
    assert config.due(due + timedelta(days=5), activated)[0] == "waiting"
    assert config.due(datetime(2026, 9, 22, 4, tzinfo=UTC), activated)[0] == "waiting"


def test_late_restart_obeys_quiet_hours_and_pause():
    config = BriefSchedule(enabled=True, timezone="UTC", at="16:00", weekdays=[1],
                           quiet_start="17:00", quiet_end="08:00")
    activated = datetime(2026, 9, 20, tzinfo=UTC)
    assert config.due(datetime(2026, 9, 21, 18, tzinfo=UTC), activated)[0] == "quiet_hours"
    assert config.model_copy(update={"enabled": False}).due(activated, activated)[0] == "paused"
    with pytest.raises(ValueError):
        config.due(datetime(2026, 9, 21), activated)
