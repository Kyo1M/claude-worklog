"""Codex のセッションログ(~/.codex/sessions/**/*.jsonl)の解析。

旧形式(各行に時刻と cwd が無い)は対象外。新形式は各行が `type`・`timestamp`・`payload` を持つ。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .common import Activity, Prompt, Record, Title, clean_prompt, to_minute

SOURCE = "codex"


class CodexParser:
    """cwd と session_id は session_meta / turn_context にしか無いので、読んだ位置の状態として持ち越す。"""

    def __init__(self, state: dict | None = None):
        state = state or {}
        self.cwd: str | None = state.get("cwd")
        self.session_id: str | None = state.get("session_id")

    def state(self) -> dict:
        return {"cwd": self.cwd, "session_id": self.session_id}

    def feed(self, obj: dict) -> Iterator[Record]:
        kind = obj.get("type")
        payload = obj.get("payload")
        if not isinstance(kind, str) or not isinstance(payload, dict):
            return
        if kind == "session_meta" and isinstance(payload.get("id"), str):
            self.session_id = payload["id"]
        if kind in ("session_meta", "turn_context") and isinstance(payload.get("cwd"), str):
            self.cwd = payload["cwd"]

        minute = to_minute(obj.get("timestamp"))
        if minute is None:
            return
        yield Activity(minute, self.cwd, self.session_id)

        if kind == "event_msg" and payload.get("type") == "user_message" and self.session_id:
            message = payload.get("message")
            prompt = clean_prompt(message) if isinstance(message, str) else None
            if prompt:
                yield Prompt(self.session_id, minute, self.cwd, prompt)


def read_titles(index_path: Path) -> Iterator[Title]:
    """~/.codex/session_index.jsonl からスレッド名を読む。"""
    if not index_path.exists():
        return
    with index_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("id"), str) and isinstance(obj.get("thread_name"), str):
                yield Title(obj["id"], obj["thread_name"])
