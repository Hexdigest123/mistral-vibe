"""Discovered model lists, cached until the machine reboots.

The cache is one JSON file in a private per-user directory under the system
temp dir (``/tmp/vibe-<uid>/discovered-models.json`` on Linux) and records the
boot it was written in: until a reboot, or until the temp dir is cleaned, a
session start reads it instead of asking the providers again. A provider's
entry also records its endpoint and a fingerprint of its key, so pointing the
provider elsewhere or changing the key refetches that provider only.

The temp dir is shared by every local user, so the directory must be a real
directory this user owns and nobody else can enter; anything else (a symlink,
another owner) disables the cache rather than trusting what it holds.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import getpass
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vibe.core.models.catalog import DiscoveredModel
from vibe.observability.logging import logger

CACHE_VERSION = 2
CACHE_FILE_NAME = "discovered-models.json"
LOCK_FILE_NAME = ".discovered-models.lock"
_BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")

# None resolves under the system temp dir; tests point it elsewhere.
_CACHE_DIR: Path | None = None


class CachedProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endpoint: str
    key: str = ""
    fetched_at: float = 0.0
    models: list[DiscoveredModel] = Field(default_factory=list)


class DiscoveryCache(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = CACHE_VERSION
    boot_id: str = ""
    providers: dict[str, CachedProvider] = Field(default_factory=dict)


def cache_dir() -> Path:
    if _CACHE_DIR is not None:
        return _CACHE_DIR
    owner = os.getuid() if hasattr(os, "getuid") else getpass.getuser()
    return Path(tempfile.gettempdir()) / f"vibe-{owner}"


def cache_path() -> Path:
    return cache_dir() / CACHE_FILE_NAME


def boot_id() -> str:
    """This boot's identity: the kernel's boot id, else the minute it booted."""
    with contextlib.suppress(OSError):
        if value := _BOOT_ID_FILE.read_text(encoding="ascii").strip():
            return value
    # A clock that keeps counting through sleep, so a resume is not a reboot.
    clock = getattr(time, "CLOCK_BOOTTIME", None)
    if clock is None:
        clock = getattr(time, "CLOCK_MONOTONIC", None)
    uptime = time.clock_gettime(clock) if clock is not None else time.monotonic()
    return f"boot-{int(time.time() - uptime) // 60}"


def key_fingerprint(key: str | None) -> str:
    """A short hash naming the key an entry was fetched with; empty without one."""
    return hashlib.sha256(key.encode()).hexdigest()[:16] if key else ""


def load_cache() -> DiscoveryCache:
    """This boot's cache: empty when missing, unreadable, untrusted or stale."""
    current = boot_id()
    path = cache_path()
    if not _private_dir(path.parent, create=False):
        return DiscoveryCache(boot_id=current)
    try:
        cache = DiscoveryCache.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return DiscoveryCache(boot_id=current)
    except (OSError, ValidationError) as exc:
        logger.debug("Discovered model cache ignored path=%s error=%s", path, exc)
        return DiscoveryCache(boot_id=current)
    if cache.version != CACHE_VERSION or cache.boot_id != current:
        return DiscoveryCache(boot_id=current)
    return cache


def save_cache(cache: DiscoveryCache) -> None:
    """Replace the cache atomically; a failure only costs the next start a fetch."""
    path = cache_path()
    if not _private_dir(path.parent, create=True):
        logger.warning(
            "Discovered models not cached: %s is not a private directory", path.parent
        )
        return
    tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            tmp = handle.name
            handle.write(cache.model_dump_json())
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not cache discovered models path=%s error=%s", path, exc)
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


@contextlib.asynccontextmanager
async def locked() -> AsyncIterator[None]:
    """Hold this user's discovery lock across processes and sessions, so starts
    racing on an empty cache fetch each provider once: the later one waits,
    then reads what the first cached. The OS drops the lock with its holder.
    """
    directory = cache_dir()
    if sys.platform == "win32" or not _private_dir(directory, create=True):
        yield
        return
    import fcntl

    handle = await asyncio.to_thread(open, directory / LOCK_FILE_NAME, "a")
    try:
        await asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _private_dir(path: Path, *, create: bool) -> bool:
    """Whether ``path`` is a directory only this user can enter, made if asked."""
    try:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    if not hasattr(os, "getuid"):
        return True
    if info.st_uid != os.getuid():
        return False
    if info.st_mode & 0o077:
        try:
            path.chmod(0o700)
        except OSError:
            return False
    return True
