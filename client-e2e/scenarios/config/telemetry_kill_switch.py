"""The telemetry kill switch row is flagged dangerous; arming it warns and writes /disable_all_telemetry."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.slash_command._config_fixtures import field, fields_read

kill_switch = field(
    "disable_all_telemetry",
    "bool",
    False,
    layers=[("default", False)],
)
kill_switch["dangerous"] = True
kill_switch["description"] = (
    "DANGEROUS: fully disable ALL telemetry regardless of enable_telemetry and "
    "delete the telemetry stored on disk. May violate the Terms of Service and "
    "can get the account banned."
)

handshake = {
    "config/fields/read": fields_read(
        kill_switch, field("enable_telemetry", "bool", True)
    ),
    "config/write": {"runtime": {"config": {"disableAllTelemetry": True}}},
}

request_methods = frozenset({"config/write"})
screen_contains = ("disable_all_telemetry", "Dangerous")

# Open /config, search the kill switch (Enter opens its editor), flip False -> True, save.
timeline: Timeline = [
    "/config\r",
    "/disable_all\r",
    take_snapshot("edit"),
    "\x1b[A",
    "\r",
    take_snapshot("armed"),
]
