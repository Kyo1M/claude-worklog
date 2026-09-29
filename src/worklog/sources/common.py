"""ソースの解析結果の型と共通処理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

PROMPT_MAX_CHARS = 500
# 作業内容の手がかりにならない組み込みコマンド
IGNORED_COMMANDS = {
    "/clear", "/compact", "/exit", "/quit", "/model", "/resume", "/config", "/cost", "/status", "/help",
    "/login", "/logout", "/effort", "/fast", "/permissions", "/memory", "/context", "/usage", "/rewind",
}


@dataclass(frozen=True)
class Activity:
    minute: int
    cwd: str | None
    session_id: str | None
    automated: bool = False  # claude -p・codex exec などの自動実行


@dataclass(frozen=True)
class Prompt:
    session_id: str
    minute: int
    cwd: str | None
    text: str


@dataclass(frozen=True)
class Title:
    session_id: str
    title: str


Record = Activity | Prompt | Title


def to_minute(timestamp: object) -> int | None:
    """ISO 8601 の時刻を UTC の epoch 分に丸める。"""
    if not isinstance(timestamp, str):
        return None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return int(dt.timestamp() // 60)


_COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def clean_prompt(text: str) -> str | None:
    """人が入力した依頼文だけを残す。自動挿入の文は None。"""
    text = text.strip()
    if not text:
        return None
    name = _COMMAND_NAME.search(text)
    if name:
        args = _COMMAND_ARGS.search(text)
        command = name.group(1).strip()
        if command in IGNORED_COMMANDS:
            return None
        text = f"{command} {args.group(1).strip() if args else ''}".strip()
    elif text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    elif text.split(maxsplit=1)[0] in IGNORED_COMMANDS:
        return None
    return text[:PROMPT_MAX_CHARS]
