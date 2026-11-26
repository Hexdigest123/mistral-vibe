"""Tests for the ``conversation/*`` app-server capability (fork feature)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from vibe.app_server import _conversation_controller as module
from vibe.app_server._conversation_controller import (
    CONVERSATION_METHODS,
    ConversationController,
)
from vibe.app_server._dispatch import RequestFailure
from vibe.app_server._model import ProtocolModel
from vibe.app_server.protocol import (
    CONVERSATION_STATE_METHOD,
    CONVERSATION_TASK_REQUEST_METHOD,
    CONVERSATION_TRANSCRIPT_METHOD,
    SERVER_METHODS,
    ConversationTaskResultParams,
)

_SESSION_ID = "session-1"


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], Any]] = {}
        self.connected = False
        self.closed = False
        self.ended = asyncio.Event()

    def on(self, event: str, handler: Callable[[Any], Any]) -> Callable[[], None]:
        self.handlers[event] = handler
        return lambda: None

    async def connect(self) -> None:
        self.connected = True

    async def wait(self) -> None:
        await self.ended.wait()

    async def close(self) -> None:
        self.closed = True
        self.ended.set()


class Rig:
    def __init__(self, *, enabled: bool = True, fail: Exception | None = None) -> None:
        self.session = FakeSession()
        self.notes: list[tuple[str, ProtocolModel]] = []
        self.handlers: dict[str, Any] = {}
        self.opened = 0
        config = SimpleNamespace(
            conversation_mode_enabled=enabled,
            conversation_model="mistral-small-latest",
            conversation_voice_id="gb_jane_neutral",
        )

        async def open_session(_config: Any, handlers: dict[str, Any]) -> FakeSession:
            self.opened += 1
            if fail is not None:
                raise fail
            self.handlers = handlers
            return self.session

        async def notify(method: str, params: ProtocolModel) -> None:
            self.notes.append((method, params))

        self.controller = ConversationController(
            require_session=lambda session_id: None,
            config_getter=lambda: config,  # type: ignore[arg-type, return-value]
            notify=notify,
            open_session=open_session,
        )

    def states(self) -> list[str]:
        return [p.state for m, p in self.notes if m == CONVERSATION_STATE_METHOD]  # type: ignore[attr-defined]

    def requests(self) -> list[Any]:
        return [p for m, p in self.notes if m == CONVERSATION_TASK_REQUEST_METHOD]


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _result(
    task_id: str,
    status: Literal["running", "needs_approval", "done", "failed", "interrupted"],
    text: str = "",
) -> ConversationTaskResultParams:
    return ConversationTaskResultParams(
        session_id=_SESSION_ID,
        task_id=task_id,
        status=status,
        text=text,  # type: ignore[arg-type]
    )


def test_methods_are_advertised() -> None:
    assert CONVERSATION_METHODS <= set(SERVER_METHODS)


@pytest.mark.asyncio
async def test_start_connects_and_reports_listening() -> None:
    rig = Rig()
    response = await rig.controller.start(_SESSION_ID)
    assert response.ok
    assert rig.session.connected
    assert rig.states() == ["connecting", "listening"]
    assert rig.controller.active


@pytest.mark.asyncio
async def test_start_while_active_does_not_open_a_second_session() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    assert (await rig.controller.start(_SESSION_ID)).ok
    assert rig.opened == 1


@pytest.mark.asyncio
async def test_start_refuses_when_the_setting_is_off() -> None:
    rig = Rig(enabled=False)
    response = await rig.controller.start(_SESSION_ID)
    assert not response.ok and "/voice" in (response.error or "")
    assert rig.opened == 0


@pytest.mark.asyncio
async def test_a_missing_feature_is_a_clear_error_and_stops_cleanly() -> None:
    rig = Rig(fail=RuntimeError(module.MISSING_FEATURE))
    response = await rig.controller.start(_SESSION_ID)
    assert not response.ok and "voice-agents" in (response.error or "")
    assert rig.states()[-1] == "stopped"
    assert not rig.controller.active


@pytest.mark.asyncio
async def test_stop_closes_the_session_and_reports_stopped() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    assert (await rig.controller.stop()).ok
    assert rig.session.closed
    assert rig.states()[-1] == "stopped"
    assert not rig.controller.active


@pytest.mark.asyncio
async def test_the_session_ending_on_its_own_stops_the_conversation() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    rig.session.ended.set()
    await _settle()
    assert not rig.controller.active
    assert rig.states()[-1] == "stopped"


@pytest.mark.asyncio
async def test_a_fatal_error_stops_it_with_the_message() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    rig.session.handlers["error"](SimpleNamespace(fatal=True, message="mic gone"))
    await _settle()
    last = [p for m, p in rig.notes if m == CONVERSATION_STATE_METHOD][-1]
    assert last.state == "stopped" and last.error == "mic gone"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_transcripts_and_agent_states_are_forwarded() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    rig.session.handlers["transcript"](
        SimpleNamespace(role="user", content="run the tests", final=True)
    )
    rig.session.handlers["agent_state_changed"](SimpleNamespace(state="speaking"))
    await _settle()
    transcripts = [p for m, p in rig.notes if m == CONVERSATION_TRANSCRIPT_METHOD]
    assert [(t.role, t.content) for t in transcripts] == [("user", "run the tests")]  # type: ignore[attr-defined]
    assert rig.states()[-1] == "speaking"


@pytest.mark.asyncio
async def test_run_task_asks_the_client_and_returns_its_result() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("run the tests"))
    await _settle()
    [request] = rig.requests()
    assert (request.action, request.prompt) == ("run", "run the tests")
    await rig.controller.task_result(
        _result(request.task_id, "done", "All 12 tests pass.")
    )
    result = await call
    assert result == {
        "task_id": request.task_id,
        "status": "done",
        "result": "All 12 tests pass.",
    }


@pytest.mark.asyncio
async def test_a_long_task_answers_running_then_wait_returns_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "WAIT_SECONDS", 0.05)
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    first = await rig.handlers["run_task"]("big refactor")
    assert first["status"] == "running"
    waiting = asyncio.ensure_future(rig.handlers["wait_for_task"](first["task_id"]))
    await _settle()
    await rig.controller.task_result(_result(first["task_id"], "done", "Refactored."))
    assert (await waiting)["status"] == "done"


@pytest.mark.asyncio
async def test_needs_approval_returns_early_so_the_agent_can_say_so() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("delete the build dir"))
    await _settle()
    [request] = rig.requests()
    await rig.controller.task_result(_result(request.task_id, "needs_approval"))
    assert (await call)["status"] == "needs_approval"


@pytest.mark.asyncio
async def test_a_second_task_while_one_runs_is_busy() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    asyncio.ensure_future(rig.handlers["run_task"]("first"))
    await _settle()
    again = await rig.handlers["run_task"]("second")
    assert again["status"] == "busy"
    assert len(rig.requests()) == 1


@pytest.mark.asyncio
async def test_cancel_asks_the_client_and_reports_interrupted() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    asyncio.ensure_future(rig.handlers["run_task"]("long job"))
    await _settle()
    [run] = rig.requests()
    cancel = asyncio.ensure_future(rig.handlers["cancel_task"](run.task_id))
    await _settle()
    assert [r.action for r in rig.requests()] == ["run", "cancel"]
    await rig.controller.task_result(_result(run.task_id, "interrupted"))
    assert (await cancel)["status"] == "interrupted"


@pytest.mark.asyncio
async def test_wait_for_an_unknown_task_says_so() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    assert (await rig.handlers["wait_for_task"]("nope"))["status"] == "unknown"


@pytest.mark.asyncio
async def test_stopping_ends_a_waiting_task_as_interrupted() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("work"))
    await _settle()
    await rig.controller.stop()
    assert (await call)["status"] == "interrupted"


@pytest.mark.asyncio
async def test_dispatch_routes_and_rejects_unknown_methods() -> None:
    rig = Rig()
    started = await rig.controller.dispatch(
        "conversation/start", {"sessionId": _SESSION_ID}
    )
    assert started.response.ok  # type: ignore[attr-defined]
    stopped = await rig.controller.dispatch(
        "conversation/stop", {"sessionId": _SESSION_ID}
    )
    assert stopped.response.ok  # type: ignore[attr-defined]
    with pytest.raises(RequestFailure):
        await rig.controller.dispatch("conversation/nope", {"sessionId": _SESSION_ID})
