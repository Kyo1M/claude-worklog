from conftest import make_repo

from worklog.resolve import NO_CLIENT, UNASSIGNED, Resolver, find_repo


def test_subdirectory_resolves_to_repo_root(tmp_path):
    repo = make_repo(tmp_path / "work" / "app")
    (repo / "docs").mkdir()
    assert find_repo(str(repo / "docs")) == str(repo)


def test_vanished_directory_resolves_by_ancestor(tmp_path):
    repo = make_repo(tmp_path / "app")
    assert find_repo(str(repo / "data" / "output" / "gone")) == str(repo)


def test_worktree_resolves_to_main_repo(tmp_path):
    main = make_repo(tmp_path / "main")
    worktree = tmp_path / "workspaces" / "feature"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {main}/.git/worktrees/feature\n")
    assert find_repo(str(worktree)) == str(main)


def test_no_repo_is_unassigned(tmp_path):
    resolver = Resolver([], [])
    assert resolver.project(str(tmp_path)).name == UNASSIGNED
    assert resolver.project("").name == UNASSIGNED


def test_alias_is_prefix_replacement_on_path_boundary(tmp_path):
    new = make_repo(tmp_path / "Developer" / "app")
    make_repo(tmp_path / "Developer" / "app-other")
    old_root = tmp_path / "Documents" / "Develop"
    resolver = Resolver([(f"{old_root}/*", f"{tmp_path}/Developer/*")], [])
    assert resolver.repo(f"{old_root}/app/docs") == str(new)
    assert resolver.repo(f"{old_root}/app-other") == str(tmp_path / "Developer" / "app-other")


def test_longer_alias_wins(tmp_path):
    moved = make_repo(tmp_path / "Developer" / "client" / "app")
    make_repo(tmp_path / "Developer" / "app")
    resolver = Resolver(
        [
            (f"{tmp_path}/Old/*", f"{tmp_path}/Developer/*"),
            (f"{tmp_path}/Old/app", f"{tmp_path}/Developer/client/app"),
        ],
        [],
    )
    assert resolver.repo(f"{tmp_path}/Old/app") == str(moved)


def test_clients_first_match_and_default(tmp_path):
    a = make_repo(tmp_path / "Developer" / "client" / "app")
    b = make_repo(tmp_path / "Developer" / "hobby")
    c = make_repo(tmp_path / "elsewhere")
    resolver = Resolver(
        [], [("Client", [f"{tmp_path}/Developer/client/*"]), ("Personal", [f"{tmp_path}/Developer/*"])]
    )
    assert resolver.project(str(a)).client == "Client"
    assert resolver.project(str(b)).client == "Personal"
    assert resolver.project(str(c)).client == NO_CLIENT


def test_duplicate_names_get_parent_prefix(tmp_path):
    a = make_repo(tmp_path / "x" / "app")
    b = make_repo(tmp_path / "y" / "app")
    c = make_repo(tmp_path / "y" / "solo")
    resolver = Resolver([], [])
    resolver.learn_names([str(a), str(b), str(c)])
    assert resolver.project(str(a)).name == "x/app"
    assert resolver.project(str(b)).name == "y/app"
    assert resolver.project(str(c)).name == "solo"
    assert resolver.client_for_name("solo") == NO_CLIENT
