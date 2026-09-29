"""worklog コマンド。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import material as material_mod
from .activity import LocalCalendar, day_start_minute
from .config import TEMPLATE, Config, ConfigError, config_dir, load_config
from .ingest import ingest
from .render import Style, fmt_day, fmt_minutes, month_rows, render_day, render_rows, week_rows
from .report import AdjustmentError, Usage, compute, daterange, load_adjustments
from .resolve import UNASSIGNED, Resolver
from .store import Store


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["day", *argv]
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        return args.func(args, config)
    except (ConfigError, AdjustmentError, ValueError) as e:
        print(f"worklog: {e}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=_path, help="設定ファイル(既定 ~/.config/worklog/config.toml)")
    common.add_argument(
        "--by", choices=["project", "repo", "client"], default="project", help="集計単位(既定 project)"
    )
    common.add_argument("--raw", action="store_true", help="補正ファイルを反映しない")
    common.add_argument("--no-ingest", action="store_true", help="実行前の取り込みを省く")
    common.add_argument("--no-color", action="store_true", help="色を付けない")

    parser = argparse.ArgumentParser(
        prog="worklog", description="Claude Code と Codex のログから、プロジェクトごとの稼働時間を表示する"
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("day", parents=[common], help="1 日のプロジェクト別の稼働")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD / today / yesterday(既定 today)")
    p.set_defaults(func=cmd_day)

    p = sub.add_parser("week", parents=[common], help="週(月曜始まり)の日別の稼働")
    p.add_argument("date", nargs="?", help="週に含まれる日 YYYY-MM-DD(既定 today)")
    p.set_defaults(func=cmd_week)

    p = sub.add_parser("month", parents=[common], help="月の週別の稼働")
    p.add_argument("month", nargs="?", help="YYYY-MM(既定 今月)")
    p.set_defaults(func=cmd_month)

    p = sub.add_parser("export", parents=[common], help="稼働時間を CSV で出力")
    p.add_argument("--from", dest="start", help="開始日 YYYY-MM-DD(既定 今月 1 日)")
    p.add_argument("--to", dest="end", help="終了日 YYYY-MM-DD(既定 今日)")
    p.add_argument("--grain", choices=["day", "week", "month"], default="day")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("material", parents=[common], help="作業内容の要約の素材")
    p.add_argument("--date", help="1 日分 YYYY-MM-DD")
    p.add_argument("--from", dest="start", help="開始日 YYYY-MM-DD")
    p.add_argument("--to", dest="end", help="終了日 YYYY-MM-DD")
    p.add_argument("--project", help="プロジェクト名で絞る")
    p.add_argument("--max-prompts", type=int, default=8, help="セッションごとの依頼文の上限(既定 8)")
    p.add_argument("--prompt-chars", type=int, default=200, help="依頼文ごとの文字数の上限(既定 200)")
    p.add_argument("--json", action="store_true", help="JSON で出力")
    p.set_defaults(func=cmd_material)

    p = sub.add_parser("projects", parents=[common], help="cwd → プロジェクト → 案件 の判定結果")
    p.add_argument("--from", dest="start", help="開始日(既定 全期間)")
    p.add_argument("--to", dest="end", help="終了日(既定 今日)")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("ingest", parents=[common], help="ログの取り込みだけを行う")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("config", parents=[common], help="設定の場所と内容を表示")
    p.add_argument("--init", action="store_true", help="設定ファイルのひな形を書き出す")
    p.set_defaults(func=cmd_config)
    return parser


def _path(value: str) -> Path:
    return Path(value).expanduser()


# 共通処理


def today(config: Config) -> date:
    return datetime.now(config.tz).date() if config.tz else datetime.now().date()


def parse_day(value: str | None, config: Config) -> date:
    if value in (None, "today"):
        return today(config)
    if value == "yesterday":
        return today(config) - timedelta(days=1)
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"日付 {value!r} は YYYY-MM-DD で指定してください") from e


def open_store(args, config: Config) -> Store:
    store = Store(config.db_path)
    if not args.no_ingest:
        stats = ingest(store, config)
        for w in stats.warnings:
            print(f"worklog: {w}", file=sys.stderr)
    return store


def usage_for(args, config: Config, store: Store, start: date, end: date, by: str | None = None) -> Usage:
    resolver = Resolver(config.aliases, config.clients, config.roots, config.projects)
    adjustments = [] if args.raw else load_adjustments(config.adjustments_path)
    return compute(store, config, resolver, start, end, by or args.by, adjustments)


def style_for(args, units: list[str]) -> Style:
    color = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
    return Style.for_units(units, color)


def bar_width(default: int, name_width: int = 28, extra: int = 12) -> int:
    columns = shutil.get_terminal_size((100, 24)).columns
    return max(10, min(default, columns - name_width - extra))


# コマンド


def cmd_day(args, config: Config) -> int:
    day = parse_day(args.date, config)
    store = open_store(args, config)
    usage = usage_for(args, config, store, day, day)
    style = style_for(args, usage.units())
    print(render_day(usage, config.gap_minutes, style, LocalCalendar(config.tz), bar_width(24)))
    return 0


def cmd_week(args, config: Config) -> int:
    day = parse_day(args.date, config)
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    store = open_store(args, config)
    usage = usage_for(args, config, store, start, end)
    title = f"{fmt_day(start)} 〜 {fmt_day(end)}"
    print(render_rows(title, week_rows(start), usage, config.gap_minutes, style_for(args, usage.units()), bar_width(40, 9)))
    return 0


def cmd_month(args, config: Config) -> int:
    first = _parse_month(args.month, config)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    store = open_store(args, config)
    usage = usage_for(args, config, store, first, last)
    title = f"{first:%Y-%m}"
    print(render_rows(title, month_rows(first, last), usage, config.gap_minutes, style_for(args, usage.units()), bar_width(40, 11)))
    return 0


def _parse_month(value: str | None, config: Config) -> date:
    if value is None:
        return today(config).replace(day=1)
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError as e:
        raise ValueError(f"月 {value!r} は YYYY-MM で指定してください") from e


def cmd_export(args, config: Config) -> int:
    start = parse_day(args.start, config) if args.start else today(config).replace(day=1)
    end = parse_day(args.end, config) if args.end else today(config)
    if end < start:
        raise ValueError("--to は --from 以降の日付にしてください")
    store = open_store(args, config)
    usage = usage_for(args, config, store, start, end)
    write_csv(usage, args.grain, sys.stdout)
    return 0


def period_of(day: date, grain: str) -> str:
    if grain == "week":
        return (day - timedelta(days=day.weekday())).isoformat()
    if grain == "month":
        return f"{day:%Y-%m}"
    return day.isoformat()


def write_csv(usage: Usage, grain: str, out) -> None:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["period", "client", "project", "repo", "minutes", "hours"])
    periods: dict[str, list[date]] = {}
    for d in daterange(usage.start, usage.end):
        periods.setdefault(period_of(d, grain), []).append(d)
    for period, days in periods.items():
        for unit in usage.units():
            minutes = sum(usage.days[unit][d] for d in days)
            if minutes == 0:
                continue
            client = usage.clients.get(unit, "")
            project = "" if usage.by == "client" else usage.projects.get(unit, unit)
            repo = unit if usage.by == "repo" else ""
            writer.writerow([period, client, project, repo, minutes, f"{minutes / 60:.2f}"])


def cmd_material(args, config: Config) -> int:
    if args.date:
        start = end = parse_day(args.date, config)
    else:
        start = parse_day(args.start, config) if args.start else today(config)
        end = parse_day(args.end, config) if args.end else today(config)
    if end < start:
        raise ValueError("--to は --from 以降の日付にしてください")
    store = open_store(args, config)
    resolver = Resolver(config.aliases, config.clients, config.roots, config.projects)
    adjustments = [] if args.raw else load_adjustments(config.adjustments_path)
    usage = compute(store, config, resolver, start, end, "project", adjustments)
    data = material_mod.build(store, config, resolver, usage, args.project, args.max_prompts, args.prompt_chars)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(material_mod.to_markdown(data))
    return 0


def cmd_projects(args, config: Config) -> int:
    store = open_store(args, config)
    resolver = Resolver(config.aliases, config.clients, config.roots, config.projects)
    resolver.learn_names(store.all_cwds())
    lo = day_start_minute(parse_day(args.start, config), config.tz) if args.start else 0
    end = parse_day(args.end, config) if args.end else today(config)
    hi = day_start_minute(end + timedelta(days=1), config.tz)

    tree: dict[tuple[str, str], dict[tuple[str, str], list[tuple[str, int]]]] = {}
    for cwd, minutes in store.activity_by_cwd(lo, hi, config.include_automated):
        p = resolver.project(cwd)
        tree.setdefault((p.client, p.name), {}).setdefault((p.repo, p.key), []).append((cwd, minutes))
    for (client, name), repos in sorted(tree.items()):
        print(f"{client} / {name}")
        for (repo, key), cwds in sorted(repos.items()):
            total = sum(m for _, m in cwds)
            where = "" if key == UNASSIGNED else f"  {key}"
            print(f"    {repo}{where}  (イベントのある分 {fmt_minutes(total)})")
            for cwd, minutes in sorted(cwds, key=lambda c: -c[1]):
                print(f"        {cwd or '(cwd なし)'}  {fmt_minutes(minutes)}")
    return 0


def cmd_ingest(args, config: Config) -> int:
    store = Store(config.db_path)
    stats = ingest(store, config)
    for w in stats.warnings:
        print(f"worklog: {w}", file=sys.stderr)
    print(f"取り込み: ファイル {stats.files} 件・行 {stats.lines} 件(読み飛ばし {stats.skipped_lines} 件)")
    print(f"保存先: {config.db_path}")
    return 0


def cmd_config(args, config: Config) -> int:
    path = config.config_path or args.config or config_dir() / "config.toml"
    if args.init:
        if path.exists():
            print(f"worklog: {path} はすでにあります", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE, encoding="utf-8")
        print(f"書き出しました: {path}")
        return 0
    print(f"設定ファイル: {path}{'' if path.exists() else '(なし。既定値で動作)'}")
    print(f"補正ファイル: {config.adjustments_path}")
    print(f"保存先: {config.db_path}")
    print(f"タイムゾーン: {config.timezone or 'システムのローカル'}")
    print(f"しきい値: {config.gap_minutes} 分")
    print(f"自動実行: {'数える' if config.include_automated else '数えない'}")
    print(f"Claude Code のログ: {config.claude_dir}")
    print(f"Codex のログ: {config.codex_dir}")
    for root in config.roots:
        print(f"プロジェクトの親: {root}")
    for old, new in config.aliases:
        print(f"別名: {old} → {new}")
    for name, patterns in config.projects:
        print(f"プロジェクト: {name} ← {', '.join(patterns)}")
    for name, patterns in config.clients:
        print(f"案件: {name} ← {', '.join(patterns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
