"""Fork feature: `/model refresh` without a `discover = true` provider says what to configure."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

handshake = {"models/refresh": {"entries": [], "totalModels": 0, "errors": []}}
request_methods = {"models/refresh"}
timeline: Timeline = ["/model refresh\r", take_snapshot()]
screen_contains = ("No provider has discover = true in config.toml",)
