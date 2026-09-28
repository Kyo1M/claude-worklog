"""Claude Code のセッションログ(~/.claude/projects/**/*.jsonl)の解析。"""

from __future__ import annotations

from collections.abc import Iterator

from .common import Activity, Prompt, Record, Title, clean_prompt, to_minute

SOURCE = "claude"
COUNTED_TYPES = {"user", "assistant", "system", "queue-operation"}


class ClaudeParser:
    """1 ファイル分の行を順に受け取る。cwd を持たない行は直前の cwd を使う。"""

    def __init__(self, state: dict | None = None):
        self.cwd: str | None = (state or {}).get("cwd")

    def state(self) -> dict:
        return {"cwd": self.cwd}

    def feed(self, obj: dict) -> Iterator[Record]:
        if isinstance(obj.get("cwd"), str):
            self.cwd = obj["cwd"]
        kind = obj.get("type")
        session_id = obj.get("sessionId")

        if kind == "ai-title" and session_id and isinstance(obj.get("aiTitle"), str):
            yield Title(session_id, obj["aiTitle"])
            return
        if kind not in COUNTED_TYPES:
            return
        minute = to_minute(obj.get("timestamp"))
        if minute is None:
            return
        yield Activity(minute, self.cwd, session_id)

        if kind == "user" and session_id and not obj.get("isMeta") and not obj.get("isSidechain"):
            text = _message_text(obj.get("message"))
            prompt = clean_prompt(text) if text else None
            if prompt:
                yield Prompt(session_id, minute, self.cwd, prompt)


def _message_text(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool_result":
            return None
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            texts.append(item["text"])
    return "\n".join(texts) or None
