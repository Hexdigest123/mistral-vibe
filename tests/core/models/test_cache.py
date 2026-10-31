from __future__ import annotations

import getpass
import os
from pathlib import Path
import sys

import pytest

from vibe.core.models import cache
from vibe.core.models.cache import (
    CACHE_VERSION,
    CachedProvider,
    DiscoveryCache,
    boot_id,
    cache_path,
    key_fingerprint,
    load_cache,
    save_cache,
)
from vibe.core.models.catalog import DiscoveredModel

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")


def _cache(**providers: list[str]) -> DiscoveryCache:
    return DiscoveryCache(
        boot_id=boot_id(),
        providers={
            name: CachedProvider(
                endpoint=f"https://{name}/models",
                models=[DiscoveredModel(id=model_id) for model_id in ids],
            )
            for name, ids in providers.items()
        },
    )


def test_cache_lives_under_the_system_temp_dir_per_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cache, "_CACHE_DIR", None)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    owner = os.getuid() if hasattr(os, "getuid") else getpass.getuser()
    assert cache_path() == tmp_path / f"vibe-{owner}" / "discovered-models.json"


def test_round_trip() -> None:
    save_cache(_cache(openrouter=["a", "b"]))
    loaded = load_cache()
    assert loaded.version == CACHE_VERSION
    assert [m.id for m in loaded.providers["openrouter"].models] == ["a", "b"]


def test_missing_cache_is_empty_for_this_boot() -> None:
    loaded = load_cache()
    assert loaded.providers == {}
    assert loaded.boot_id == boot_id()


def test_a_reboot_empties_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    save_cache(_cache(openrouter=["a"]))
    monkeypatch.setattr(cache, "boot_id", lambda: "another-boot")
    assert load_cache().providers == {}


def test_other_versions_and_corrupt_files_are_ignored() -> None:
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().write_text("{not json", encoding="utf-8")
    assert load_cache().providers == {}
    stale = _cache(openrouter=["a"]).model_copy(update={"version": 1})
    cache_path().write_text(stale.model_dump_json(), encoding="utf-8")
    assert load_cache().providers == {}


def test_boot_id_is_stable_within_a_boot() -> None:
    assert boot_id() == boot_id()
    assert boot_id()


def test_key_fingerprint_hides_the_key() -> None:
    assert key_fingerprint(None) == key_fingerprint("") == ""
    assert key_fingerprint("secret") != "secret"
    assert key_fingerprint("secret") == key_fingerprint("secret")
    assert len(key_fingerprint("secret")) == 16


@posix_only
def test_the_directory_is_made_private() -> None:
    save_cache(_cache(openrouter=["a"]))
    assert cache_path().parent.stat().st_mode & 0o777 == 0o700
    assert [p.name for p in cache_path().parent.iterdir()] == [cache_path().name]


@posix_only
def test_a_shared_directory_is_tightened() -> None:
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().parent.chmod(0o777)
    save_cache(_cache(openrouter=["a"]))
    assert cache_path().parent.stat().st_mode & 0o777 == 0o700
    assert load_cache().providers


@posix_only
def test_a_symlinked_directory_is_never_trusted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    link = tmp_path / "vibe-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(cache, "_CACHE_DIR", link)
    save_cache(_cache(openrouter=["a"]))
    assert not (target / "discovered-models.json").exists()
    assert load_cache().providers == {}


@posix_only
def test_a_directory_owned_by_someone_else_is_never_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_cache(_cache(openrouter=["a"]))
    monkeypatch.setattr(os, "getuid", lambda: os.stat(cache_path()).st_uid + 1)
    assert load_cache().providers == {}
