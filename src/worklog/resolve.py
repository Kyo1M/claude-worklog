"""cwd → リポジトリ → プロジェクト → 案件 の判定。"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

UNASSIGNED = "(未分類)"
NO_CLIENT = "(案件未設定)"


@dataclass(frozen=True)
class Project:
    key: str  # リポジトリの絶対パス。未分類は UNASSIGNED
    repo: str  # リポジトリの表示名
    name: str  # プロジェクト名。[projects] に当たらなければリポジトリの表示名
    client: str


class Resolver:
    def __init__(
        self,
        aliases: list[tuple[str, str]],
        clients: list[tuple[str, list[str]]],
        roots: list[str] | None = None,
        projects: list[tuple[str, list[str]]] | None = None,
    ):
        # 長いパターンを先に当てる
        self.aliases = sorted(((_strip_star(a), _strip_star(b)) for a, b in aliases), key=lambda x: -len(x[0]))
        self.clients = clients
        self.roots = sorted((_strip_star(r) for r in roots or []), key=len, reverse=True)
        self._repo_cache: dict[str, str | None] = {}
        self.projects = projects or []
        self._names: dict[str, str] = {}
        self._group_clients: dict[str, str] = {}

    def apply_alias(self, cwd: str) -> str:
        """書き換えが止まるまで繰り返す(旧パス → 中間のパス → 現在のパス をたどれるように)。"""
        for _ in range(10):
            for old, new in self.aliases:
                if cwd == old or cwd.startswith(old + "/"):
                    cwd = new + cwd[len(old):]
                    break
            else:
                return cwd
        return cwd

    def repo(self, cwd: str) -> str | None:
        if cwd not in self._repo_cache:
            self._repo_cache[cwd] = self._resolve(cwd) if cwd else None
        return self._repo_cache[cwd]

    def _resolve(self, cwd: str) -> str | None:
        path = self.apply_alias(cwd)
        repo = find_repo(path)
        if repo:
            moved = self.apply_alias(repo)  # worktree が旧パスの本体を指している場合
            return repo if moved == repo else find_repo(moved) or moved
        return self._root_project(path)

    def _root_project(self, path: str) -> str | None:
        """git リポジトリでないときは、roots の直下のディレクトリをプロジェクトとみなす。"""
        for root in self.roots:
            if path.startswith(root + "/"):
                return f"{root}/{path[len(root) + 1:].split('/')[0]}"
        return None

    def client(self, repo: str | None) -> str:
        if repo is None:
            return UNASSIGNED
        for name, patterns in self.clients:
            if any(fnmatchcase(repo, p) for p in patterns):
                return name
        return NO_CLIENT

    def learn_names(self, cwds: Iterable[str]) -> None:
        """表示名を決める。同じディレクトリ名が複数あれば「親/名前」にする。"""
        repos = {r for r in (self.repo(c) for c in cwds) if r}
        by_base: dict[str, list[str]] = defaultdict(list)
        for r in repos:
            by_base[os.path.basename(r)].append(r)
        for base, rs in by_base.items():
            for r in rs:
                self._names[r] = base if len(rs) == 1 else f"{os.path.basename(os.path.dirname(r))}/{base}"
        self._group_clients.clear()

    def group(self, repo: str) -> str | None:
        """[projects] で最初に当たったプロジェクト名。"""
        for name, patterns in self.projects:
            if any(fnmatchcase(repo, p) for p in patterns):
                return name
        return None

    def repo_name(self, repo: str) -> str:
        return self._names.get(repo) or os.path.basename(repo)

    def project_client(self, repo: str) -> str:
        """案件はプロジェクトの単位で決める。所属リポジトリで案件が分かれたら [clients] の上にあるものを採る。"""
        group = self.group(repo)
        if group is None:
            return self.client(repo)
        if group not in self._group_clients:
            members = [r for r in self._names if self.group(r) == group] or [repo]
            self._group_clients[group] = next(
                (name for name, patterns in self.clients if any(fnmatchcase(r, p) for r in members for p in patterns)),
                NO_CLIENT,
            )
        return self._group_clients[group]

    def describe_name(self, name: str) -> tuple[str, str]:
        """補正ファイルに書かれた名前(リポジトリ名かプロジェクト名)から (プロジェクト名, 案件) を引く。"""
        for repo, known in self._names.items():
            if known == name:
                return self.group(repo) or known, self.project_client(repo)
        for repo in self._names:
            if self.group(repo) == name:
                return name, self.project_client(repo)
        return name, NO_CLIENT

    def project(self, cwd: str) -> Project:
        repo = self.repo(cwd)
        if repo is None:
            return Project(UNASSIGNED, UNASSIGNED, UNASSIGNED, UNASSIGNED)
        repo_name = self.repo_name(repo)
        return Project(repo, repo_name, self.group(repo) or repo_name, self.project_client(repo))


def _strip_star(path: str) -> str:
    if path.endswith("/*"):
        path = path[:-2]
    return path.rstrip("/") or "/"


def find_repo(path: str) -> str | None:
    """path から親へたどって git リポジトリを探す。path 自体が消えていても祖先で判定する。"""
    p = Path(path)
    if not p.is_absolute():
        return None
    for d in (p, *p.parents):
        git = d / ".git"
        if git.is_dir():
            return str(d)
        if git.is_file():
            return _worktree_main(git) or str(d)
    return None


def _worktree_main(git_file: Path) -> str | None:
    """git worktree の `.git` ファイルから本体のリポジトリを得る。"""
    try:
        line = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = line[len("gitdir:"):].strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(git_file.parent, gitdir))
    marker = "/.git/worktrees/"
    if marker in gitdir:
        return gitdir.split(marker)[0]
    return None
