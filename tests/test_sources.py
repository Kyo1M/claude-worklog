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
    assert parser.state() == {"cwd": "/w/b", "session_id": "c1", "automated": False, "subagent": False}


def codex_user_message(when: str, text: str) -> dict:
    item = {"type": "UserMessage", "id": "item-1", "content": [{"type": "text", "text": text}]}
    return {"type": "event_msg", "timestamp": ts(when), "payload": {"type": "item_completed", "item": item}}


def codex_meta(when: str, source, session: str = "c1") -> dict:
    return {"type": "session_meta", "timestamp": ts(when), "payload": {"id": session, "cwd": "/w/a", "source": source}}


def test_codex_user_message_item_drops_ide_context():
    records = feed_all(
        CodexParser(),
        [
            codex_meta("2026-09-28 10:00", "vscode"),
            codex_user_message("2026-09-28 10:01", "集計を直して\n"),
            codex_user_message(
                "2026-09-28 10:02", "# Context from my IDE setup:\n\n## Active file: a.py\n\n## My request for Codex:\nテストも書いて\n"
            ),
            codex_user_message(
                "2026-09-28 10:03",
                '<in-app-browser-context source="ambient-ui-state">\nx\n</in-app-browser-context>\n\n## My request for Codex:\n画面を確認して',
            ),
            codex_user_message("2026-09-28 10:04", "<task>Run a review</task>"),
        ],
    )
    assert prompts(records) == ["集計を直して", "テストも書いて", "画面を確認して"]
    assert not any(r.automated for r in records if isinstance(r, Activity))


def test_codex_subagent_counts_time_but_is_not_a_session():
    records = feed_all(
        CodexParser(),
        [
            codex_meta("2026-09-28 10:00", {"subagent": {"other": "guardian"}}, "g1"),
            codex_user_message("2026-09-28 10:01", "The following is the Codex agent history"),
        ],
    )
    activity = [r for r in records if isinstance(r, Activity)]
    assert [r.session_id for r in activity] == [None, None]
    assert prompts(records) == []


def test_automated_runs_are_flagged():
    codex = [r for r in CodexParser().feed(codex_meta("2026-09-28 10:00", "exec")) if isinstance(r, Activity)]
    assert [r.automated for r in codex] == [True]
    claude = feed_all(
        ClaudeParser(),
        [
            claude_prompt("2026-09-28 10:00", "/", "日次ログを書いて", entrypoint="sdk-cli"),
            claude_line("2026-09-28 10:01", "/w", "s2", entrypoint="cli"),
        ],
    )
    assert [r.automated for r in claude if isinstance(r, Activity)] == [True, False]


def test_claude_lines_before_cwd_are_not_counted():
    records = feed_all(
        ClaudeParser(),
        [
            {"type": "queue-operation", "timestamp": ts("2026-09-28 10:00"), "sessionId": "s1"},
            claude_line("2026-09-28 10:00", "/w/app"),
        ],
    )
    assert [r.cwd for r in records if isinstance(r, Activity)] == ["/w/app"]


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
