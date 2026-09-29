"""Codex のセッションログ(~/.codex/sessions/**/*.jsonl)の解析。

旧形式(各行に時刻と cwd が無い)は対象外。新形式は各行が `type`・`timestamp`・`payload` を持つ。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .common import Activity, Prompt, Record, Title, clean_prompt, to_minute

SOURCE = "codex"
# IDE の拡張・デスクトップ版は、開いているファイルなどの前置きのあとにこの見出しで依頼文を続ける
REQUEST_MARKER = "## My request for Codex:"


class CodexParser:
    """cwd と session_id は session_meta / turn_context にしか無いので、読んだ位置の状態として持ち越す。"""

    def __init__(self, state: dict | None = None):
        state = state or {}
        self.cwd: str | None = state.get("cwd")
        self.session_id: str | None = state.get("session_id")
        self.automated: bool = state.get("automated", False)
        self.subagent: bool = state.get("subagent", False)

    def state(self) -> dict:
        return {"cwd": self.cwd, "session_id": self.session_id, "automated": self.automated, "subagent": self.subagent}

    def feed(self, obj: dict) -> Iterator[Record]:
        kind = obj.get("type")
        payload = obj.get("payload")
        if not isinstance(kind, str) or not isinstance(payload, dict):
            return
        if kind == "session_meta":
            if isinstance(payload.get("id"), str):
                self.session_id = payload["id"]
            source = payload.get("source")
            self.automated = source == "exec"
            # 承認の審査(guardian)などのサブエージェント。時間は親と同じく数え、セッションとしては並べない
            self.subagent = isinstance(source, dict) and "subagent" in source
        if kind in ("session_meta", "turn_context") and isinstance(payload.get("cwd"), str):
            self.cwd = payload["cwd"]

        minute = to_minute(obj.get("timestamp"))
        if minute is None:
            return
        session_id = None if self.subagent else self.session_id
        yield Activity(minute, self.cwd, session_id, self.automated)

        text = _user_text(kind, payload) if session_id else None
        prompt = clean_prompt(text) if text else None
        if prompt:
            yield Prompt(session_id, minute, self.cwd, prompt)


def _user_text(kind: str, payload: dict) -> str | None:
    """依頼文。旧来の user_message と、現在の item_completed の UserMessage の両方を読む。"""
    if kind != "event_msg":
        return None
    text = None
    if payload.get("type") == "user_message" and isinstance(payload.get("message"), str):
        text = payload["message"]
    elif payload.get("type") == "item_completed":
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") == "UserMessage" and isinstance(item.get("content"), list):
            texts = [c["text"] for c in item["content"] if isinstance(c, dict) and isinstance(c.get("text"), str)]
            text = "\n".join(texts)
    if text and REQUEST_MARKER in text:
        text = text.rsplit(REQUEST_MARKER, 1)[1]
    return text or None


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
