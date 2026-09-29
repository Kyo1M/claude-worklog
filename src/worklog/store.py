"""取り込んだログを保存する SQLite。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    minute INTEGER NOT NULL,
    source TEXT NOT NULL,
    cwd TEXT NOT NULL,
    automated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (minute, source, cwd)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sessions (
    source TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT,
    cwd TEXT,
    first_minute INTEGER,
    last_minute INTEGER,
    automated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, session_id)
);
CREATE TABLE IF NOT EXISTS prompts (
    source TEXT NOT NULL,
    session_id TEXT NOT NULL,
    minute INTEGER NOT NULL,
    cwd TEXT,
    text TEXT NOT NULL,
    PRIMARY KEY (source, session_id, minute, text)
);
CREATE INDEX IF NOT EXISTS prompts_minute ON prompts (minute);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    state TEXT NOT NULL
);
"""
# 取り込み方を変えたら上げる。上がると取り込み済みのログを最初から読み直す
DATA_VERSION = 1
# automated の値。同じ分に対話と自動実行が重なったら対話(0)を残す。
# 2 は自動実行を区別する前に取り込んだ行で、読み直しで 0 か 1 に決まる(ログが消えていれば 2 のまま。対話として扱う)
AUTOMATED = 1
UNKNOWN = 2


@dataclass(frozen=True)
class FileMark:
    size: int
    offset: int
    state: dict


@dataclass(frozen=True)
class SessionRow:
    source: str
    session_id: str
    title: str | None
    cwd: str | None
    first_minute: int
    last_minute: int


@dataclass(frozen=True)
class PromptRow:
    source: str
    session_id: str
    minute: int
    cwd: str | None
    text: str


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        if self.conn.execute("PRAGMA user_version").fetchone()[0] < DATA_VERSION:
            self._upgrade()

    def _upgrade(self) -> None:
        for table in ("activity", "sessions"):
            columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if "automated" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN automated INTEGER NOT NULL DEFAULT 0")
                self.conn.execute(f"UPDATE {table} SET automated = {UNKNOWN}")
        # Codex のサブエージェントを 1 セッションとして入れていたので作り直す(Codex はログを消さない)
        self.conn.execute("DELETE FROM sessions WHERE source = 'codex'")
        self.conn.execute("DELETE FROM files")
        self.conn.execute(f"PRAGMA user_version = {DATA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    # 取り込み

    def file_mark(self, path: str) -> FileMark | None:
        row = self.conn.execute("SELECT size, offset, state FROM files WHERE path = ?", (path,)).fetchone()
        return FileMark(row[0], row[1], json.loads(row[2])) if row else None

    def set_file_mark(self, path: str, mark: FileMark) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO files (path, size, offset, state) VALUES (?, ?, ?, ?)",
            (path, mark.size, mark.offset, json.dumps(mark.state)),
        )

    def add_activity(self, rows: Iterable[tuple[int, str, str, int]]) -> None:
        """(minute, source, cwd, automated)。"""
        self.conn.executemany(
            """
            INSERT INTO activity (minute, source, cwd, automated) VALUES (?, ?, ?, ?)
            ON CONFLICT (minute, source, cwd) DO UPDATE SET automated = MIN(activity.automated, excluded.automated)
            """,
            rows,
        )

    def add_prompts(self, rows: Iterable[tuple[str, str, int, str | None, str]]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO prompts (source, session_id, minute, cwd, text) VALUES (?, ?, ?, ?, ?)", rows
        )

    def merge_sessions(self, rows: Iterable[tuple[str, str, str | None, int, int, int]]) -> None:
        """(source, session_id, cwd, first_minute, last_minute, automated) を既存の行と合わせる。"""
        self.conn.executemany(
            """
            INSERT INTO sessions (source, session_id, cwd, first_minute, last_minute, automated) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, session_id) DO UPDATE SET
                cwd = COALESCE(sessions.cwd, excluded.cwd),
                first_minute = MIN(COALESCE(sessions.first_minute, excluded.first_minute), excluded.first_minute),
                last_minute = MAX(COALESCE(sessions.last_minute, excluded.last_minute), excluded.last_minute),
                automated = MIN(sessions.automated, excluded.automated)
            """,
            rows,
        )

    def set_titles(self, rows: Iterable[tuple[str, str, str]]) -> None:
        """(source, session_id, title)。セッションの行が無ければ作る。"""
        self.conn.executemany(
            """
            INSERT INTO sessions (source, session_id, title) VALUES (?, ?, ?)
            ON CONFLICT (source, session_id) DO UPDATE SET title = excluded.title
            """,
            rows,
        )

    # 読み出し

    def activity_between(self, start_minute: int, end_minute: int, automated: bool = False) -> list[tuple[int, str]]:
        """[start, end) の (分, cwd)。ソースの違いはまとめる。automated が False なら自動実行だけの分を除く。"""
        return self.conn.execute(
            f"SELECT DISTINCT minute, cwd FROM activity WHERE minute >= ? AND minute < ? {_manual(automated)}",
            (start_minute, end_minute),
        ).fetchall()

    def activity_by_cwd(self, start_minute: int, end_minute: int, automated: bool = False) -> list[tuple[str, int]]:
        return self.conn.execute(
            f"SELECT cwd, COUNT(DISTINCT minute) FROM activity WHERE minute >= ? AND minute < ? {_manual(automated)} GROUP BY cwd",
            (start_minute, end_minute),
        ).fetchall()

    def all_cwds(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT cwd FROM activity")]

    def sessions_between(self, start_minute: int, end_minute: int, automated: bool = False) -> list[SessionRow]:
        rows = self.conn.execute(
            f"""
            SELECT source, session_id, title, cwd, first_minute, last_minute FROM sessions
            WHERE first_minute < ? AND last_minute >= ? {_manual(automated)} ORDER BY first_minute
            """,
            (end_minute, start_minute),
        ).fetchall()
        return [SessionRow(*r) for r in rows]

    def prompts_between(self, start_minute: int, end_minute: int) -> list[PromptRow]:
        rows = self.conn.execute(
            "SELECT source, session_id, minute, cwd, text FROM prompts WHERE minute >= ? AND minute < ? ORDER BY minute",
            (start_minute, end_minute),
        ).fetchall()
        return [PromptRow(*r) for r in rows]


def _manual(automated: bool) -> str:
    return "" if automated else f"AND automated != {AUTOMATED}"
