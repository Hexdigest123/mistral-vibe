from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import re

from vibe.utils.io import read_safe

DEFAULT_IGNORE_PATTERNS: list[tuple[str, bool]] = [
    (".git/", True),
    ("__pycache__/", True),
    ("node_modules/", True),
    (".DS_Store", True),
    ("*.pyc", True),
    ("*.log", True),
    (".vscode/", True),
    (".idea/", True),
    ("/build/", True),
    ("dist/", True),
    ("target/", True),
    (".next/", True),
    (".nuxt/", True),
    ("coverage/", True),
    (".nyc_output/", True),
    ("*.egg-info", True),
    (".pytest_cache/", True),
    (".tox/", True),
    ("vendor/", True),
    ("third_party/", True),
    ("deps/", True),
    ("*.min.js", True),
    ("*.min.css", True),
    ("*.bundle.js", True),
    ("*.chunk.js", True),
    (".cache/", True),
    ("tmp/", True),
    ("temp/", True),
    ("logs/", True),
    (".uv-cache/", True),
    (".ruff_cache/", True),
    (".venv/", True),
    ("venv/", True),
    (".mypy_cache/", True),
    ("htmlcov/", True),
    (".coverage", True),
]


@dataclass(slots=True)
class CompiledPattern:
    raw: str
    stripped: str
    is_exclude: bool
    dir_only: bool
    name_only: bool
    anchor_root: bool


@dataclass(frozen=True, slots=True)
class _ExcludeMatchers:
    """Every exclude pattern folded into one regex per (target, dir_only) group.

    Only valid when no pattern negates: then "ignored" is simply "any pattern
    matches", and one regex per group replaces a `fnmatch` call per pattern.
    """

    name: re.Pattern[str] | None
    name_dir: re.Pattern[str] | None
    root_name: re.Pattern[str] | None
    root_name_dir: re.Pattern[str] | None
    path: re.Pattern[str] | None
    path_dir: re.Pattern[str] | None

    @classmethod
    def build(cls, patterns: list[CompiledPattern]) -> _ExcludeMatchers:
        def group(
            *, name_only: bool, anchor_root: bool, dir_only: bool
        ) -> re.Pattern[str] | None:
            sources = [
                fnmatch.translate(os.path.normcase(pattern.stripped))
                for pattern in patterns
                if pattern.name_only == name_only
                and (pattern.anchor_root == anchor_root or not name_only)
                and pattern.dir_only == dir_only
            ]
            return re.compile("|".join(sources)) if sources else None

        return cls(
            name=group(name_only=True, anchor_root=False, dir_only=False),
            name_dir=group(name_only=True, anchor_root=False, dir_only=True),
            root_name=group(name_only=True, anchor_root=True, dir_only=False),
            root_name_dir=group(name_only=True, anchor_root=True, dir_only=True),
            path=group(name_only=False, anchor_root=False, dir_only=False),
            path_dir=group(name_only=False, anchor_root=False, dir_only=True),
        )

    def matches(self, rel_str: str, name: str, is_dir: bool) -> bool:
        name = os.path.normcase(name)
        if self.name and self.name.match(name):
            return True
        if is_dir and self.name_dir and self.name_dir.match(name):
            return True
        if "/" not in rel_str:
            if self.root_name and self.root_name.match(name):
                return True
            if is_dir and self.root_name_dir and self.root_name_dir.match(name):
                return True
        rel_str = os.path.normcase(rel_str)
        if self.path and self.path.match(rel_str):
            return True
        return bool(is_dir and self.path_dir and self.path_dir.match(rel_str))


class IgnoreRules:
    def __init__(self, defaults: list[tuple[str, bool]] | None = None) -> None:
        self._defaults = defaults or DEFAULT_IGNORE_PATTERNS
        self._patterns: list[CompiledPattern] | None = None
        self._exclude_matchers: _ExcludeMatchers | None = None
        self._root: Path | None = None

    @property
    def default_exclude_patterns(self) -> list[str]:
        """The default patterns, in `.gitignore` syntax, for native walkers."""
        return [raw if is_exclude else f"!{raw}" for raw, is_exclude in self._defaults]

    def _compile_default_patterns(self) -> list[CompiledPattern]:
        patterns: list[CompiledPattern] = []
        for raw, is_exclude in self._defaults:
            anchor_root = raw.startswith("/")
            if anchor_root:
                raw = raw[1:]
            stripped = raw.rstrip("/")
            patterns.append(
                CompiledPattern(
                    raw=raw,
                    stripped=stripped,
                    is_exclude=is_exclude,
                    dir_only=raw.endswith("/"),
                    name_only="/" not in stripped,
                    anchor_root=anchor_root,
                )
            )
        return patterns

    def get_walk_skip_dir_names(self) -> frozenset[str]:
        return frozenset(
            p.stripped
            for p in self._compile_default_patterns()
            if p.dir_only and p.name_only and not p.anchor_root
        )

    def ensure_for_root(self, root: Path) -> None:
        resolved_root = root.resolve()
        if self._patterns is None or self._root != resolved_root:
            self._patterns = self._build_patterns(resolved_root)
            self._exclude_matchers = (
                _ExcludeMatchers.build(self._patterns)
                if all(pattern.is_exclude for pattern in self._patterns)
                else None
            )
            self._root = resolved_root

    def should_ignore(self, rel_str: str, name: str, is_dir: bool) -> bool:
        if not self._patterns:
            return False

        if self._exclude_matchers is not None:
            return self._exclude_matchers.matches(rel_str, name, is_dir)

        ignored = False
        for pattern in self._patterns:
            if self._matches(rel_str, name, is_dir, pattern):
                ignored = pattern.is_exclude
        return ignored

    def reset(self) -> None:
        self._patterns = None
        self._exclude_matchers = None
        self._root = None

    def _build_patterns(self, root: Path) -> list[CompiledPattern]:
        patterns = self._compile_default_patterns()
        gitignore_path = root / ".gitignore"
        if gitignore_path.exists():
            try:
                text = read_safe(gitignore_path).text
            except Exception:
                return patterns

            for line in text.splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue

                if "#" in raw:
                    raw = raw.split("#", 1)[0].rstrip()
                    if not raw:
                        continue

                is_exclude = not raw.startswith("!")
                if not is_exclude:
                    raw = raw[1:].lstrip()
                    if not raw:
                        continue

                anchor_root = raw.startswith("/")
                if anchor_root:
                    raw = raw[1:]

                stripped = raw.rstrip("/")
                patterns.append(
                    CompiledPattern(
                        raw=raw,
                        stripped=stripped,
                        is_exclude=is_exclude,
                        dir_only=raw.endswith("/"),
                        name_only="/" not in stripped,
                        anchor_root=anchor_root,
                    )
                )

        return patterns

    def _matches(
        self, rel_str: str, name: str, is_dir: bool, pattern: CompiledPattern
    ) -> bool:
        if pattern.name_only:
            if pattern.anchor_root and "/" in rel_str:
                return False
            target = name
        else:
            target = rel_str

        if not fnmatch.fnmatch(target, pattern.stripped):
            return False

        return not pattern.dir_only or is_dir


WALK_SKIP_DIR_NAMES: frozenset[str] = IgnoreRules().get_walk_skip_dir_names()
