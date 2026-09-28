"""イベントの分から稼働した分を求める。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, tzinfo


def active_minutes(minutes: Iterable[int], gap: int) -> set[int]:
    """イベントがあった分と、差が gap 分以下の隣り合うイベントの間の分を稼働とする。"""
    active: set[int] = set()
    prev: int | None = None
    for m in sorted(set(minutes)):
        if prev is not None and m - prev <= gap:
            active.update(range(prev + 1, m))
        active.add(m)
        prev = m
    return active


def day_start_minute(day: date, tz: tzinfo | None) -> int:
    """tz の day の 0 時を UTC の epoch 分で返す。tz が None ならシステムのローカル。"""
    dt = datetime.combine(day, time())
    dt = dt.replace(tzinfo=tz) if tz else dt.astimezone()
    return int(dt.timestamp() // 60)


class LocalCalendar:
    """epoch 分 → 現地の日付・時刻。タイムゾーンのずれは 15 分単位なので 15 分ごとにキャッシュする。"""

    def __init__(self, tz: tzinfo | None):
        self.tz = tz
        self._cache: dict[int, datetime] = {}

    def local(self, minute: int) -> datetime:
        block = minute // 15
        base = self._cache.get(block)
        if base is None:
            base = datetime.fromtimestamp(block * 15 * 60, self.tz) if self.tz else datetime.fromtimestamp(block * 15 * 60).astimezone()
            self._cache[block] = base
        return base + timedelta(minutes=minute - block * 15)

    def date(self, minute: int) -> date:
        return self.local(minute).date()


def minutes_per_day(active: Iterable[int], calendar: LocalCalendar) -> Counter[date]:
    return Counter(calendar.date(m) for m in active)
