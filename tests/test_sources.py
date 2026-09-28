from conftest import claude_line, claude_prompt, ts

from worklog.sources.claude import ClaudeParser
from worklog.sources.codex import CodexParser, read_titles
from worklog.sources.common import Activity, Prompt, Title, to_minute


def feed_all(parser, rows):
    return [r for row in rows for r in parser.feed(row)]


def prompts(records):
    return [r.text for r in records if isinstance(r, Prompt)]


def test_claude_counts_only_conversation_lines():
    records = feed_all(
        ClaudeParser(),
        [
            claude_line("2026-09-28 10:00", "/w/app", kind="assistant"),
            claude_line("2026-09-28 10:01", "/w/app", kind="attachment"),
            claude_line("2026-09-28 10:02", "/w/app", kind="system"),
            {"type": "last-prompt", "sessionId": "s1"},
        ],
    )
    activity = [r for r in records if isinstance(r, Activity)]
    assert [r.minute for r in activity] == [to_minute(ts("2026-09-28 10:00")), to_minute(ts("2026-09-28 10:02"))]


def test_claude_carries_cwd_to_lines_without_it():
    parser = ClaudeParser()
    feed_all(parser, [claude_line("2026-09-28 10:00", "/w/app")])
    [record] = feed_all(parser, [{"type": "assistant", "timestamp": ts("2026-09-28 10:01"), "sessionId": "s1"}])
    assert record.cwd == "/w/app"


def test_claude_prompt_extraction():
    records = feed_all(
        ClaudeParser(),
        [
            claude_prompt("2026-09-28 10:00", "/w", "集計を直して"),
            claude_prompt("2026-09-28 10:01", "/w", [{"type": "text", "text": "テストも書いて"}]),
            claude_prompt("2026-09-28 10:02", "/w", [{"type": "tool_result", "content": "ok"}]),
            claude_prompt("2026-09-28 10:03", "/w", "自動挿入", isMeta=True),
            claude_prompt("2026-09-28 10:04", "/w", "サブエージェントへの依頼", isSidechain=True),
            claude_prompt("2026-09-28 10:05", "/w", "<system-reminder>x</system-reminder>"),
            claude_prompt(
                "2026-09-28 10:06",
                "/w",
                "<command-message>x</command-message><command-name>/review</command-name><command-args>PR 12</command-args>",
            ),
            claude_prompt("2026-09-28 10:07", "/w", "[Request interrupted by user]"),
            claude_prompt("2026-09-28 10:08", "/w", "<command-name>/clear</command-name><command-args></command-args>"),
            claude_prompt("2026-09-28 10:09", "/w", "/compact"),
        ],
    )
    assert prompts(records) == ["集計を直して", "テストも書いて", "/review PR 12"]


def test_claude_title():
    [record] = list(ClaudeParser().feed({"type": "ai-title", "aiTitle": "集計の修正", "sessionId": "s1"}))
    assert record == Title("s1", "集計の修正")


def test_codex_session_meta_and_turn_context():
    parser = CodexParser()
    records = feed_all(
        parser,
        [
            {"type": "session_meta", "timestamp": ts("2026-09-28 10:00"), "payload": {"id": "c1", "cwd": "/w/a"}},
            {"type": "event_msg", "timestamp": ts("2026-09-28 10:01"), "payload": {"type": "user_message", "message": "直して"}},
            {"type": "turn_context", "timestamp": ts("2026-09-28 10:02"), "payload": {"cwd": "/w/b"}},
            {"type": "response_item", "timestamp": ts("2026-09-28 10:03"), "payload": {"type": "message"}},
        ],
    )
    activity = [r for r in records if isinstance(r, Activity)]
    assert [(r.cwd, r.session_id) for r in activity] == [("/w/a", "c1"), ("/w/a", "c1"), ("/w/b", "c1"), ("/w/b", "c1")]
    assert prompts(records) == ["直して"]
    assert parser.state() == {"cwd": "/w/b", "session_id": "c1"}


def test_codex_old_format_is_ignored():
    records = feed_all(
        CodexParser(),
        [
            {"id": "old", "timestamp": "2025-08-08T22:43:49.574Z", "instructions": None},
            {"type": "message", "role": "user", "content": []},
        ],
    )
    assert records == []


def test_codex_titles(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text('{"id": "c1", "thread_name": "資料の作成"}\nbroken\n', encoding="utf-8")
    assert list(read_titles(index)) == [Title("c1", "資料の作成")]
