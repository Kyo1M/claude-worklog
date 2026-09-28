import json

from conftest import claude_line, claude_prompt, ts, write_jsonl

from worklog.ingest import ingest
from worklog.store import Store


def count(store, table):
    return store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_reads_only_appended_lines(env):
    root, config = env
    log = config.claude_dir / "p" / "s1.jsonl"
    write_jsonl(log, [claude_line("2026-09-28 10:00", "/w/app")])
    store = Store(config.db_path)
    assert ingest(store, config).lines == 1

    write_jsonl(log, [claude_line("2026-09-28 10:05", "/w/app")], mode="a")
    stats = ingest(store, config)
    assert stats.lines == 1
    assert count(store, "activity") == 2


def test_partial_line_is_read_next_time(env):
    root, config = env
    log = config.claude_dir / "p" / "s1.jsonl"
    line = json.dumps(claude_line("2026-09-28 10:00", "/w/app"))
    log.parent.mkdir(parents=True)
    log.write_text(line[:20])
    store = Store(config.db_path)
    assert ingest(store, config).lines == 0

    log.write_text(line + "\n")
    assert ingest(store, config).lines == 1
    assert count(store, "activity") == 1


def test_reingest_is_idempotent(env):
    root, config = env
    write_jsonl(
        config.claude_dir / "p" / "s1.jsonl",
        [claude_prompt("2026-09-28 10:00", "/w/app", "直して"), claude_line("2026-09-28 10:01", "/w/app")],
    )
    store = Store(config.db_path)
    ingest(store, config)
    store.conn.execute("DELETE FROM files")
    ingest(store, config)
    assert count(store, "activity") == 2
    assert count(store, "prompts") == 1
    assert count(store, "sessions") == 1


def test_shrunk_file_is_read_again(env):
    root, config = env
    log = config.claude_dir / "p" / "s1.jsonl"
    write_jsonl(log, [claude_line("2026-09-28 10:00", "/w/app"), claude_line("2026-09-28 10:01", "/w/app")])
    store = Store(config.db_path)
    ingest(store, config)

    write_jsonl(log, [claude_line("2026-09-28 11:00", "/w/app")])
    assert ingest(store, config).lines == 1
    assert count(store, "activity") == 3


def test_broken_lines_are_counted(env):
    root, config = env
    log = config.claude_dir / "p" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{broken\n[1, 2]\n" + json.dumps(claude_line("2026-09-28 10:00", "/w")) + "\n")
    stats = ingest(Store(config.db_path), config)
    assert (stats.lines, stats.skipped_lines) == (3, 2)


def test_codex_cwd_survives_incremental_reads(env):
    root, config = env
    log = config.codex_dir / "2026" / "09" / "28" / "rollout-1.jsonl"
    write_jsonl(log, [{"type": "session_meta", "timestamp": ts("2026-09-28 10:00"), "payload": {"id": "c1", "cwd": "/w/app"}}])
    store = Store(config.db_path)
    ingest(store, config)
    write_jsonl(log, [{"type": "event_msg", "timestamp": ts("2026-09-28 10:05"), "payload": {"type": "task_started"}}], mode="a")
    ingest(store, config)
    cwds = {r[0] for r in store.conn.execute("SELECT cwd FROM activity")}
    assert cwds == {"/w/app"}


def test_sessions_and_titles(env):
    root, config = env
    write_jsonl(
        config.claude_dir / "p" / "s1.jsonl",
        [
            claude_line("2026-09-28 10:00", "/w/app"),
            {"type": "ai-title", "aiTitle": "集計の修正", "sessionId": "s1"},
            claude_line("2026-09-28 10:30", "/w/app"),
        ],
    )
    (config.codex_dir.parent / "session_index.jsonl").write_text('{"id": "c1", "thread_name": "資料"}\n')
    store = Store(config.db_path)
    ingest(store, config)
    row = store.conn.execute("SELECT title, cwd, last_minute - first_minute FROM sessions WHERE session_id = 's1'").fetchone()
    assert row == ("集計の修正", "/w/app", 30)


def test_missing_source_is_a_warning(env):
    root, config = env
    config.codex_dir = root / "nothing"
    stats = ingest(Store(config.db_path), config)
    assert len(stats.warnings) == 1
