"""Open a real MCP stdio server through the harness, print its pid, die hard.

Used by tests/app_server/test_pdeathsig.py: the spawner plays the app-server,
the fake server plays an MCP stdio child (a node process in production). The
spawner SIGKILLs itself right after printing the server's pid, so the test can
assert the kernel's PR_SET_PDEATHSIG took the server down with it.
"""

from __future__ import annotations

import os
import signal
import sys

import anyio

from mistralai_vibe_local_harness.vibe._mcp_models import ResolvedMCPServerConfig
from mistralai_vibe_local_harness.vibe._mcp_transport import UnifiedMCPTransportFactory

FAKE_SERVER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fake_local_mcp_server.py"
)


def _server_pids() -> list[int]:
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read()
        except OSError:
            continue
        if b"fake_local_mcp_server.py" in cmdline:
            pids.append(int(entry))
    return pids


async def amain() -> None:
    server = ResolvedMCPServerConfig(
        name="fake", transport="stdio", command=sys.executable, args=(FAKE_SERVER,)
    )
    factory = UnifiedMCPTransportFactory()
    connection = await factory.open_stdio(server, sampling_callback=None)
    tools = await connection.list_tools()
    assert tools, "fake server listed no tools"
    pids = _server_pids()
    assert pids, "no fake server process found in /proc"
    print(" ".join(str(pid) for pid in pids), flush=True)
    os.kill(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    anyio.run(amain)
