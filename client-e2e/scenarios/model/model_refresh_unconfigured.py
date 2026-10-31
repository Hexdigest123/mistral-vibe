"""Fork feature: `/model refresh` without a `discover = true` provider says what to configure."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

handshake = {"models/refresh": {"entries": [], "totalModels": 0, "errors": []}}
request_methods = {"models/refresh"}
capture_startup = False
timeline: Timeline = ["/model refresh\r"]
screen_contains = ("No provider has discover = true in config.toml",)
