import io
from datetime import date

from conftest import claude_line, make_repo, ts, write_jsonl

from worklog.cli import write_csv
from worklog.ingest import ingest
from worklog.report import Adjustment, compute, load_adjustments
from worklog.resolve import Resolver
from worklog.store import Store

DAY = date(2026, 9, 28)


def setup(env, logs: dict[str, list[dict]], clients=None):
    root, config = env
    for name, rows in logs.items():
        write_jsonl(config.claude_dir / "p" / f"{name}.jsonl", rows)
    store = Store(config.db_path)
    ingest(store, config)
    return store, config, Resolver([], clients or [])


def test_parallel_sessions_in_one_project_are_not_double_counted(env):
    root, _ = env
    app = str(make_repo(root / "w" / "app"))
    store, config, resolver = setup(
        env,
        {
            "s1": [claude_line("2026-09-28 10:00", app, "s1"), claude_line("2026-09-28 10:10", app, "s1")],
            "s2": [claude_line("2026-09-28 10:05", app, "s2"), claude_line("2026-09-28 10:20", app, "s2")],
        },
    )
    usage = compute(store, config, resolver, DAY, DAY)
    assert usage.total("app") == 21
    assert usage.union[DAY] == 21


def test_different_projects_are_counted_separately(env):
    root, _ = env
    a = str(make_repo(root / "w" / "a"))
    b = str(make_repo(root / "w" / "b"))
    store, config, resolver = setup(
        env,
        {
            "s1": [claude_line("2026-09-28 10:00", a, "s1"), claude_line("2026-09-28 10:09", a, "s1")],
            "s2": [claude_line("2026-09-28 10:00", b, "s2"), claude_line("2026-09-28 10:09", b, "s2")],
        },
    )
    usage = compute(store, config, resolver, DAY, DAY)
    assert (usage.total("a"), usage.total("b")) == (10, 10)
    assert usage.grand_total() == 20
    assert usage.union[DAY] == 10


def test_client_view_unions_projects_of_the_same_client(env):
    root, _ = env
    a = str(make_repo(root / "w" / "client" / "a"))
    b = str(make_repo(root / "w" / "client" / "b"))
    store, config, resolver = setup(
        env,
        {
            "s1": [claude_line("2026-09-28 10:00", a, "s1"), claude_line("2026-09-28 10:09", a, "s1")],
            "s2": [claude_line("2026-09-28 10:05", b, "s2"), claude_line("2026-09-28 10:14", b, "s2")],
        },
        clients=[("Client", [f"{root}/w/client/*"])],
    )
    usage = compute(store, config, resolver, DAY, DAY, by="client")
    assert usage.total("Client") == 15


def test_events_just_outside_the_range_still_connect(env):
    root, _ = env
    app = str(make_repo(root / "app"))
    store, config, resolver = setup(
        env, {"s1": [claude_line("2026-09-27 23:55", app), claude_line("2026-09-28 00:04", app)]}
    )
    usage = compute(store, config, resolver, DAY, DAY)
    assert usage.total("app") == 5  # 00:00〜00:04


def test_adjustments_and_raw(env):
    root, _ = env
    app = str(make_repo(root / "app"))
    store, config, resolver = setup(env, {"s1": [claude_line("2026-09-28 10:00", app)]})
    adjustments = [Adjustment(DAY, "app", 30, "会議"), Adjustment(date(2026, 9, 1), "app", 99, "範囲外")]
    usage = compute(store, config, resolver, DAY, DAY, adjustments=adjustments)
    assert usage.total("app") == 31
    assert usage.adjusted
    assert compute(store, config, resolver, DAY, DAY).total("app") == 1


def test_load_adjustments(tmp_path):
    path = tmp_path / "adjustments.csv"
    path.write_text("date,project,minutes,note\n2026-09-28,app,-15,重複分\n", encoding="utf-8")
    assert load_adjustments(path) == [Adjustment(DAY, "app", -15, "重複分")]
    path.write_text("date,project,minutes\n2026-09-28,app,abc\n", encoding="utf-8")
    try:
        load_adjustments(path)
    except Exception as e:
        assert ":2:" in str(e)
    else:
        raise AssertionError("書式の誤りを検出していない")


def test_csv_by_grain(env):
    root, _ = env
    app = str(make_repo(root / "app"))
    store, config, resolver = setup(
        env,
        {
            "s1": [claude_line("2026-09-28 10:00", app), claude_line("2026-09-28 10:09", app)],
            "s2": [claude_line("2026-09-29 10:00", app, "s2")],
        },
        clients=[("Client", [app])],
    )
    usage = compute(store, config, resolver, date(2026, 9, 28), date(2026, 9, 29))

    out = io.StringIO()
    write_csv(usage, "day", out)
    assert out.getvalue().splitlines() == [
        "period,client,project,minutes,hours",
        "2026-09-28,Client,app,10,0.17",
        "2026-09-29,Client,app,1,0.02",
    ]
    out = io.StringIO()
    write_csv(usage, "week", out)
    assert out.getvalue().splitlines()[1:] == ["2026-09-28,Client,app,11,0.18"]  # 週の月曜日
    out = io.StringIO()
    write_csv(usage, "month", out)
    assert out.getvalue().splitlines()[1] == "2026-09,Client,app,11,0.18"
