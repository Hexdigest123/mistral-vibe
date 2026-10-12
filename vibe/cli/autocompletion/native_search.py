"""Native search backends (fzf, fd) with a pure-Python fallback.

Every entry point returns ``None`` when the native tool cannot answer -- it is
not installed, exited with an error, timed out, or the caller cancelled -- and
callers then run their pure-Python implementation. A tool that fails with a
usage error (exit code 2, e.g. an fzf too old for ``--scheme``) is disabled for
the rest of the process so a broken install costs one subprocess, not one per
keystroke.

These helpers block, so callers run them off the Textual event loop (the path
completion worker thread, the file-index rebuild thread).
"""

from __future__ import annotations

import atexit
from collections.abc import Callable, Sequence
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import IO

from vibe.utils.platform import resolve_trusted_executable

# Below this many candidates the pure-Python matcher answers faster than
# spawning fzf (~2-4 ms of process start-up before any matching happens).
FZF_MIN_CANDIDATES = 1000

_POLL_INTERVAL_S = 0.01
_FIELD_SEPARATOR = "\x1f"
_TIMEOUT_S = 10.0
_USAGE_ERROR_EXIT_CODE = 2

# User-level defaults these tools read from the environment can change the
# matching semantics (`--exact`, `--no-sort`, `--tiebreak`, extra globs...).
_SCRUBBED_ENV_VARS = ("FZF_DEFAULT_OPTS", "FZF_DEFAULT_OPTS_FILE")

_lock = threading.Lock()
_executables: dict[tuple[str, Path], str | None] = {}
_disabled: set[str] = set()
_ignore_files: dict[tuple[str, ...], Path] = {}


def _resolve(*names: str, cwd: Path | None) -> str | None:
    """Resolve the first of ``names`` on PATH, never a project-local binary.

    Cached per project directory, because whether a PATH entry is trusted
    depends on which project Vibe is working in.
    """
    tool = names[0]
    project_dir = (cwd or Path.cwd()).resolve()
    with _lock:
        if tool in _disabled:
            return None
        key = (tool, project_dir)
        if key not in _executables:
            _executables[key] = next(
                (
                    path
                    for name in names
                    if (path := resolve_trusted_executable(name, cwd=project_dir))
                ),
                None,
            )
        return _executables[key]


def _disable(name: str) -> None:
    with _lock:
        _disabled.add(name)


def reset_native_search_cache() -> None:
    """Forget resolved executables and disabled tools (tests, PATH changes)."""
    with _lock:
        _executables.clear()
        _disabled.clear()


def fzf_executable(cwd: Path | None = None) -> str | None:
    return _resolve("fzf", cwd=cwd)


def fd_executable(cwd: Path | None = None) -> str | None:
    # Debian and Ubuntu ship fd as `fdfind`.
    return _resolve("fd", "fdfind", cwd=cwd)


def _scrubbed_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in _SCRUBBED_ENV_VARS:
        env.pop(name, None)
    return env


def _spawn(
    cmd: list[str], *, stdin: IO[bytes] | None, cwd: Path | None
) -> subprocess.Popen[bytes] | None:
    try:
        return subprocess.Popen(
            cmd,
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            env=_scrubbed_env(),
        )
    except OSError:
        return None


