from collections import Counter
from datetime import date
from zoneinfo import ZoneInfo

from worklog.render import Style, span_lines, bar, display_width, fit, fmt_minutes, render_rows, unit_bars, week_rows
from worklog.activity import LocalCalendar, day_start_minute
from worklog.report import Usage
from worklog.resolve import UNASSIGNED

DAY = date(2026, 9, 28)


def usage_of(totals: dict[str, int]) -> Usage:
    return Usage(start=DAY, end=DAY, by="repo", days={u: Counter({DAY: m}) for u, m in totals.items()})


def test_fit_pads_and_truncates_by_display_width():
    assert fit("(未分類)", 10) == "(未分類)  "
    assert display_width(fit("とても長いプロジェクト名です", 10)) == 10
    assert fit("とても長いプロジェクト名です", 10).rstrip().endswith("…")


def test_bars_start_at_the_same_column_with_fullwidth_names():
    usage = usage_of({"client-a-dashboard-long-name": 205, "blog": 108, UNASSIGNED: 10})
    lines = unit_bars(usage, Style.for_units(usage.units(), color=False), 24)
    starts = {display_width(line[: min(i for i in (line.find("█"), line.find("░")) if i >= 0)]) for line in lines}
    assert len(starts) == 1


def test_no_ansi_without_color():
    usage = usage_of({"a": 30, "b": 20})
    text = render_rows("週", week_rows(DAY), usage, 15, Style.for_units(usage.units(), color=False))
    assert "\033[" not in text


def test_color_output_has_ansi():
    usage = usage_of({"a": 30})
    lines = unit_bars(usage, Style.for_units(usage.units(), color=True), 24)
    assert "\033[38;5;" in lines[0]


def test_bar_widths():
    filled, rest = bar(50, 100, 10)
    assert display_width(filled) + display_width(rest) == 10
    assert bar(0, 100, 10) == ("", "░" * 10)


def test_fmt_minutes():
    assert fmt_minutes(205) == "3h25m"
    assert fmt_minutes(47) == "47m"
    assert fmt_minutes(-15) == "-15m"


def test_stack_groups_merge_minor_units():
    from worklog.render import OTHER, STACK_LIMIT, stack_groups

    units = [f"p{i}" for i in range(10)] + [UNASSIGNED]
    series, groups = stack_groups(units)
    assert series == units[:STACK_LIMIT] + [OTHER, UNASSIGNED]
    assert groups[OTHER] == units[STACK_LIMIT:10]
    assert stack_groups(units[:8])[0] == units[:8]


def test_span_lines_wrap_and_end_at_24():
    tz = ZoneInfo("Asia/Tokyo")
    start = day_start_minute(DAY, tz)
    minutes = set()
    for hour in range(0, 23, 2):
        minutes |= set(range(start + hour * 60, start + hour * 60 + 5))
    minutes |= set(range(start + 23 * 60 + 50, start + 24 * 60))
    usage = Usage(start=DAY, end=DAY, by="project", minutes={"a": minutes})
    lines = span_lines(usage, LocalCalendar(tz), line_width=60)
    assert lines[0] == "開始〜終了"
    assert lines[1].startswith("09/28 (月)   1h10m  00:00〜00:05 5m、")
    assert all(display_width(line) <= 60 for line in lines)
    assert lines[2].startswith(" " * display_width("09/28 (月)   1h10m  "))
    assert lines[-1].endswith("23:50〜24:00 10m")
