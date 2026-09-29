import json
import sqlite3

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


def test_missing_sources_warn_only_when_both_are_missing(env):
    root, config = env
    config.codex_dir = root / "nothing"
    assert ingest(Store(config.db_path), config).warnings == []
    config.claude_dir = root / "nothing-either"
    assert len(ingest(Store(config.db_path), config).warnings) == 1


def test_minute_with_manual_and_automated_counts_as_manual(env):
    root, config = env
    write_jsonl(config.claude_dir / "p" / "auto.jsonl", [claude_line("2026-09-28 10:00", "/w", "a", entrypoint="sdk-cli")])
    store = Store(config.db_path)
    ingest(store, config)
    assert store.conn.execute("SELECT automated FROM activity").fetchall() == [(1,)]
    write_jsonl(config.claude_dir / "p" / "manual.jsonl", [claude_line("2026-09-28 10:00", "/w", "m", entrypoint="cli")])
    ingest(store, config)
    assert store.conn.execute("SELECT automated FROM activity").fetchall() == [(0,)]


def test_old_database_is_upgraded_and_read_again(env):
    root, config = env
    config.db_path.parent.mkdir(parents=True)
    old = sqlite3.connect(config.db_path)
    old.executescript(
        """
        CREATE TABLE activity (minute INTEGER NOT NULL, source TEXT NOT NULL, cwd TEXT NOT NULL,
            PRIMARY KEY (minute, source, cwd)) WITHOUT ROWID;
        CREATE TABLE sessions (source TEXT NOT NULL, session_id TEXT NOT NULL, title TEXT, cwd TEXT,
            first_minute INTEGER, last_minute INTEGER, PRIMARY KEY (source, session_id));
        CREATE TABLE files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, offset INTEGER NOT NULL, state TEXT NOT NULL);
        INSERT INTO activity VALUES (1, 'claude', '/w/auto'), (2, 'claude', '/w/gone');
        INSERT INTO sessions VALUES ('codex', 'g1', NULL, '/w', 1, 1);
        """
    )
    log = config.claude_dir / "p" / "auto.jsonl"
    write_jsonl(log, [{"type": "user", "timestamp": "1970-01-01T00:01:00Z", "cwd": "/w/auto", "sessionId": "a", "entrypoint": "sdk-cli"}])
    old.execute("INSERT INTO files VALUES (?, 1, 999, '{}')", (str(log),))
    old.commit()
    old.close()

    store = Store(config.db_path)
    ingest(store, config)
    rows = dict(store.conn.execute("SELECT cwd, automated FROM activity"))
    assert rows == {"/w/auto": 1, "/w/gone": 2}  # 読み直せたものは判定し、ログの無いものは対話として残す
    assert [r[0] for r in store.activity_between(0, 10)] == [2]
    assert store.conn.execute("SELECT COUNT(*) FROM sessions WHERE source = 'codex'").fetchone()[0] == 0
