"""PR_SET_PDEATHSIG for child processes, so they die with the app-server.

A child spawned with ``start_new_session`` lives in its own session, so the
process-group kills on the graceful paths (the client killing the app-server's
group, a tool's group teardown) never reach it. If the app-server then dies
without running its cleanup (SIGKILL, OOM, the SIGTERM deadline's ``os._exit``),
such a child -- an MCP stdio server, a background process's PTY shell -- is
orphaned and keeps running.

``PR_SET_PDEATHSIG`` asks the kernel to signal the child when its parent dies,
however the parent dies, and it survives ``execve`` (only a setuid/setgid exec
clears it), so a trampoline that sets it and then execs the real command covers
the command itself. Python-level ``preexec_fn`` is not used in the app-server:
it is threaded, and a preexec running Python code after fork is unsafe there.
The trampolines here are fresh single-threaded processes, which may call
``prctl`` directly.

The parent's pid is passed in by the spawner, captured before the fork: if the
parent died before the child ran, the child's getppid() is already 1 and the
race check would compare against the wrong process. Same pattern as the
terminal client's ``die_with_parent`` in ``vibe/cli-rust/src/server/child.rs``.

Linux only: macOS has no ``prctl`` (the client's own parent-death signal is
Linux-only too). Windows needs nothing: the client spawns the app-server in a
Job Object that kills the whole tree when its handle closes.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import signal
import sys

_PR_SET_PDEATHSIG = 1

# The frozen bundle's entry point serves this module on a flag, as it does the
# PTY helper: a frozen build has no interpreter to run a script with.
INTERNAL_FLAG = "--internal-pdeathsig-exec"


def supported() -> bool:
    return sys.platform == "linux"


def set_pdeathsig(expected_ppid: int, signo: int = signal.SIGKILL) -> None:
    """SIGKILL this process when the parent dies; exit at once if it already
    did (``expected_ppid`` was read before the fork, so a mismatch means the
    parent is gone and no signal will ever come).
    """
    if not supported():
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(_PR_SET_PDEATHSIG, signo, 0, 0, 0)
    if os.getppid() != expected_ppid:
        os._exit(1)


def shim_argv(command: Sequence[str]) -> list[str]:
    """Wrap ``command`` in the exec shim so the spawned child dies with this
    process. Returns ``command`` unchanged where parent-death needs no help.
    """
    if not supported():
        return list(command)
    parent = str(os.getpid())
    if getattr(sys, "frozen", False):
        return [sys.executable, INTERNAL_FLAG, "--parent-pid", parent, "--", *command]
    return [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--parent-pid",
        parent,
        "--",
        *command,
    ]


def main(argv: list[str]) -> int:
    """The shim's entry point: ``[--parent-pid N] -- <command> [args...]``."""
    if argv[:1] == ["--parent-pid"]:
        try:
            expected_ppid = int(argv[1])
        except (IndexError, ValueError):
            expected_ppid = -1
        argv = argv[2:]
    else:
        expected_ppid = -1
    try:
        command = argv[argv.index("--") + 1 :]
    except ValueError:
        command = []
    if not command or expected_ppid < 0:
        print(
            f"usage: {INTERNAL_FLAG} --parent-pid N -- <command> [args...]",
            file=sys.stderr,
        )
        return 2
    set_pdeathsig(expected_ppid)
    try:
        os.execvp(command[0], command)
    except OSError as error:
        print(f"pdeathsig shim: cannot exec {command[0]!r}: {error}", file=sys.stderr)
        return 127
    return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
