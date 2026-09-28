import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from worklog.config import Config

JST = timezone(timedelta(hours=9))


def ts(text: str) -> str:
    """'2026-09-28 10:00' (JST) → UTC の ISO 文字列。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=JST).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(path: Path, rows: list[dict], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def claude_line(when: str, cwd: str, session: str = "s1", kind: str = "assistant", **extra) -> dict:
    return {"type": kind, "timestamp": ts(when), "cwd": cwd, "sessionId": session, **extra}


def claude_prompt(when: str, cwd: str, text, session: str = "s1", **extra) -> dict:
    return claude_line(when, cwd, session, kind="user", message={"role": "user", "content": text}, **extra)


def make_repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


@pytest.fixture
def env(tmp_path: Path):
    """ソースのディレクトリ・DB・設定をまとめた作業場所。"""
    claude_dir = tmp_path / "claude" / "projects"
    codex_dir = tmp_path / "codex" / "sessions"
    claude_dir.mkdir(parents=True)
    codex_dir.mkdir(parents=True)
    config = Config(
        claude_dir=claude_dir,
        codex_dir=codex_dir,
        db_path=tmp_path / "data" / "worklog.db",
        adjustments_path=tmp_path / "adjustments.csv",
        timezone="Asia/Tokyo",
        gap_minutes=15,
    )
    return tmp_path, config
