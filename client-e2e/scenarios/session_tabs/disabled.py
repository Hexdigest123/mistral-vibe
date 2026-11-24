"""With enable_session_tabs = false the tab keys and /tab stay inert, no tab bar shows."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.scenario import Timeline

_fixture = json.loads(FIXTURE_PATH.read_text())
_runtime = json.loads(json.dumps(_fixture["handshake"]["runtime/read"]))
_runtime["runtime"]["config"]["enableSessionTabs"] = False

handshake = {"runtime/read": _runtime}
screen_contains = ("Session tabs are off",)
screen_excludes = ("Tab switch tab",)

timeline: Timeline = ["/tab new\r", "\t"]
