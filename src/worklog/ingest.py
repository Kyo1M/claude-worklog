"""ログファイルの差分を読み、Store に取り込む。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .sources import claude, codex
from .sources.common import Activity, Prompt, Title
from .store import FileMark, Store

PARSERS = {claude.SOURCE: claude.ClaudeParser, codex.SOURCE: codex.CodexParser}


@dataclass
class IngestStats:
    files: int = 0
    lines: int = 0
    skipped_lines: int = 0
    warnings: list[str] = field(default_factory=list)


def ingest(store: Store, config: Config) -> IngestStats:
    stats = IngestStats()
    missing = []
    for source, root in ((claude.SOURCE, config.claude_dir), (codex.SOURCE, config.codex_dir)):
        if not root.exists():
            missing.append(str(root))
            continue
        for path in sorted(root.rglob("*.jsonl")):
            ingest_file(store, source, path, stats)
            store.commit()
    if len(missing) == 2:  # 片方だけ使う人には警告しない
        stats.warnings.append(f"Claude Code と Codex のログが見つかりません: {'、'.join(missing)}")

    titles = [(codex.SOURCE, t.session_id, t.title) for t in codex.read_titles(config.codex_index)]
    store.set_titles(titles)
    store.commit()
    return stats


def ingest_file(store: Store, source: str, path: Path, stats: IngestStats) -> None:
    key = str(path)
    size = path.stat().st_size
    mark = store.file_mark(key)
    if mark and size < mark.offset:
        mark = None  # 書き換えられたので最初から読み直す(保存は冪等なので重複しない)
    offset = mark.offset if mark else 0
    if size == offset:
        return

    with path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return  # 書き込み途中の行だけなので次回に回す

    parser = PARSERS[source](mark.state if mark else None)
    activity: dict[tuple[int, str, str], int] = {}
    prompts: list[tuple[str, str, int, str | None, str]] = []
    titles: list[tuple[str, str, str]] = []
    sessions: dict[str, list] = {}

    for raw in data[: end + 1].splitlines():
        if not raw.strip():
            continue
        stats.lines += 1
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            stats.skipped_lines += 1
            continue
        if not isinstance(obj, dict):
            stats.skipped_lines += 1
            continue
        for record in parser.feed(obj):
            if isinstance(record, Activity):
                row = (record.minute, source, record.cwd or "")
                activity[row] = min(activity.get(row, 1), int(record.automated))
                if record.session_id:
                    s = sessions.setdefault(record.session_id, [record.cwd, record.minute, record.minute, 1])
                    s[0] = s[0] or record.cwd
                    s[1] = min(s[1], record.minute)
                    s[2] = max(s[2], record.minute)
                    s[3] = min(s[3], int(record.automated))
            elif isinstance(record, Prompt):
                prompts.append((source, record.session_id, record.minute, record.cwd, record.text))
            elif isinstance(record, Title):
                titles.append((source, record.session_id, record.title))

    store.add_activity((*row, automated) for row, automated in activity.items())
    store.merge_sessions((source, sid, cwd, first, last, auto) for sid, (cwd, first, last, auto) in sessions.items())
    store.add_prompts(prompts)
    store.set_titles(titles)
    store.set_file_mark(key, FileMark(size=size, offset=offset + end + 1, state=parser.state()))
    stats.files += 1
