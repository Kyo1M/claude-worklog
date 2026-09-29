"""設定ファイルの読み込みと既定値。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    pass


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "worklog"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "worklog"


def expand(path: str) -> str:
    """`~` を展開し、末尾の `/` を落とす(`*` はそのまま残す)。"""
    expanded = os.path.expanduser(path)
    return expanded.rstrip("/") or "/"


@dataclass
class Config:
    claude_dir: Path
    codex_dir: Path
    db_path: Path
    adjustments_path: Path
    config_path: Path | None = None
    timezone: str | None = None
    gap_minutes: int = 15
    include_automated: bool = False  # claude -p・codex exec などの自動実行も数えるか
    aliases: list[tuple[str, str]] = field(default_factory=list)
    clients: list[tuple[str, list[str]]] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    projects: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def tz(self) -> tzinfo | None:
        """None はシステムのローカルタイムゾーンを表す。"""
        if self.timezone is None:
            return None
        return ZoneInfo(self.timezone)

    @property
    def codex_index(self) -> Path:
        return self.codex_dir.parent / "session_index.jsonl"


def default_config() -> Config:
    return Config(
        claude_dir=Path(expand("~/.claude/projects")),
        codex_dir=Path(expand("~/.codex/sessions")),
        db_path=data_dir() / "worklog.db",
        adjustments_path=config_dir() / "adjustments.csv",
    )


def load_config(path: Path | None = None) -> Config:
    config = default_config()
    path = path or Path(os.environ.get("WORKLOG_CONFIG") or config_dir() / "config.toml")
    if not path.exists():
        return config
    config.config_path = path
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e

    if "timezone" in raw:
        try:
            ZoneInfo(raw["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError(f"{path}: timezone {raw['timezone']!r} が見つかりません") from e
        config.timezone = raw["timezone"]
    if "gap_minutes" in raw:
        gap = raw["gap_minutes"]
        if not isinstance(gap, int) or gap < 0:
            raise ConfigError(f"{path}: gap_minutes は 0 以上の整数にしてください")
        config.gap_minutes = gap
    if "include_automated" in raw:
        if not isinstance(raw["include_automated"], bool):
            raise ConfigError(f"{path}: include_automated は true か false にしてください")
        config.include_automated = raw["include_automated"]

    sources = raw.get("sources", {})
    if "claude" in sources:
        config.claude_dir = Path(expand(sources["claude"]))
    if "codex" in sources:
        config.codex_dir = Path(expand(sources["codex"]))
    if "db" in raw:
        config.db_path = Path(expand(raw["db"]))
    if "adjustments" in raw:
        config.adjustments_path = Path(expand(raw["adjustments"]))

    roots = raw.get("roots", [])
    if isinstance(roots, str):
        roots = [roots]
    config.roots = [expand(r) for r in roots]
    config.aliases = [(expand(k), expand(v)) for k, v in raw.get("aliases", {}).items()]
    config.projects = _groups(raw.get("projects", {}))
    config.clients = _groups(raw.get("clients", {}))
    return config


def _groups(table: dict) -> list[tuple[str, list[str]]]:
    """{名前: パターン or [パターン]} を書いた順のリストにする。"""
    groups = []
    for name, patterns in table.items():
        if isinstance(patterns, str):
            patterns = [patterns]
        groups.append((name, [expand(p) for p in patterns]))
    return groups


TEMPLATE = """\
# worklog の設定ファイル
# timezone = "Asia/Tokyo"   # 省略時はシステムのローカル
gap_minutes = 15            # イベントの間隔がこれ以下(分)なら稼働をつなげる
include_automated = false   # claude -p・codex exec などの自動実行も稼働に数えるなら true
# roots = ["~/Developer"]   # git リポジトリでないときは、この直下のディレクトリをプロジェクトとみなす

# [sources]
# claude = "~/.claude/projects"
# codex  = "~/.codex/sessions"

# 旧パス → 現在のパス(前方一致で置き換える。末尾の /* は省略可)
[aliases]
# "~/Documents/Develop/*" = "~/Developer/*"

# リポジトリ → プロジェクト(glob。上から順に最初に当たったもの。当たらなければリポジトリ名)
[projects]
# "分析基盤" = ["~/Developer/client-a/etl", "~/Developer/client-a/dashboard"]

# リポジトリ → 案件(glob。上から順に最初に当たったもの)
[clients]
# "案件A" = ["~/Developer/client-a/*"]
# "個人"  = ["~/Developer/*"]
"""
