"""期間の集計と補正の反映。"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .activity import LocalCalendar, active_minutes, day_start_minute, local_minute, minutes_per_day
from .config import Config
from .meetings import find_meetings
from .resolve import NO_CLIENT, UNASSIGNED, Resolver
from .store import Store


class AdjustmentError(Exception):
    pass


@dataclass(frozen=True)
class Adjustment:
    day: date
    project: str
    minutes: int
    note: str


@dataclass
class Usage:
    """集計単位(リポジトリ名・プロジェクト名・案件名のどれか)ごとの日別の分。"""

    start: date
    end: date  # この日を含む
    by: str
    days: dict[str, Counter[date]] = field(default_factory=dict)
    union: Counter[date] = field(default_factory=Counter)  # 全体を 1 本の時間軸に合成した実時間
    minutes: dict[str, set[int]] = field(default_factory=dict)  # 稼働した分(タイムライン用。会議は含み、補正は含まない)
    clients: dict[str, str] = field(default_factory=dict)  # 集計単位 → 案件名
    projects: dict[str, str] = field(default_factory=dict)  # 集計単位 → プロジェクト名
    adjusted: bool = False
    meetings: int = 0  # 時刻がそろい、稼働に足した会議の件数
    untimed_meetings: int = 0  # 期間内の議事録のうち start・end が無く足していない件数
    warnings: list[str] = field(default_factory=list)

    def total(self, unit: str) -> int:
        return sum(self.days.get(unit, Counter()).values())

    def day_total(self, day: date) -> int:
        return sum(c[day] for c in self.days.values())

    def grand_total(self) -> int:
        return sum(self.total(u) for u in self.days)

    def units(self) -> list[str]:
        """合計の多い順。未分類・案件未設定は最後。"""
        special = (UNASSIGNED, NO_CLIENT)
        return sorted(self.days, key=lambda u: (u in special, -self.total(u), u))


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def load_adjustments(path: Path) -> list[Adjustment]:
    if not path.exists():
        return []
    result = []
    with path.open(encoding="utf-8-sig", newline="") as f:  # Excel で保存した BOM 付きも読む
        reader = csv.DictReader(f)
        missing = {"date", "project", "minutes"} - set(reader.fieldnames or [])
        if missing:
            raise AdjustmentError(f"{path}: 列 {', '.join(sorted(missing))} がありません(date,project,minutes,note)")
        for lineno, row in enumerate(reader, start=2):
            try:
                result.append(
                    Adjustment(date.fromisoformat(row["date"].strip()), row["project"].strip(), int(row["minutes"]), (row.get("note") or "").strip())
                )
            except (ValueError, AttributeError, TypeError) as e:
                raise AdjustmentError(f"{path}:{lineno}: 値が読めません(date,project,minutes,note)") from e
    return result


def compute(
    store: Store,
    config: Config,
    resolver: Resolver,
    start: date,
    end: date,
    by: str = "project",
    adjustments: list[Adjustment] | None = None,
) -> Usage:
    tz = config.tz
    gap = config.gap_minutes
    lo = day_start_minute(start, tz)
    hi = day_start_minute(end + timedelta(days=1), tz)
    resolver.learn_names(store.all_cwds())

    # 期間の外側のイベントとつながる分も数えるため、前後に gap 分だけ広げて読む
    events: dict[str, list[int]] = defaultdict(list)
    usage = Usage(start=start, end=end, by=by)
    for minute, cwd in store.activity_between(lo - gap, hi + gap, config.include_automated):
        project = resolver.project(cwd)
        unit = {"repo": project.repo, "project": project.name, "client": project.client}[by]
        usage.clients[unit] = project.client
        usage.projects[unit] = project.name
        events[unit].append(minute)

    # AI の稼働とは別に、議事録の会議の時間をそのまま稼働に足す(同じ分は 1 回だけ数える。しきい値ではつなげない)
    active_by_unit = {unit: active_minutes(minutes, gap) for unit, minutes in events.items()}
    meetings, usage.warnings = find_meetings(resolver.repos(), config.minutes, start, end) if config.minutes else ([], [])
    for meeting in meetings:
        if meeting.start is None or meeting.end is None:
            usage.untimed_meetings += 1
            continue
        project = resolver.project(meeting.repo)
        unit = {"repo": project.repo, "project": project.name, "client": project.client}[by]
        usage.clients[unit] = project.client
        usage.projects[unit] = project.name
        begin, finish = local_minute(meeting.day, meeting.start, tz), local_minute(meeting.day, meeting.end, tz)
        active_by_unit.setdefault(unit, set()).update(range(begin, finish))
        usage.meetings += 1

    calendar = LocalCalendar(tz)
    everything: set[int] = set()
    for unit, all_active in active_by_unit.items():
        active = {m for m in all_active if lo <= m < hi}
        if not active:
            continue
        usage.minutes[unit] = active
        usage.days[unit] = minutes_per_day(active, calendar)
        everything |= active
    usage.union = minutes_per_day(everything, calendar)

    for adj in adjustments or []:
        if not start <= adj.day <= end:
            continue
        project, client = resolver.describe_name(adj.project)
        unit = {"repo": adj.project, "project": project, "client": client}[by]
        usage.clients.setdefault(unit, client)
        usage.projects.setdefault(unit, project)
        usage.days.setdefault(unit, Counter())[adj.day] += adj.minutes
        usage.union[adj.day] += adj.minutes
        usage.adjusted = True
    return usage

