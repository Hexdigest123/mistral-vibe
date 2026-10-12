from __future__ import annotations

from pathlib import Path

import pytest

from vibe.cli.autocompletion.file_indexer.ignore_rules import IgnoreRules

_CASES = [
    ("node_modules", "node_modules", True),
    ("pkg/node_modules", "node_modules", True),
    ("node_modules", "node_modules", False),
    ("build", "build", True),
    ("pkg/build", "build", True),
    ("debug.log", "debug.log", False),
    ("logs/app.log", "app.log", False),
    ("src/main.py", "main.py", False),
    ("src/main.pyc", "main.pyc", False),
    ("docs/guide.md", "guide.md", False),
    ("docs/sub/guide.md", "guide.md", False),
    ("secret.txt", "secret.txt", False),
    ("pkg/secret.txt", "secret.txt", False),
    ("out", "out", True),
    ("pkg/out", "out", True),
    ("a.egg-info", "a.egg-info", True),
    (".env", ".env", False),
]


def _slow_answers(rules: IgnoreRules) -> list[bool]:
    matchers = rules._exclude_matchers
    rules._exclude_matchers = None
    try:
        return [rules.should_ignore(*case) for case in _CASES]
    finally:
        rules._exclude_matchers = matchers


@pytest.mark.parametrize(
    "gitignore",
    [
        "",
        "secret.txt\n/out/\ndocs/*.md\n# comment\n*.tmp  # trailing\n",
        "/secret.txt\nout/\n",
    ],
)
def test_compiled_matchers_agree_with_the_ordered_pattern_loop(
    tmp_path: Path, gitignore: str
) -> None:
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    rules = IgnoreRules()
    rules.ensure_for_root(tmp_path)

    assert rules._exclude_matchers is not None
    fast = [rules.should_ignore(*case) for case in _CASES]
    assert fast == _slow_answers(rules)


def test_negations_keep_last_match_wins_semantics(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("!build/\n*.md\n!keep.md\n", encoding="utf-8")
    rules = IgnoreRules()
    rules.ensure_for_root(tmp_path)

    assert rules._exclude_matchers is None
    assert not rules.should_ignore("build", "build", True)
    assert rules.should_ignore("notes.md", "notes.md", False)
    assert not rules.should_ignore("keep.md", "keep.md", False)
    assert rules.should_ignore("node_modules", "node_modules", True)


def test_default_exclude_patterns_are_gitignore_lines() -> None:
    rules = IgnoreRules(defaults=[("/build/", True), ("*.log", True), ("keep", False)])

    assert rules.default_exclude_patterns == ["/build/", "*.log", "!keep"]
