"""Saving with Enter keeps the same setting selected for the next edit."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

screen_contains = ("┌─ Enable telemetry ",)
timeline: Timeline = ["/config\r", "\x1b[B" * 9 + "\r", "\r", "\r"]
