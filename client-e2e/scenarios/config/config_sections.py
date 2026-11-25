"""`/config` groups rows into the server's category sections, TTS among them."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot
from scenarios.slash_command._config_fixtures import field, fields_read

handshake = {
    "config/fields/read": fields_read(
        field("theme", "str", "dark", category="popular"),
        field("disable_all_telemetry", "bool", False, popular=False, category="fork"),
        field(
            "active_transcribe_model",
            "str",
            "voxtral-mini-latest",
            popular=False,
            category="voice",
        ),
        field("active_tts_model", "str", "voxtral-tts", popular=False, category="tts"),
        field("tts_models", "complex", {}, popular=False, category="tts"),
        field("api_timeout", "int", 60, popular=False, category="advanced"),
    )
}

screen_contains = (
    "Popular settings",
    "Fork features",
    "Voice",
    "TTS",
    "Active TTS model",
    "Advanced settings",
)

timeline: Timeline = ["/config\r", take_snapshot()]
