from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from vibe.cli.autocompletion import native_search
import vibe.cli.autocompletion.completers as completers_module
from vibe.cli.autocompletion.completers import BOOST_FIELD_COUNT, PathCompleter
from vibe.cli.autocompletion.file_indexer.store import IndexEntry, build_ascii_mask
from vibe.cli.autocompletion.fuzzy import fuzzy_match as real_fuzzy_match


@pytest.fixture()
def file_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "models.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "core" / "logger.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core" / "models.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core" / "ports.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core" / "sanitize.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core" / "use_cases.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "core" / "validate.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "settings.py").write_text("", encoding="utf-8")
    (tmp_path / "config" / "database.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_fuzzy_matches_subsequence_characters(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@sr", cursor_pos=3)

    assert "@src/" in results


def test_fuzzy_matches_consecutive_characters_higher(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/main", cursor_pos=9)

    assert "@src/main.py" in results


def test_fuzzy_matches_prefix_highest(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src", cursor_pos=4)

    assert results[0].startswith("@src")


def test_fuzzy_matches_across_directory_boundaries(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/main", cursor_pos=9)

    assert "@src/main.py" in results


def test_fuzzy_matches_case_insensitive(file_tree: Path) -> None:
    completer = PathCompleter()
    assert "@README.md" in completer.get_completions("@readme", cursor_pos=7)
    assert "@README.md" in completer.get_completions("@README", cursor_pos=7)


def test_fuzzy_matches_word_boundaries_preferred(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/mp", cursor_pos=7)

    assert "@src/models.py" in results


def test_bare_at_lists_current_directory_without_workspace_discovery(
    file_tree: Path,
) -> None:
    completer = PathCompleter()

    assert completer.get_completions("@", cursor_pos=1) == [
        "@config/",
        "@README.md",
        "@src/",
    ]
    assert completer._indexer.stats.rebuilds == 0


def test_fuzzy_matches_hidden_files_only_with_dot(file_tree: Path) -> None:
    completer = PathCompleter()
    assert "@.env" not in completer.get_completions("@e", cursor_pos=2)
    assert "@.env" in completer.get_completions("@.", cursor_pos=2)


def test_fuzzy_matches_directories_and_files(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/", cursor_pos=5)

    assert any(r.endswith("/") for r in results)
    assert any(not r.endswith("/") for r in results)


def test_fuzzy_matches_sorted_by_score(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/main", cursor_pos=9)

    assert results[0] == "@src/main.py"


def test_fuzzy_matches_nested_directories(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/core/l", cursor_pos=11)

    assert "@src/core/logger.py" in results


def test_fuzzy_matches_partial_filename(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/mo", cursor_pos=7)

    assert "@src/models.py" in results


def test_fuzzy_matches_multiple_files_with_same_pattern(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/m", cursor_pos=6)

    assert "@src/main.py" in results
    assert "@src/models.py" in results


def test_fuzzy_matches_no_results_when_no_match(file_tree: Path) -> None:
    completer = PathCompleter()
    assert completer.get_completions("@xyz123", cursor_pos=7) == []


def test_searches_entries_beyond_the_former_fixed_scan_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        IndexEntry(
            rel=f"generated/file_{index}.txt",
            rel_lower=f"generated/file_{index}.txt",
            name=f"file_{index}.txt",
            is_dir=False,
            ascii_mask=build_ascii_mask(f"generated/file_{index}.txt"),
        )
        for index in range(32_000)
    ]
    entries.append(
        IndexEntry(
            rel="src/needle.py",
            rel_lower="src/needle.py",
            name="needle.py",
            is_dir=False,
            ascii_mask=build_ascii_mask("src/needle.py"),
        )
    )
    completer = PathCompleter()
    monkeypatch.setattr(completer._indexer, "get_index", lambda *_: entries)

    assert "@src/needle.py" in completer.get_completions("@needle", cursor_pos=7)


def test_fuzzy_matches_directory_traversal(file_tree: Path) -> None:
    results = PathCompleter().get_completions("@src/", cursor_pos=5)

    assert "@src/main.py" in results
    assert "@src/core/" in results
    assert "@src/utils/" in results


def test_directory_prefix_can_match_from_a_nested_path_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "vibe" / "acp").mkdir(parents=True)
    (tmp_path / "vibe" / "acp" / "entrypoint.py").write_text("", encoding="utf-8")
    (tmp_path / "vibe" / "myacp").mkdir(parents=True)
    (tmp_path / "vibe" / "myacp" / "entrypoint.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@acp/", cursor_pos=5)

    assert "@vibe/acp/entrypoint.py" in results
    assert "@vibe/myacp/entrypoint.py" not in results


def test_prefers_exact_filename_match_over_other_path_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "chat-input.tsx").write_text("", encoding="utf-8")
    (tmp_path / "src" / "features").mkdir(parents=True)
    (tmp_path / "src" / "features" / "chat-input-state.ts").write_text(
        "", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "chat-input.md").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@chat-input", cursor_pos=11)

    assert results[0] == "@src/chat-input.tsx"


def test_keeps_late_strong_match_when_target_matches_is_small(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(10):
        (tmp_path / f"prefix_{i}_chatnoise.txt").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "chat-input.tsx").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter(target_matches=5).get_completions("@chati", cursor_pos=6)

    assert results[0] == "@src/chat-input.tsx"


def test_prefers_source_file_over_lock_file_for_stem_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "foo.lock").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@foo", cursor_pos=4)

    assert results[0] == "@src/foo.py"


def test_prefers_exact_filename_matches_for_filename_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        tmp_path
        / "ts"
        / "apps"
        / "le-chat-web"
        / "src"
        / "app"
        / "chat"
        / "_components"
    ).mkdir(parents=True)
    (
        tmp_path
        / "ts"
        / "apps"
        / "le-chat-web"
        / "src"
        / "app"
        / "chat"
        / "_components"
        / "chat-input.tsx"
    ).write_text("", encoding="utf-8")
    (tmp_path / "ts" / "apps" / "le-chat-web" / "src" / "components").mkdir(
        parents=True
    )
    (
        tmp_path
        / "ts"
        / "apps"
        / "le-chat-web"
        / "src"
        / "components"
        / "chat-input.tsx"
    ).write_text("", encoding="utf-8")
    (
        tmp_path / "ts" / "apps" / "le-chat-mobile" / "components" / "SearchInput.tsx"
    ).parent.mkdir(parents=True)
    (
        tmp_path / "ts" / "apps" / "le-chat-mobile" / "components" / "SearchInput.tsx"
    ).write_text("", encoding="utf-8")
    (
        tmp_path
        / "ts"
        / "apps"
        / "le-chat-web"
        / "src"
        / "app"
        / "chat"
        / "_components"
        / "message-input.tsx"
    ).write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@chat-input.tsx", cursor_pos=16)

    assert set(results[:2]) == {
        "@ts/apps/le-chat-web/src/app/chat/_components/chat-input.tsx",
        "@ts/apps/le-chat-web/src/components/chat-input.tsx",
    }
    assert results.index("@ts/apps/le-chat-mobile/components/SearchInput.tsx") > 1
    assert (
        results.index("@ts/apps/le-chat-web/src/app/chat/_components/message-input.tsx")
        > 1
    )


def test_exact_path_query_ranks_children_ahead_of_unrelated_fuzzy_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scripts" / "zephyr" / "generators").mkdir(parents=True)
    (tmp_path / "zephyr" / "generators" / "tests").mkdir(parents=True)
    (tmp_path / "zephyr" / "generators" / "prompts").mkdir(parents=True)
    (tmp_path / "zephyr" / "generators" / "common.py").write_text("", encoding="utf-8")
    (tmp_path / "zephyr" / "generators" / "README.md").write_text("", encoding="utf-8")
    (
        tmp_path
        / "zephyr"
        / "datasets"
        / "synthetic_sp_up_conflict"
        / "grounded_policies"
        / "hotel"
    ).mkdir(parents=True)
    (
        tmp_path
        / "zephyr"
        / "datasets"
        / "synthetic_sp_up_conflict"
        / "grounded_policies"
        / "hotel"
        / "generators.py"
    ).write_text("", encoding="utf-8")
    (
        tmp_path
        / "zephyr"
        / "datasets"
        / "synthetic_sp_up_conflict"
        / "grounded_policies"
        / "retail"
    ).mkdir(parents=True)
    (
        tmp_path
        / "zephyr"
        / "datasets"
        / "synthetic_sp_up_conflict"
        / "grounded_policies"
        / "retail"
        / "generators.py"
    ).write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@zephyr/generators", cursor_pos=18)

    assert results[0] == "@zephyr/generators/"
    assert results.index("@zephyr/generators/common.py") < results.index(
        "@zephyr/datasets/synthetic_sp_up_conflict/grounded_policies/hotel/generators.py"
    )
    assert results.index("@zephyr/generators/prompts/") < results.index(
        "@zephyr/datasets/synthetic_sp_up_conflict/grounded_policies/retail/generators.py"
    )
    assert results.index("@zephyr/generators/tests/") < results.index(
        "@zephyr/datasets/synthetic_sp_up_conflict/grounded_policies/hotel/generators.py"
    )


def test_prioritizes_exact_path_prefix_before_fuzzy_search_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def make_entry(rel: str, *, is_dir: bool = False) -> IndexEntry:
        return IndexEntry(
            rel=rel,
            rel_lower=rel.lower(),
            name=Path(rel).name,
            is_dir=is_dir,
            ascii_mask=build_ascii_mask(rel.lower()),
        )

    entries = [
        make_entry("tools/flake8/alembic-loop/build/lib/flake8_alembic_loop.py"),
        make_entry("cloud-api-client/.speakeasy/cloud-api-codegen-overlay.yaml"),
        make_entry("vibe/tests/cli/test_audio_config_boundary.py"),
        make_entry("ts", is_dir=True),
        make_entry("ts/apps/cloud/AGENTS.md"),
    ]
    completer = PathCompleter(max_entries_to_process=3)
    monkeypatch.setattr(completer._indexer, "get_index", lambda *_: entries)

    results = completer.get_completions("@ts/cloudA", cursor_pos=10)

    assert results[0] == "@ts/apps/cloud/AGENTS.md"


def test_skips_fuzzy_scoring_for_entries_missing_required_query_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "chat-input.tsx").write_text("", encoding="utf-8")
    for name in ("alpha.txt", "theta.txt", "notes.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    for i in range(20):
        (tmp_path / f"zzzz_{i}.txt").write_text("", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    fuzzy_calls: list[str] = []

    def counting_fuzzy_match(
        pattern: str, text: str, text_lower: str | None = None
    ) -> object:
        fuzzy_calls.append(text)
        return real_fuzzy_match(pattern, text, text_lower)

    monkeypatch.setattr(completers_module, "fuzzy_match", counting_fuzzy_match)

    results = PathCompleter().get_completions("@chati", cursor_pos=6)

    assert results[0] == "@src/chat-input.tsx"
    assert fuzzy_calls == ["src/chat-input.tsx"]


def test_non_ascii_queries_still_match_when_ascii_prefilter_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "café.txt").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = PathCompleter().get_completions("@café", cursor_pos=5)

    assert results == ["@café.txt"]


def test_trailing_slash_on_nonexistent_prefix_keeps_picker_alive(
    file_tree: Path,
) -> None:
    # "cor" is not a real directory (the real dir is "core"), but fuzzy-matches
    # paths under "core/". The trailing slash is kept as a literal anchor so
    # only paths where "cor" precedes a directory boundary survive.
    results = PathCompleter().get_completions("@cor/", cursor_pos=5)

    assert results
    assert "@src/core/logger.py" in results
    assert all(result.startswith("@src/core/") for result in results)


def test_trailing_slash_on_real_prefix_still_lists_immediate_children(
    file_tree: Path,
) -> None:
    results = PathCompleter().get_completions("@src/", cursor_pos=5)

    assert "@src/main.py" in results
    assert "@src/core/" in results


def test_slash_only_partial_does_not_flood_picker(file_tree: Path) -> None:
    # "@/" has no non-slash content to anchor on; the fuzzy fallback must skip
    # it instead of matching every indexed path that contains a separator.
    results = PathCompleter().get_completions("@/", cursor_pos=2)

    assert results == []


def test_trailing_slash_on_empty_real_dir_returns_empty_not_fuzzy_noise(
    file_tree: Path,
) -> None:
    # src/utils is a real indexed directory with no children. The picker must
    # return an empty list rather than falling back to fuzzy and surfacing
    # unrelated paths that happen to contain "utils" as a substring.
    results = PathCompleter().get_completions("@src/utils/", cursor_pos=11)

    assert results == []


@pytest.fixture()
def nested_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("", encoding="utf-8")
    (tmp_path / "sibling").mkdir()
    (tmp_path / "sibling" / "note.txt").write_text("", encoding="utf-8")
    (tmp_path / "sibling" / "nested").mkdir()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.chdir(project)
    return tmp_path


def test_parent_directory_traversal_lists_siblings(nested_project: Path) -> None:
    results = PathCompleter().get_completions("@../", cursor_pos=4)

    assert "@../sibling/" in results
    assert "@../project/" in results


def test_parent_directory_segment_drills_into_sibling(nested_project: Path) -> None:
    results = PathCompleter().get_completions("@../sibling/", cursor_pos=12)

    assert "@../sibling/note.txt" in results
    assert "@../sibling/nested/" in results


def test_grandparent_traversal_lists_entries(nested_project: Path) -> None:
    results = PathCompleter().get_completions("@../../", cursor_pos=7)

    assert results
    assert all(result.startswith("@../../") for result in results)


def test_parent_dot_suffix_lists_hidden_files(nested_project: Path) -> None:
    results = PathCompleter().get_completions("@../.", cursor_pos=5)

    assert "@../.env" in results
    assert all(not r.startswith("@../.") or r == "@../.env" for r in results)


def test_windows_backslash_in_parent_traversal_is_normalized(
    nested_project: Path,
) -> None:
    # On Windows a user may type @..\ instead of @../. The completer must
    # normalize the backslash so parent traversal still works. The test is
    # runnable on Linux/macOS because normalization happens before any
    # filesystem call.
    results = PathCompleter().get_completions("@..\\", cursor_pos=4)

    assert "@../sibling/" in results
    assert "@../project/" in results


def test_windows_backslash_drills_into_sibling(nested_project: Path) -> None:
    results = PathCompleter().get_completions("@..\\sibling\\", cursor_pos=12)

    assert "@../sibling/note.txt" in results
    assert "@../sibling/nested/" in results


def _index_entry(rel: str, *, is_dir: bool = False) -> IndexEntry:
    return IndexEntry(
        rel=rel,
        rel_lower=rel.lower(),
        name=rel.rsplit("/", 1)[-1],
        is_dir=is_dir,
        ascii_mask=build_ascii_mask(rel.lower()),
    )


_LARGE_INDEX_NEEDLES = [
    "src/needle.py",
    "lib/needle_utils.py",
    "docs/needles.md",
    "pkg/n_e_e_d_l_e.txt",
    "uv.lock",
    "needle",
]


def _large_index() -> list[IndexEntry]:
    entries = [
        _index_entry(f"generated/batch_{batch}/file_{index}.txt")
        for batch in range(4)
        for index in range(600)
    ]
    entries += [
        _index_entry(f"generated/batch_{batch}", is_dir=True) for batch in range(4)
    ]
    entries.append(_index_entry("needle", is_dir=True))
    entries += [_index_entry(rel) for rel in _LARGE_INDEX_NEEDLES[:-1]]
    return sorted(entries, key=lambda entry: entry.rel)


@pytest.mark.parametrize(
    "query",
    [
        "needle",
        "needle.py",
        "needle/",
        "src/needle",
        ".py",
        "uv.lock",
        "lock",
        "n",
        "batch_1/file_1",
        "zzz",
    ],
)
def test_boost_key_orders_like_the_match_rank_boost_flags(query: str) -> None:
    completer = PathCompleter()
    context = completer._build_search_context(query)
    facts = completer._query_facts(context)

    for entry in _large_index()[::37] + [
        _index_entry(rel) for rel in _LARGE_INDEX_NEEDLES
    ]:
        flags = completer._build_match_rank(entry, context, 0.0, facts)[
            :BOOST_FIELD_COUNT
        ]
        packed = sum(bit << (BOOST_FIELD_COUNT - 1 - i) for i, bit in enumerate(flags))
        assert completer._boost_key(entry, facts) == packed, entry.rel


@pytest.mark.skipif(shutil.which("fzf") is None, reason="needs fzf")
def test_large_index_is_ranked_by_fzf_with_structural_boosts_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_search.reset_native_search_cache()
    entries = _large_index()
    completer = PathCompleter()
    monkeypatch.setattr(completer._indexer, "get_index", lambda *_: entries)

    def no_python_scoring(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("large indexes should be scored by fzf")

    monkeypatch.setattr(completers_module, "fuzzy_match", no_python_scoring)

    results = completer.get_completions("@needle", cursor_pos=7)

    assert results[:2] == ["@needle/", "@src/needle.py"]
    assert set(results[2:4]) == {"@lib/needle_utils.py", "@docs/needles.md"}
    assert "@pkg/n_e_e_d_l_e.txt" in results
    assert completer.get_completions("@zzzq", cursor_pos=5) == []


@pytest.mark.skipif(shutil.which("fzf") is None, reason="needs fzf")
def test_fzf_and_python_rankings_agree_on_boosted_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Below the structural boosts the two scorers may order plain fuzzy
    # matches differently; above them, both must produce the same groups.
    native_search.reset_native_search_cache()
    entries = _large_index()
    by_label = {
        f"@{entry.rel}{'/' if entry.is_dir else ''}": entry for entry in entries
    }
    completer = PathCompleter()
    monkeypatch.setattr(completer._indexer, "get_index", lambda *_: entries)

    def boost_groups(query: str, results: list[str]) -> list[tuple[int, set[str]]]:
        facts = completer._query_facts(completer._build_search_context(query[1:]))
        groups: dict[int, set[str]] = {}
        for label in results:
            if key := completer._boost_key(by_label[label], facts):
                groups.setdefault(key, set()).add(label)
        return list(groups.items())

    for query in ("@needle", "@needle.py", "@uv.lock", "@src/needle", "@.md"):
        with_fzf = completer.get_completions(query, cursor_pos=len(query))
        with monkeypatch.context() as patch:
            patch.setattr(native_search, "fzf_executable", lambda cwd=None: None)
            python_only = completer.get_completions(query, cursor_pos=len(query))
        assert with_fzf[0] == python_only[0], query
        assert boost_groups(query, with_fzf) == boost_groups(query, python_only)


def test_large_index_falls_back_to_python_without_fzf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _large_index()
    completer = PathCompleter()
    monkeypatch.setattr(completer._indexer, "get_index", lambda *_: entries)
    monkeypatch.setattr(native_search, "fzf_executable", lambda cwd=None: None)

    results = completer.get_completions("@needle", cursor_pos=7)

    assert results[:2] == ["@needle/", "@src/needle.py"]