def _kill(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    process.communicate()


def _collect(
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
    should_cancel: Callable[[], bool] | None,
) -> tuple[int, bytes] | None:
    while True:
        if (should_cancel and should_cancel()) or time.monotonic() > deadline:
            _kill(process)
            return None
        try:
            stdout, _ = process.communicate(timeout=_POLL_INTERVAL_S)
        except subprocess.TimeoutExpired:
            continue
        return process.returncode, stdout


def _run(
    cmd: list[str], *, stdin: bytes, should_cancel: Callable[[], bool] | None = None
) -> tuple[int, bytes] | None:
    # Feed the input from an unlinked temp file rather than a pipe: the tool
    # reads it at full speed, and Python never shuttles megabytes through
    # `communicate`'s write loop while also polling for cancellation.
    try:
        with tempfile.TemporaryFile() as stdin_file:
            stdin_file.write(stdin)
            stdin_file.seek(0)
            process = _spawn(cmd, stdin=stdin_file, cwd=None)
            if process is None:
                return None
            return _collect(
                process,
                deadline=time.monotonic() + _TIMEOUT_S,
                should_cancel=should_cancel,
            )
    except OSError:
        return None


def _run_concurrently(
    cmds: list[list[str]], *, cwd: Path, should_cancel: Callable[[], bool] | None = None
) -> list[tuple[int, bytes]] | None:
    processes: list[subprocess.Popen[bytes]] = []
    for cmd in cmds:
        process = _spawn(cmd, stdin=None, cwd=cwd)
        if process is None:
            for started in processes:
                _kill(started)
            return None
        processes.append(process)

    deadline = time.monotonic() + _TIMEOUT_S
    results: list[tuple[int, bytes]] = []
    for index, process in enumerate(processes):
        result = _collect(process, deadline=deadline, should_cancel=should_cancel)
        if result is None:
            for pending in processes[index + 1 :]:
                _kill(pending)
            return None
        results.append(result)
    return results


def fzf_filter(
    query: str,
    candidates: Sequence[str],
    *,
    scheme: str = "path",
    should_cancel: Callable[[], bool] | None = None,
) -> list[int] | None:
    """Rank ``candidates`` against ``query`` with ``fzf --filter``.

    Returns the indices of the matching candidates, best match first, or
    ``None`` when fzf cannot answer. Matching mirrors the pure-Python matcher:
    a case-insensitive subsequence match on the literal query (no extended
    search syntax, no latin-script normalisation).
    """
    fzf = fzf_executable()
    if fzf is None or not query:
        return None

    # Each record is "<candidate>\x1f<zero-padded index>" and fzf matches only
    # the first field, so results map back by slicing digits instead of by a
    # text lookup. A suffix (unlike a prefix) leaves fzf's path-aware
    # tiebreaks, and therefore its ordering, identical to plain candidates.
    width = len(str(len(candidates)))
    payload = "\0".join(
        f"{candidate}{_FIELD_SEPARATOR}{index:0{width}d}"
        for index, candidate in enumerate(candidates)
    )
    if payload.count(_FIELD_SEPARATOR) != len(candidates):
        return None

    result = _run(
        [
            fzf,
            f"--filter={query}",
            "--read0",
            "--print0",
            "--no-extended",
            "--ignore-case",
            "--literal",
            f"--scheme={scheme}",
            f"--delimiter={_FIELD_SEPARATOR}",
            "--nth=1",
        ],
        stdin=payload.encode("utf-8", "surrogateescape"),
        should_cancel=should_cancel,
    )
    if result is None:
        return None
    returncode, stdout = result
    if returncode == 1:  # ran fine, nothing matched
        return []
    if returncode != 0:
        if returncode == _USAGE_ERROR_EXIT_CODE:
            _disable("fzf")
        return None
    return [int(record[-width:]) for record in stdout.split(b"\0") if record]


def _default_ignore_file(patterns: Sequence[str]) -> Path | None:
    key = tuple(patterns)
    with _lock:
        if (cached := _ignore_files.get(key)) is not None:
            return cached
        try:
            fd, name = tempfile.mkstemp(prefix="vibe-file-index-", suffix=".ignore")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(patterns) + "\n")
        except OSError:
            return None
        path = _ignore_files[key] = Path(name)
        atexit.register(path.unlink, missing_ok=True)
        return path


def fd_list_entries(
    root: Path,
    default_ignore_patterns: Sequence[str],
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[str], list[str]] | None:
    """List ``(directories, other_entries)`` under ``root`` with fd.

    Paths are root-relative and use ``/``. Ignore semantics mirror the
    pure-Python walker: the default patterns, then the root ``.gitignore``
    (later patterns win, so a ``!pattern`` there re-includes a default), and
    nothing else -- no nested, global, or ``.fdignore`` rules.
    """
    fd = fd_executable(cwd=root)
    if fd is None:
        return None
    ignore_file = _default_ignore_file(default_ignore_patterns)
    if ignore_file is None:
        return None

    base = [
        fd,
        "--hidden",
        "--no-ignore",
        "--print0",
        "--ignore-file",
        str(ignore_file),
    ]
    if (root / ".gitignore").is_file():
        base += ["--ignore-file", ".gitignore"]

    results = _run_concurrently(
        [[*base, "--type", "d"], [*base, "--type", "f", "--type", "l"]],
        cwd=root,
        should_cancel=should_cancel,
    )
    if results is None:
        return None
    if any(returncode == _USAGE_ERROR_EXIT_CODE for returncode, _ in results):
        _disable("fd")
    if any(returncode != 0 for returncode, _ in results):
        return None
    (_, directories), (_, others) = results
    return _parse_fd_output(directories), _parse_fd_output(others)


def _parse_fd_output(stdout: bytes) -> list[str]:
    paths: list[str] = []
    for raw in stdout.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", "surrogateescape").replace(os.sep, "/")
        path = path.removeprefix("./").rstrip("/")
        if path:
            paths.append(path)
    return paths
