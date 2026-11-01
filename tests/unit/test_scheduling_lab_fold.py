"""Lab scheduling DST fold stays on a future autumn Sunday."""

from datetime import UTC, date, datetime

from lab.scheduling_tools import eastern_fall_fold_day


def test_eastern_fall_fold_day_keeps_2026_before_the_window_ends():
    assert eastern_fall_fold_day(datetime(2026, 10, 31, 12, tzinfo=UTC)) == date(2026, 11, 1)
    assert eastern_fall_fold_day(datetime(2026, 11, 1, 7, tzinfo=UTC)) == date(2026, 11, 1)


def test_eastern_fall_fold_day_advances_after_the_2026_window_passes():
    assert eastern_fall_fold_day(datetime(2026, 11, 1, 13, tzinfo=UTC)) == date(2027, 11, 7)
    assert eastern_fall_fold_day(datetime(2026, 11, 2, tzinfo=UTC)) == date(2027, 11, 7)
