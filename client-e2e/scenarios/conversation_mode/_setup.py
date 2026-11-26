"""Shared handshake for conversation mode: the setting is on and the server accepts every call."""

from __future__ import annotations

from typing import Any

CTRL_X = "\x18"


def _runtime(policy: str) -> dict[str, Any]:
    return {
        "config": {"conversationModeEnabled": True},
        "activeApprovalPolicy": {"name": policy, "displayName": policy, "safety": "smart"},
    }


handshake: dict[str, Any] = {
    "config/read": {"config": {"conversationModeEnabled": True}},
    "runtime/read": {"runtime": {"config": {"conversationModeEnabled": True}}},
    "session/approvalPolicy/update": {"runtime": _runtime("smart-approve"), "status": "applied"},
    "conversation/start": {"ok": True},
    "conversation/stop": {"ok": True},
    "conversation/taskResult": {"ok": True},
}
