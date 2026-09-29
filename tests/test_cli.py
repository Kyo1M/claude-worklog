import json

from conftest import claude_line, claude_prompt, make_repo, write_jsonl

from worklog.cli import main


def write_config(root, config):
    path = root / "config.toml"
    path.write_text(
        f"""
timezone = "Asia/Tokyo"
db = "{config.db_path}"
adjustments = "{config.adjustments_path}"
[sources]
claude = "{config.claude_dir}"
codex = "{config.codex_dir}"
[clients]
"Client" = ["{root}/w/*"]
""",
        encoding="utf-8",
    )
    return str(path)


def seed(env):
    root, config = env
    app = str(make_repo(root / "w" / "app"))
    write_jsonl(
        config.claude_dir / "p" / "s1.jsonl",
        [
            claude_prompt("2026-09-28 10:00", app, "集計を直して"),
            {"type": "ai-title", "aiTitle": "集計の修正", "sessionId": "s1"},
            claude_prompt("2026-09-28 10:05", app, "集計を直して"),
            claude_line("2026-09-28 10:30", app),
            claude_line("2026-09-28 10:40", app),
        ],
    )
    return write_config(root, config)


def test_day(env, capsys):
    cfg = seed(env)
    assert main(["day", "2026-09-28", "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "app" in out and "17m" in out  # 10:00〜10:05 の 6 分 + 10:30〜10:40 の 11 分
    assert "2026-09-28 (月)" in out


def test_default_command_is_day(env, capsys):
    cfg = seed(env)
    assert main(["--config", cfg]) == 0
    assert "しきい値 15 分" in capsys.readouterr().out


def test_week_and_month_by_client(env, capsys):
    cfg = seed(env)
    assert main(["week", "2026-09-30", "--config", cfg, "--by", "client"]) == 0
    assert "案件別" in capsys.readouterr().out
    assert main(["month", "2026-09", "--config", cfg]) == 0
    assert "09/28〜09/30" in capsys.readouterr().out


def test_export(env, capsys):
    cfg = seed(env)
    assert main(["export", "--from", "2026-09-01", "--to", "2026-09-30", "--grain", "month", "--config", cfg]) == 0
    assert capsys.readouterr().out.splitlines()[1] == "2026-09,Client,app,,17,0.28"


def test_material_json(env, capsys):
    cfg = seed(env)
    assert main(["material", "--date", "2026-09-28", "--json", "--config", cfg]) == 0
    data = json.loads(capsys.readouterr().out)
    [project] = data["projects"]
    assert project["name"] == "app" and project["minutes"] == 17
    [session] = project["sessions"]
    assert session["title"] == "集計の修正"
    assert [p["text"] for p in session["prompts"]] == ["集計を直して"]
    assert session["start"].startswith("2026-09-28T10:00")


def test_projects_and_config(env, capsys):
    cfg = seed(env)
    assert main(["projects", "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "Client / app" in out and "    app  " in out
    assert main(["config", "--config", cfg]) == 0
    assert "Asia/Tokyo" in capsys.readouterr().out


def test_bad_date_is_an_error(env, capsys):
    cfg = seed(env)
    assert main(["day", "28/09", "--config", cfg]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_by_repo_heading(env, capsys):
    cfg = seed(env)
    assert main(["week", "2026-09-28", "--by", "repo", "--config", cfg]) == 0
    assert "リポジトリ別" in capsys.readouterr().out
