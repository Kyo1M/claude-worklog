"""ターミナル表示(バー・積み上げバー・タイムライン)。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from .activity import LocalCalendar
from .resolve import NO_CLIENT, UNASSIGNED
from .report import Usage, daterange

WEEKDAYS = "月火水木金土日"
PALETTE = [33, 208, 41, 170, 220, 45, 203, 141, 106, 214]
GRAY = 245
EIGHTHS = " ▏▎▍▌▋▊▉█"
PLAIN_FILLS = "█▓▒░#=+*%@"
STACK_LIMIT = 7  # 積み上げバーで個別に色分けする件数。残りは「その他」にまとめる
OTHER = "その他"
SPECIAL_FILLS = {UNASSIGNED: "·", NO_CLIENT: "·", OTHER: ":"}
NOTE = "※ AI とやりとりしていた時間の推定です。会議や AI を使わない作業は含みません。"


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(c) for c in text)


def fit(text: str, width: int) -> str:
    """表示幅 width に切り詰め・右詰めの空白埋めをする。"""
    if display_width(text) <= width:
        return text + " " * (width - display_width(text))
    out, used = "", 0
    for ch in text:
        w = char_width(ch)
        if used + w > width - 1:
            break
        out += ch
        used += w
    out += "…"
    return out + " " * (width - used - 1)


def fmt_minutes(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    h, m = divmod(abs(minutes), 60)
    return f"{sign}{h}h{m:02d}m" if h else f"{sign}{m}m"


def fmt_day(day: date) -> str:
    return f"{day.isoformat()} ({WEEKDAYS[day.weekday()]})"


@dataclass
class Style:
    color: bool
    colors: dict[str, int]

    @classmethod
    def for_units(cls, units: list[str], color: bool) -> "Style":
        colors, i = {OTHER: GRAY}, 0
        for u in units:
            if u in SPECIAL_FILLS:
                colors[u] = GRAY
            else:
                colors[u] = PALETTE[i % len(PALETTE)]
                i += 1
        return cls(color, colors)

    def paint(self, unit: str, text: str) -> str:
        if not self.color or not text:
            return text
        return f"\033[38;5;{self.colors.get(unit, GRAY)}m{text}\033[0m"

    def dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.color and text else text

    def fill(self, unit: str, units: list[str]) -> str:
        """色が無いときはプロジェクトごとに塗りの文字を変える。未分類は「·」。"""
        if self.color:
            return "█"
        if unit in SPECIAL_FILLS:
            return SPECIAL_FILLS[unit]
        regular = [u for u in units if u not in SPECIAL_FILLS]
        return PLAIN_FILLS[regular.index(unit) % len(PLAIN_FILLS)]


def bar(value: int, maximum: int, width: int) -> tuple[str, str]:
    """(塗り, 残り) を返す。1/8 文字単位で描く。"""
    if maximum <= 0 or value <= 0:
        return "", "░" * width
    eighths = round(max(value, 0) / maximum * width * 8)
    full, part = divmod(min(eighths, width * 8), 8)
    filled = "█" * full + (EIGHTHS[part] if part else "")
    return filled, "░" * (width - display_width(filled))


def stacked(values: list[tuple[str, int]], maximum: int, width: int, style: Style, units: list[str]) -> str:
    """累積で丸めて、区切りのずれがたまらないようにする。"""
    if maximum <= 0:
        return ""
    out, acc, drawn = "", 0, 0
    for unit, value in values:
        if value <= 0:
            continue
        acc += value
        end = round(acc / maximum * width)
        n = end - drawn
        if n > 0:
            out += style.paint(unit, style.fill(unit, units) * n)
            drawn = end
    return out


def name_width(names: list[str], limit: int = 28) -> int:
    return min(max([display_width(n) for n in names] + [8]), limit)


def header(title: str, usage: Usage, gap: int) -> str:
    total = usage.grand_total()
    real = sum(usage.union.values())
    head = f"{title}  しきい値 {gap} 分・1 分単位"
    return f"{head}    合計 {fmt_minutes(total)}(実時間 {fmt_minutes(real)})"


def footer(usage: Usage, style: Style) -> list[str]:
    lines = []
    if usage.adjusted:
        lines.append(style.dim("補正を含みます(--raw で補正前)"))
    lines.append(style.dim(NOTE))
    return lines


def unit_bars(usage: Usage, style: Style, bar_width: int) -> list[str]:
    units = usage.units()
    width = name_width(units)
    maximum = max((usage.total(u) for u in units), default=0)
    lines = []
    for u in units:
        filled, rest = bar(usage.total(u), maximum, bar_width)
        lines.append(f"{fit(u, width)}  {style.paint(u, filled)}{style.dim(rest)}  {fmt_minutes(usage.total(u)):>7}")
    return lines


def render_day(usage: Usage, gap: int, style: Style, calendar: LocalCalendar, bar_width: int = 24) -> str:
    day = usage.start
    lines = [header(fmt_day(day), usage, gap), ""]
    if not usage.days:
        lines.append("稼働の記録はありません。")
        return "\n".join(lines + [""] + footer(usage, style))
    lines += unit_bars(usage, style, bar_width)

    units = [u for u in usage.units() if usage.minutes.get(u)]
    if units:
        width = name_width(usage.units())
        axis = "".join(f"{h:<6}" for h in range(0, 24, 3)) + "24"
        lines += ["", f"{fit('時間帯', width)}  {axis}"]
        for u in units:
            bins = {_bin_of(calendar, m) for m in usage.minutes[u]}
            row = "".join(style.paint(u, "▇") if i in bins else style.dim("·") for i in range(48))
            lines.append(f"{fit(u, width)}  {row}")
    return "\n".join(lines + [""] + footer(usage, style))


def _bin_of(calendar: LocalCalendar, minute: int) -> int:
    t = calendar.local(minute)
    return t.hour * 2 + t.minute // 30


def render_rows(
    title: str,
    rows: list[tuple[str, list[date]]],
    usage: Usage,
    gap: int,
    style: Style,
    bar_width: int = 40,
) -> str:
    """week / month 共通。rows は (行ラベル, その行に含む日付)。"""
    lines = [header(title, usage, gap), ""]
    if not usage.days:
        lines.append("稼働の記録はありません。")
        return "\n".join(lines + [""] + footer(usage, style))

    units, groups = stack_groups(usage.units())
    totals = [
        [(u, sum(usage.days[m][d] for m in groups[u] for d in days)) for u in units] for _, days in rows
    ]
    row_sums = [sum(v for _, v in t) for t in totals]
    maximum = max(row_sums, default=0)
    label_width = max(display_width(label) for label, _ in rows)
    for (label, _), values, row_sum in zip(rows, totals, row_sums):
        drawn = stacked(values, maximum, bar_width, style, units)
        pad = " " * (bar_width - display_width(_strip_ansi(drawn)))
        lines.append(f"{fit(label, label_width)}  {drawn}{pad}  {fmt_minutes(row_sum):>7}")

    legend = "  ".join(f"{style.paint(u, style.fill(u, units))} {u}" for u in units)
    lines += ["", legend, "", {"client": "案件別", "repo": "リポジトリ別"}.get(usage.by, "プロジェクト別")]
    lines += unit_bars(usage, style, 24)
    return "\n".join(lines + [""] + footer(usage, style))


def stack_groups(units: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """積み上げバーの系列。上位 STACK_LIMIT 件のほかは「その他」にまとめる。"""
    regular = [u for u in units if u not in SPECIAL_FILLS]
    special = [u for u in units if u in SPECIAL_FILLS]
    if len(regular) <= STACK_LIMIT + 1:
        return units, {u: [u] for u in units}
    shown = regular[:STACK_LIMIT]
    groups = {u: [u] for u in shown + special}
    groups[OTHER] = regular[STACK_LIMIT:]
    return shown + [OTHER] + special, groups


def week_rows(start: date) -> list[tuple[str, list[date]]]:
    return [(f"{WEEKDAYS[d.weekday()]} {d:%m/%d}", [d]) for d in daterange(start, start + timedelta(days=6))]


def month_rows(first: date, last: date) -> list[tuple[str, list[date]]]:
    rows, d = [], first
    while d <= last:
        end = min(d + timedelta(days=6 - d.weekday()), last)
        rows.append((f"{d:%m/%d}〜{end:%m/%d}", list(daterange(d, end))))
        d = end + timedelta(days=1)
    return rows


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)
