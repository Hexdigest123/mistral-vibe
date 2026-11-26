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
        self.instructions: list[str] = []

    async def update(self, *, instructions: str) -> None:
        self.instructions.append(instructions)

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
async def test_an_answered_approval_stops_reporting_needs_approval() -> None:
    """The client says `running` once the user approved: a later status check no longer claims approval is pending."""
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("search the news"))
    await _settle()
    [request] = rig.requests()
    await rig.controller.task_result(_result(request.task_id, "needs_approval"))
    assert (await call)["status"] == "needs_approval"
    waiting = asyncio.ensure_future(rig.handlers["wait_for_task"](request.task_id))
    await _settle()
    await rig.controller.task_result(_result(request.task_id, "running"))
    await _settle()
    assert not waiting.done()
    await rig.controller.task_result(_result(request.task_id, "done", "Two CVEs."))
    assert (await waiting)["status"] == "done"


@pytest.mark.asyncio
async def test_a_finished_task_is_put_in_the_instructions_for_the_next_turn() -> None:
    """The user talked over the waiting tool call: the result still reaches the voice agent."""
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    asyncio.ensure_future(rig.handlers["run_task"]("check the CVE news"))
    await _settle()
    [request] = rig.requests()
    await rig.controller.task_result(
        _result(request.task_id, "done", "Six critical CVEs.")
    )
    await _settle()
    [note] = rig.session.instructions
    assert note.startswith(module.INSTRUCTIONS) and "Six critical CVEs." in note
    asyncio.ensure_future(rig.handlers["run_task"]("another"))
    await _settle()
    assert rig.session.instructions[-1] == module.INSTRUCTIONS


@pytest.mark.asyncio
async def test_a_failing_instruction_update_does_not_break_the_task() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)

    async def broken(*, instructions: str) -> None:
        raise RuntimeError("agent not there")

    rig.session.update = broken  # type: ignore[method-assign]
    asyncio.ensure_future(rig.handlers["run_task"]("work"))
    await _settle()
    [request] = rig.requests()
    await rig.controller.task_result(_result(request.task_id, "done", "ok"))
    await _settle()
    assert rig.controller.active


def _say(rig: Rig, content: str, *, final: bool = True) -> None:
    rig.session.handlers["transcript"](
        SimpleNamespace(role="user", content=content, final=final)
    )


@pytest.mark.asyncio
async def test_the_user_speaking_ends_the_wait_so_the_agent_can_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent sat in a silent wait loop and left five questions unanswered."""
    monkeypatch.setattr(module, "SPEECH_GRACE_SECONDS", 0.0)
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("long search"))
    await _settle()
    _say(rig, "Wie weit bist du?", final=False)
    await _settle()
    assert not call.done()
    _say(rig, "Wie weit bist du?")
    result = await asyncio.wait_for(call, 1)
    assert result["status"] == "running" and result["note"] == module.SPOKE_NOTE


@pytest.mark.asyncio
async def test_the_request_being_transcribed_does_not_end_its_own_wait() -> None:
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("long search"))
    await _settle()
    _say(rig, "search for the Portainer version")
    await _settle()
    assert not call.done()
    [request] = rig.requests()
    await rig.controller.task_result(_result(request.task_id, "done", "2.45.4"))
    assert "note" not in await call


@pytest.mark.asyncio
async def test_a_finished_task_wins_over_the_user_speaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "SPEECH_GRACE_SECONDS", 0.0)
    rig = Rig()
    await rig.controller.start(_SESSION_ID)
    call = asyncio.ensure_future(rig.handlers["run_task"]("work"))
    await _settle()
    [request] = rig.requests()
    _say(rig, "hallo")
    await rig.controller.task_result(_result(request.task_id, "done", "ok"))
    result = await call
    assert result["status"] == "done" and "note" not in result


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


@pytest.mark.parametrize(
    ("reported", "sent"), [(53, 53), (900, 500), (500, 500), (-20, 0)]
)
def test_the_echo_delay_stays_in_the_range_the_canceller_accepts(
    reported: int, sent: int
) -> None:
    """A slow output device made the canceller refuse the delay and end the conversation."""

    class Base:
        def _current_echo_delay_ms(self) -> int:
            return reported

    assert module._clamped_audio_interface(Base)._current_echo_delay_ms() == sent


def test_the_real_audio_interface_is_clamped_against_the_installed_sdk() -> None:
    """The override targets a private SDK method: it must still exist and clamp a huge reported latency."""
    pytest.importorskip("mistralai.extra.voice_agents")
    from mistralai.extra.voice_agents import DefaultAudioInterface

    interface = module._clamped_audio_interface(DefaultAudioInterface)
    interface._last_output_delay_ms = 4_000_000
    assert interface._current_echo_delay_ms() == module.MAX_ECHO_DELAY_MS


def test_no_tool_sends_an_empty_filler_text() -> None:
    """The backend refuses ``filler.static.text == ""``: a silent tool sends no filler."""
    pytest.importorskip("mistralai.extra.voice_agents")
    from mistralai.extra.voice_agents import function_tool

    async def handler(**_: Any) -> str:
        return ""

    tools = module._build_tools(
        function_tool,
        {"run_task": handler, "wait_for_task": handler, "cancel_task": handler},
    )
    wire = {t.name: t.to_wire() if hasattr(t, "to_wire") else t for t in tools}
    assert set(wire) == {"run_task", "wait_for_task", "cancel_task"}
    for name, tool in wire.items():
        filler = tool.get("filler")
        assert filler is None or filler["text"], f"{name} sends an empty filler"
    assert "filler" not in wire["wait_for_task"]
