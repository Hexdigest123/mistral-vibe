"""With enable_session_tabs = false, Ctrl+X m still opens the model picker."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.scenario import Timeline, take_snapshot

_fixture = json.loads(FIXTURE_PATH.read_text())
_runtime = json.loads(json.dumps(_fixture["handshake"]["runtime/read"]))
_runtime["runtime"]["config"]["enableSessionTabs"] = False

handshake = {"runtime/read": _runtime}

timeline: Timeline = ["\x18", "m", take_snapshot()]
