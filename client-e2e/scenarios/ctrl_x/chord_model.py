"""Ctrl+X m opens the model picker, as /model does."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline, take_snapshot

timeline: Timeline = ["\x18", "m", take_snapshot()]
