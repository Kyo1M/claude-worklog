"""議事録の frontmatter(date・start・end)から会議の時間を読む。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

FRONTMATTER_LIMIT = 60  # frontmatter を探す行数の上限


@dataclass(frozen=True)
class Meeting:
    repo: str
    path: str
    day: date
    start: time | None  # start・end がそろっていないときは None
    end: time | None
    title: str


class MeetingError(ValueError):
    pass


def find_meetings(repos: Iterable[str], patterns: list[str], start: date, end: date) -> tuple[list[Meeting], list[str]]:
    """各リポジトリで patterns(リポジトリからの相対 glob)に当たる議事録のうち、date が期間内のものを返す。
    `_` で始まるフォルダ・ファイル(`_drafts/` の下書きなど)は読まない。読めない値は数えずに警告にする。"""
    meetings: list[Meeting] = []
    warnings: list[str] = []
    for repo in repos:
        seen: set[Path] = set()
        for pattern in patterns:
            for path in sorted(Path(repo).glob(pattern)):
                if path in seen or not path.is_file() or _hidden(path.relative_to(repo)):
                    continue
                seen.add(path)
                try:
                    meeting = read_meeting(repo, path, start, end)
                except MeetingError as e:
                    warnings.append(f"{path}: {e}")
                    continue
                if meeting:
                    meetings.append(meeting)
    return meetings, warnings


def _hidden(relative: Path) -> bool:
    return any(part.startswith(("_", ".")) for part in relative.parts)


def read_meeting(repo: str, path: Path, start: date, end: date) -> Meeting | None:
    """date が期間内の議事録を返す。date が無い・日付として読めないものは議事録として扱わない(None)。"""
    fields = read_frontmatter(path)
    try:
        day = date.fromisoformat(fields.get("date", ""))
    except ValueError:
        return None
    if not start <= day <= end:
        return None
    title = fields.get("title") or path.stem
    begin, finish = fields.get("start"), fields.get("end")
    if not begin or not finish:
        return Meeting(repo, str(path), day, None, None, title)
    begin_time, finish_time = _time(begin, "start"), _time(finish, "end")
    if finish_time <= begin_time:
        raise MeetingError(f"end {finish} が start {begin} より前です")
    return Meeting(repo, str(path), day, begin_time, finish_time, title)


def read_frontmatter(path: Path) -> dict[str, str]:
    """先頭の `---` で囲まれた範囲から、字下げの無い `key: value` だけを拾う(YAML の入れ子やリストは読まない)。"""
    try:
        with path.open(encoding="utf-8-sig") as f:
            if f.readline().strip() != "---":
                return {}
            fields: dict[str, str] = {}
            for _, line in zip(range(FRONTMATTER_LIMIT), f):
                if line.strip() == "---":
                    return fields
                if line[:1].isspace() or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                fields[key.strip()] = _unquote(value.split(" #", 1)[0].strip())
    except (OSError, UnicodeDecodeError):
        return {}
    return {}  # 閉じの `---` が無いものは frontmatter とみなさない


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _time(value: str, key: str) -> time:
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    raise MeetingError(f"{key} {value!r} は HH:MM で書いてください")
