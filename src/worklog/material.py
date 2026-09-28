"""作業内容の要約の素材(セッション・依頼文・コミット)。"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta

from .activity import LocalCalendar, day_start_minute
from .config import Config
from .render import fmt_minutes
from .report import Usage
from .resolve import UNASSIGNED, Resolver
from .store import Store


def build(
    store: Store,
    config: Config,
    resolver: Resolver,
    usage: Usage,
    project_filter: str | None = None,
    max_prompts: int = 8,
    prompt_chars: int = 200,
) -> dict:
    tz = config.tz
    lo = day_start_minute(usage.start, tz)
    hi = day_start_minute(usage.end + timedelta(days=1), tz)
    calendar = LocalCalendar(tz)

    prompts_by_session = defaultdict(list)
    for p in store.prompts_between(lo, hi):
        prompts_by_session[(p.source, p.session_id)].append(p)

    projects: dict[str, dict] = {}

    def entry(cwd: str | None) -> dict | None:
        project = resolver.project(cwd or "")
        if project_filter and project.name != project_filter:
            return None
        if project.name not in projects:
            projects[project.name] = {
                "name": project.name,
                "client": project.client,
                "path": None if project.key == UNASSIGNED else project.key,
                "minutes": usage.total(project.name) if usage.by == "repo" else None,
                "sessions": [],
                "commits": [],
            }
        return projects[project.name]

    for s in store.sessions_between(lo, hi):
        target = entry(s.cwd)
        if target is None:
            continue
        prompts = _unique(prompts_by_session.get((s.source, s.session_id), []))
        target["sessions"].append(
            {
                "source": s.source,
                "title": s.title,
                "start": _iso(calendar, max(s.first_minute, lo)),
                "end": _iso(calendar, min(s.last_minute, hi - 1)),
                "prompt_count": len(prompts),
                "prompts": [
                    {"time": _iso(calendar, p.minute), "text": p.text[:prompt_chars]} for p in prompts[:max_prompts]
                ],
            }
        )

    since = datetime.combine(usage.start, datetime.min.time())
    until = datetime.combine(usage.end + timedelta(days=1), datetime.min.time())
    since = since.replace(tzinfo=tz) if tz else since.astimezone()
    until = until.replace(tzinfo=tz) if tz else until.astimezone()
    for p in projects.values():
        if p["path"]:
            p["commits"] = git_commits(p["path"], since, until)
        if p["minutes"] is None:
            p.pop("minutes")

    ordered = sorted(projects.values(), key=lambda p: (p["name"] == UNASSIGNED, -(p.get("minutes") or 0), p["name"]))
    return {
        "from": usage.start.isoformat(),
        "to": usage.end.isoformat(),
        "gap_minutes": config.gap_minutes,
        "projects": ordered,
    }


def _unique(prompts: list) -> list:
    """同じ依頼文の重複(再送・キューからの再投入)は最初の 1 件だけにする。"""
    seen, result = set(), []
    for p in prompts:
        if p.text not in seen:
            seen.add(p.text)
            result.append(p)
    return result


def _iso(calendar: LocalCalendar, minute: int) -> str:
    return calendar.local(minute).isoformat(timespec="minutes")


def git_commits(repo: str, since: datetime, until: datetime) -> list[dict]:
    """期間内の自分(リポジトリの user.email)のコミット。失敗したら空。"""
    try:
        email = subprocess.run(
            ["git", "-C", repo, "config", "user.email"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        args = [
            "git", "-C", repo, "log", "--all", "--no-merges",
            f"--since={since.isoformat()}", f"--until={until.isoformat()}",
            "--date=iso-strict", "--format=%h%x09%ad%x09%s",
        ]
        if email:
            args.append(f"--author={email}")
        out = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "time": parts[1], "subject": parts[2]})
    return commits


def to_markdown(material: dict) -> str:
    lines = [f"# 作業内容の素材 {material['from']} 〜 {material['to']}", ""]
    for p in material["projects"]:
        minutes = p.get("minutes")
        head = f"## {p['name']}({p['client']})"
        if minutes is not None:
            head += f" {fmt_minutes(minutes)}"
        lines += [head, ""]
        for s in p["sessions"]:
            lines.append(f"- {s['start'][5:16].replace('T', ' ')}〜{s['end'][11:16]} [{s['source']}] {s['title'] or '(タイトルなし)'}")
            for pr in s["prompts"]:
                lines.append(f"  - {pr['text'].splitlines()[0]}")
            rest = s["prompt_count"] - len(s["prompts"])
            if rest > 0:
                lines.append(f"  - ほか {rest} 件")
        if p["commits"]:
            lines.append("- コミット")
            for c in p["commits"]:
                lines.append(f"  - {c['hash']} {c['subject']}")
        lines.append("")
    return "\n".join(lines)
