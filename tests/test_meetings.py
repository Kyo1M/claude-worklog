from datetime import date, time
from pathlib import Path

from conftest import claude_line, make_repo, write_jsonl

from worklog.ingest import ingest
from worklog.meetings import find_meetings, read_frontmatter
from worklog.render import Style, footer
from worklog.report import compute
from worklog.resolve import Resolver
from worklog.store import Store

DAY = date(2026, 9, 28)


def write_minutes(repo: Path, name: str, frontmatter: str, folder: str = "docs/minutes") -> Path:
    path = repo / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n# 議事録\n", encoding="utf-8")
    return path


def setup(env, logs: dict[str, list[dict]], projects=None):
    root, config = env
    for name, rows in logs.items():
        write_jsonl(config.claude_dir / "p" / f"{name}.jsonl", rows)
    store = Store(config.db_path)
    ingest(store, config)
    return store, config, Resolver([], [], projects=projects)


def test_frontmatter_reads_top_level_keys_only(tmp_path):
    path = tmp_path / "m.md"
    path.write_text(
        '---\ntitle: 定例（9/28）\ndate: "2026-09-28"\nstart: \'14:00\'\nend: 15:30  # 延長\nattendees:\n  - start: x\n---\nstart: 99:99\n',
        encoding="utf-8",
    )
    assert read_frontmatter(path) == {"title": "定例（9/28）", "date": "2026-09-28", "start": "14:00", "end": "15:30", "attendees": ""}


def test_file_without_frontmatter_is_ignored(tmp_path):
    repo = make_repo(tmp_path / "app")
    (repo / "docs" / "minutes").mkdir(parents=True)
    (repo / "docs" / "minutes" / "old.md").write_text("# 議事録\n\n| 日時 | 2026-09-28 |\n", encoding="utf-8")
    assert find_meetings([str(repo)], ["docs/minutes/**/*.md"], DAY, DAY) == ([], [])


def test_meetings_are_filtered_by_date_and_invalid_times_warn(tmp_path):
    repo = make_repo(tmp_path / "app")
    write_minutes(repo, "a.md", 'date: "2026-09-28"\nstart: "14:00"\nend: "15:00"')
    write_minutes(repo, "sub/b.md", 'date: "2026-09-28"')
    write_minutes(repo, "c.md", 'date: "2026-09-27"\nstart: "14:00"\nend: "15:00"')
    write_minutes(repo, "d.md", 'date: "2026-09-28"\nstart: "15:00"\nend: "14:00"')
    write_minutes(repo, "f.md", 'date: "2026-09-27"\nstart: "9 時"\nend: "10:00"')  # 期間外は警告しない
    write_minutes(repo, "_drafts/e.md", 'date: "2026-09-28"\nstart: "14:00"\nend: "15:00"')
    meetings, warnings = find_meetings([str(repo)], ["docs/minutes/**/*.md"], DAY, DAY)
    assert sorted((Path(m.path).name, m.start) for m in meetings) == [("a.md", time(14)), ("b.md", None)]
    assert len(warnings) == 1 and "d.md" in warnings[0]


def test_meeting_time_is_added_to_project_without_double_counting(env):
    root, _ = env
    app = make_repo(root / "w" / "app")
    # 14:50〜15:05 に AI の稼働があり、会議 14:00〜15:00 と 10 分重なる
    store, config, resolver = setup(
        env, {"s1": [claude_line("2026-09-28 14:50", str(app)), claude_line("2026-09-28 15:05", str(app))]}
    )
    write_minutes(app, "20260928_sync.md", 'date: "2026-09-28"\nstart: "14:00"\nend: "15:00"')
    usage = compute(store, config, resolver, DAY, DAY)
    assert usage.total("app") == 66  # 14:00〜15:05
    assert usage.meetings == 1
    assert usage.union[DAY] == 66


def test_meeting_is_counted_in_the_project_of_its_repo(env):
    root, _ = env
    a = make_repo(root / "w" / "client" / "a")
    b = make_repo(root / "w" / "client" / "b")
    store, config, resolver = setup(
        env,
        {"s1": [claude_line("2026-09-28 10:00", str(a))], "s2": [claude_line("2026-09-28 10:00", str(b))]},
        projects=[("分析", [str(root / "w" / "client" / "*")])],
    )
    write_minutes(b, "m.md", 'date: "2026-09-28"\nstart: "13:00"\nend: "13:30"')
    usage = compute(store, config, resolver, DAY, DAY)
    assert usage.total("分析") == 1 + 30
    by_repo = compute(store, config, resolver, DAY, DAY, by="repo")
    assert (by_repo.total("a"), by_repo.total("b")) == (1, 31)


def test_untimed_meetings_are_reported_but_not_counted(env):
    root, _ = env
    app = make_repo(root / "w" / "app")
    store, config, resolver = setup(env, {"s1": [claude_line("2026-09-28 10:00", str(app))]})
    write_minutes(app, "m.md", 'date: "2026-09-28"')
    usage = compute(store, config, resolver, DAY, DAY)
    assert usage.total("app") == 1
    assert (usage.meetings, usage.untimed_meetings) == (0, 1)
    assert any("1 件は数えていません" in line for line in footer(usage, Style.for_units([], False)))


def test_minutes_setting_can_turn_meetings_off(env):
    root, _ = env
    app = make_repo(root / "w" / "app")
    store, config, resolver = setup(env, {"s1": [claude_line("2026-09-28 10:00", str(app))]})
    write_minutes(app, "m.md", 'date: "2026-09-28"\nstart: "13:00"\nend: "14:00"')
    config.minutes = []
    assert compute(store, config, resolver, DAY, DAY).total("app") == 1
