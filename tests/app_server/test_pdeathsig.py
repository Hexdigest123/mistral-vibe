"""PR_SET_PDEATHSIG: a process Vibe starts dies with Vibe, however Vibe dies.

The terminal client already does this for the app-server itself (see
``vibe/cli-rust/src/server/child.rs`` ``die_with_parent``); these tests cover
the app-server's own children — MCP stdio servers above all — which live in
their own sessions and so are beyond every process-group kill.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import sys
import time

from mcp.client.stdio import StdioServerParameters
import pytest

from mistralai_vibe_local_harness.vibe import _pdeathsig

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="PR_SET_PDEATHSIG is Linux-only"
)

FIXTURES = Path(__file__).parent / "fixtures"
_SHIM_PATH = str(Path(_pdeathsig.__file__).resolve())

# Spawns the command (under the parent-death shim when USE_SHIM=1), prints the
# child's pid, then SIGKILLs itself: plays the app-server dying without
# running any cleanup. The shim's --parent-pid must be this process's pid, so
# the argv is built here, not in the test process.
_SPAWNER = """
import os, signal, subprocess, sys
command = sys.argv[2:]
if os.environ.get("USE_SHIM"):
    command = [sys.executable, "-I", sys.argv[1], "--parent-pid", str(os.getpid()), "--", *command]
process = subprocess.Popen(command)
print(process.pid, flush=True)
os.kill(os.getpid(), signal.SIGKILL)
"""


async def _wait_reaped(
    process: asyncio.subprocess.Process, timeout: float = 10.0
) -> None:
    # process.wait() would hang: the grandchild inherits the stdout pipe, so
    # the pipe never reaches EOF. The child watcher sets returncode instead.
    deadline = time.monotonic() + timeout
    while process.returncode is None and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert process.returncode is not None


async def _spawn_and_die(command: list[str], *, use_shim: bool) -> int:
    env = {**os.environ, "USE_SHIM": "1" if use_shim else ""}
    spawner = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _SPAWNER,
        _SHIM_PATH,
        *command,
        stdout=asyncio.subprocess.PIPE,
        env=env,
    )
    assert spawner.stdout is not None
    line = await asyncio.wait_for(spawner.stdout.readline(), timeout=10)
    await _wait_reaped(spawner)
    assert spawner.returncode == -signal.SIGKILL
    return int(line)


async def _alive(pid: int) -> bool:
    # kill(pid, 0) also succeeds on a zombie, and a reparented orphan is one
    # until its new parent reaps it: read the state instead.
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            stat = handle.read()
    except OSError:
        return False
    state = stat[stat.rindex(b")") + 2 :].split()[0]
    return state != b"Z"


async def _wait_dead(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not await _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not await _alive(pid)


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_shimmed_child_dies_with_a_killed_parent() -> None:
    pid = await _spawn_and_die(["sleep", "60"], use_shim=True)
    assert await _wait_dead(pid), f"shimmed child {pid} survived its parent's SIGKILL"


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_plain_child_survives_a_killed_parent() -> None:
    """Control: without the shim the same child is orphaned, not killed."""
    pid = await _spawn_and_die(["sleep", "60"], use_shim=False)
    try:
        assert await _alive(pid)
    finally:
        os.kill(pid, signal.SIGKILL)
    assert await _wait_dead(pid)


@pytest.mark.asyncio
async def test_harness_stdio_connection_wraps_command_in_the_shim() -> None:
    """The harness's MCP stdio spawn goes through the parent-death shim."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from mistralai_vibe_local_harness.vibe._mcp_models import ResolvedMCPServerConfig
    import mistralai_vibe_local_harness.vibe._mcp_transport as transport

    captured: dict[str, StdioServerParameters] = {}

    class _FakeStdio:
        async def __aenter__(self) -> tuple[object, object]:
            return MagicMock(), MagicMock()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    def fake_stdio_client(
        params: StdioServerParameters, *, errlog: object = None
    ) -> _FakeStdio:
        captured["params"] = params
        return _FakeStdio()

    class _FakeSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._session = MagicMock()
            self._session.initialize = AsyncMock()

        async def __aenter__(self) -> MagicMock:
            return self._session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    server = ResolvedMCPServerConfig(
        name="fake", transport="stdio", command="node", args=("server.js",)
    )
    with (
        patch.object(transport, "stdio_client", fake_stdio_client),
        patch.object(transport, "ClientSession", _FakeSession),
    ):
        connection = await transport.UnifiedMCPTransportFactory().open_stdio(
            server, sampling_callback=None
        )
        await connection.aclose()

    params = captured["params"]
    if sys.platform == "linux":
        assert params.command == sys.executable
        assert list(params.args)[-3:] == ["--", "node", "server.js"]
    else:
        assert params.command == "node"
        assert list(params.args) == ["server.js"]


@pytest.mark.timeout(90)
@pytest.mark.asyncio
async def test_mcp_stdio_server_dies_with_a_killed_app_server() -> None:
    """End to end: a stdio MCP server opened through the harness's transport
    factory is gone once the process that opened it is SIGKILLed.
    """
    spawner = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FIXTURES / "pdeathsig_stdio_spawner.py"),
        stdout=asyncio.subprocess.PIPE,
    )
    assert spawner.stdout is not None
    line = await asyncio.wait_for(spawner.stdout.readline(), timeout=60)
    await _wait_reaped(spawner)
    assert spawner.returncode == -signal.SIGKILL
    pids = [int(part) for part in line.split()]
    assert pids
    for pid in pids:
        assert await _wait_dead(pid), (
            f"MCP stdio server pid {pid} survived the app-server's SIGKILL"
        )
