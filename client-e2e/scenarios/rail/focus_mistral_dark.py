"""On a truecolor theme the focused rail item takes the hovered button tint, like the model name and the context gauge."""

from __future__ import annotations

import json

from e2e.app_server.config import FIXTURE_PATH
from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.rail._fixtures import CTRL_X, SETUP, handshake as _rail_handshake

env = {"VIBE_THEME": "mistral-dark"}
# Session tabs off: with them on, Ctrl+X arms the tab chord first and the rail
# letters this scenario snapshots need the feature's upstream path.
_runtime = json.loads(json.dumps(json.loads(FIXTURE_PATH.read_text())["handshake"]["runtime/read"]))
_runtime["runtime"]["config"]["enableSessionTabs"] = False
_runtime["runtime"]["config"]["theme"] = "mistral-dark"
handshake = {
    **_rail_handshake,
    "config/read": {"config": {"theme": "mistral-dark", "enableSessionTabs": False}},
    "runtime/read": _runtime,
}

timeline: Timeline = [*SETUP, CTRL_X, take_snapshot()]

screen_contains = ("a 1 agent · b 2 tasks · g goal 4m · d 1/3",)
