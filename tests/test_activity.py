from datetime import date
from zoneinfo import ZoneInfo

from worklog.activity import LocalCalendar, active_minutes, day_start_minute, minutes_per_day


def test_gap_of_15_minutes_is_connected():
    assert len(active_minutes([0, 15], gap=15)) == 16


def test_gap_of_16_minutes_is_split():
    assert active_minutes([0, 16], gap=15) == {0, 16}


def test_single_event_counts_one_minute():
    assert active_minutes([100], gap=15) == {100}


def test_duplicate_and_unsorted_minutes():
    assert active_minutes([10, 5, 5, 10], gap=15) == set(range(5, 11))


def test_minutes_are_split_at_local_midnight():
    tz = ZoneInfo("Asia/Tokyo")
    midnight = day_start_minute(date(2026, 9, 29), tz)
    active = active_minutes([midnight - 10, midnight + 9], gap=30)
    per_day = minutes_per_day(active, LocalCalendar(tz))
    assert per_day[date(2026, 9, 28)] == 10
    assert per_day[date(2026, 9, 29)] == 10


def test_local_calendar_time():
    tz = ZoneInfo("Asia/Tokyo")
    start = day_start_minute(date(2026, 9, 28), tz)
    local = LocalCalendar(tz).local(start + 10 * 60 + 7)
    assert (local.hour, local.minute) == (10, 7)
