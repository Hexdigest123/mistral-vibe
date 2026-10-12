from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path
import shutil

import pytest

from vibe.cli.autocompletion import native_search
from vibe.cli.autocompletion.file_indexer.ignore_rules import IgnoreRules
from vibe.cli.autocompletion.file_indexer.store import (
    FileIndexStats,
    FileIndexStore,
    IndexEntry,
)

requires_fzf = pytest.mark.skipif(shutil.which("fzf") is None, reason="needs fzf")
requires_fd = pytest.mark.skipif(
    shutil.which("fd") is None and shutil.which("fdfind") is None, reason="needs fd"
)
posix_only = pytest.mark.skipif(os.name == "nt", reason="uses a shell-script fake")


@pytest.fixture(autouse=True)
def _fresh_tool_cache() -> Generator[None]:
    native_search.reset_native_search_cache()
    yield
    native_search.reset_native_search_cache()


def _install_fake_tool(bin_dir: Path, name: str, script: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    tool = bin_dir / name
    tool.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    tool.chmod(0o755)


def test_fzf_filter_returns_none_without_fzf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert native_search.fzf_filter("abc", ["abc"]) is None


@requires_fzf
def test_fzf_filter_ranks_case_insensitive_subsequence_matches() -> None:
    candidates = ["docs/README.md", "src/main.py", "src/models.py", "zzz.txt"]

    ranked = native_search.fzf_filter("srcmain", candidates)

    assert ranked == [1]
    assert native_search.fzf_filter("readme", candidates) == [0]
    assert native_search.fzf_filter("qqq", candidates) == []


@requires_fzf
def test_fzf_filter_maps_duplicate_candidates_to_distinct_indices() -> None:
    ranked = native_search.fzf_filter("a", ["a", "b", "a"])

    assert ranked is not None
    assert sorted(ranked) == [0, 2]


@requires_fzf
def test_fzf_filter_does_not_match_its_own_index_suffix() -> None:
    candidates = [f"name-{letter}" for letter in "abcdefghijkl"]

    assert native_search.fzf_filter("0", candidates) == []


@requires_fzf
def test_fzf_filter_ignores_user_default_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `--exact` would turn the scattered subsequence below into a non-match.
    monkeypatch.setenv("FZF_DEFAULT_OPTS", "--exact --no-sort")

    assert native_search.fzf_filter("sm", ["src/main.py"]) == [0]


@requires_fzf
def test_fzf_filter_treats_the_query_literally() -> None:
    candidates = ["abc", "x^abc", "!abc"]

    ranked = native_search.fzf_filter("^a", candidates)
    assert ranked == [1]
    assert native_search.fzf_filter("!a", candidates) == [2]


@requires_fzf
def test_fzf_filter_returns_none_when_cancelled() -> None:
    assert native_search.fzf_filter("a", ["a"], should_cancel=lambda: True) is None


@posix_only
def test_fzf_usage_error_disables_fzf_for_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    _install_fake_tool(bin_dir, "fzf", f'echo call >> "{calls}"\nexit 2')
    monkeypatch.setenv("PATH", str(bin_dir))
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path / "project")

    assert native_search.fzf_filter("a", ["a"]) is None
    assert native_search.fzf_executable() is None
    assert native_search.fzf_filter("a", ["a"]) is None
    assert calls.read_text(encoding="utf-8").count("call") == 1


@posix_only
def test_fzf_no_match_exit_does_not_disable_fzf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    _install_fake_tool(bin_dir, "fzf", "exit 1")
    monkeypatch.setenv("PATH", str(bin_dir))
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path / "project")

    assert native_search.fzf_filter("a", ["a"]) == []
    assert native_search.fzf_executable() is not None


@posix_only
def test_native_tools_are_never_taken_from_the_project_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "executed"
    for name in ("fzf", "fd"):
        _install_fake_tool(tmp_path, name, f'touch "{marker}"')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert native_search.fzf_executable() is None
    assert native_search.fd_executable() is None
    assert native_search.fzf_filter("a", ["a"]) is None
    assert native_search.fd_list_entries(tmp_path, [".git/"]) is None
    assert not marker.exists()


def _comparable(entries: list[IndexEntry]) -> set[tuple[str, bool, str, int]]:
    return {(e.rel, e.is_dir, e.name, e.ascii_mask) for e in entries}


def _sample_tree(root: Path) -> None:
    (root / "src" / "core").mkdir(parents=True)
    (root / "src" / "core" / "models.py").write_text("", encoding="utf-8")
    (root / "src" / "empty").mkdir()
    (root / "dist" / "keep").mkdir(parents=True)
    (root / "dist" / "keep" / "bundle.js").write_text("", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "out.o").write_text("", encoding="utf-8")
    (root / "pkg" / "build").mkdir(parents=True)
    (root / "pkg" / "build" / "nested.o").write_text("", encoding="utf-8")
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "node_modules" / "dep" / "index.js").write_text("", encoding="utf-8")
    (root / "debug.log").write_text("", encoding="utf-8")
    (root / ".env").write_text("", encoding="utf-8")
    (root / "secret.txt").write_text("", encoding="utf-8")
    # A negation re-includes a directory the defaults ignore; later rules win.
    (root / ".gitignore").write_text("secret.txt\n!dist/\n", encoding="utf-8")


@requires_fd
def test_fd_listing_mirrors_the_python_walker(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    store = FileIndexStore(IgnoreRules(), FileIndexStats())
    store._ignore_rules.ensure_for_root(tmp_path)

    fd_entries = store._list_fd_entries(tmp_path, None)
    walked = store._walk_directory(tmp_path)

    assert fd_entries is not None
    assert walked is not None
    assert _comparable(fd_entries) == _comparable(walked)
    rels = {entry.rel for entry in fd_entries}
    assert {"src/empty", "dist/keep/bundle.js", "pkg/build/nested.o", ".env"} <= rels
    assert rels.isdisjoint({"build", "node_modules", "debug.log", "secret.txt"})


@requires_fd
def test_non_git_rebuild_uses_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sample_tree(tmp_path)
    store = FileIndexStore(IgnoreRules(), FileIndexStats())
    monkeypatch.setattr(
        store, "_walk_directory", lambda *_a, **_k: pytest.fail("walked in Python")
    )

    assert store.rebuild(tmp_path)
    assert not store.is_git_backed
    assert "src/empty" in {entry.rel for entry in store.snapshot()}


def test_non_git_rebuild_falls_back_to_the_python_walker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sample_tree(tmp_path)
    monkeypatch.setattr(native_search, "fd_executable", lambda cwd=None: None)
    store = FileIndexStore(IgnoreRules(), FileIndexStats())

    assert store.rebuild(tmp_path)
    rels = {entry.rel for entry in store.snapshot()}
    assert {"src/empty", "dist/keep/bundle.js", ".env"} <= rels
    assert rels.isdisjoint({"build", "node_modules", "debug.log", "secret.txt"})
