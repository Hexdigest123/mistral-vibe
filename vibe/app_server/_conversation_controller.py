"""The ``conversation/*`` API: a hands-free voice session with a Mistral voice agent.

Fork feature (AGENTS.md "Fork features"). The app server hosts the session and its
microphone (ADR 0018) and never imports the voice SDK before the user starts a
conversation; ``stop`` closes the session and releases the audio device. The voice
agent reaches the coding agent through three client tools. Each one is a round trip
to the client (``conversation/taskRequest`` out, ``conversation/taskResult`` back),
so the prompt runs through the client's ordinary submit path: its queue, its
approvals and the session's approval policy apply as they do for a typed prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from uuid import uuid4

from vibe.app_server._dispatch import DispatchResult, method_not_found
from vibe.app_server._model import ProtocolModel, validate_wire
from vibe.app_server.protocol import (
    CONVERSATION_STATE_METHOD,
    CONVERSATION_TASK_REQUEST_METHOD,
    CONVERSATION_TRANSCRIPT_METHOD,
    ConversationStartParams,
    ConversationStartResponse,
    ConversationStateParams,
    ConversationStopParams,
    ConversationStopResponse,
    ConversationTaskRequestParams,
    ConversationTaskResultParams,
    ConversationTaskResultResponse,
    ConversationTranscriptParams,
)
from vibe.observability.logging import logger

if TYPE_CHECKING:
    from vibe.core.config import VibeConfigSchema

__all__ = ["CONVERSATION_METHODS", "ConversationController"]

CONVERSATION_METHODS = frozenset({
    "conversation/start",
    "conversation/stop",
    "conversation/taskResult",
})

# A tool call answers within this, or says the task still runs; the agent then
# says so aloud and asks again. Under the tools' own 30 s timeout.
WAIT_SECONDS = 12.0
CANCEL_SECONDS = 5.0
# The utterance that started the task is transcribed about now: it must not end the first wait.
SPEECH_GRACE_SECONDS = 1.5
SPOKE_NOTE = (
    "The user spoke while you waited. Say something right now, even just that the task "
    "is still running, then call wait_for_task again."
)

MISSING_FEATURE = (
    "Conversation mode needs a build with the voice-agents feature: run `make features`, "
    "choose Conversation mode, then `make build`."
)

INSTRUCTIONS = """\
You are the voice of Mistral Vibe, a coding agent running in the user's terminal.
The user talks to you hands-free. You never write code yourself: you hand every
coding or repository request to the coding agent with run_task, then tell the user
what happened in one or two short spoken sentences. Never read code, paths or long
output aloud; summarise it. If run_task says the task is still running, say so
briefly and call wait_for_task again. If the status is needs_approval, tell the user
the coding agent waits for their approval on the keyboard, then keep waiting. Use
cancel_task when the user asks you to stop. Answer plain conversation yourself.
Speak the language the user speaks to you, unless they asked for one ("only English",
"sprich Deutsch"): that choice wins over the language they speak, for every reply
and result, until they ask for another. Pass the user's request to run_task in their
own words, whatever the language.
Never stay silent after the user spoke: while a task runs, "still working on it" is a
good answer, and so is "I'm waiting for your approval". When the user asks for progress or the result, call wait_for_task: never answer from
memory, the status changes while you talk. Approval is only pending while the tool
says needs_approval; a running status means the user already approved. If the
instructions below name a finished task result, tell the user that result at your
next turn, in the conversation's language, unless you already did.
"""

RESULT_NOTE = """

The coding agent finished task {task_id} ({status}). Its result, to tell the user
now in one or two short spoken sentences:
{text}
"""


class VoiceSession(Protocol):
    """The part of the SDK's session the controller drives."""

    def on(self, event: str, handler: Callable[[Any], Any]) -> Callable[[], None]: ...
    async def connect(self) -> None: ...
    async def wait(self) -> None: ...
    async def close(self) -> None: ...
    async def update(self, *, instructions: str) -> Any: ...


type TaskHandler = Callable[..., Awaitable[dict[str, Any]]]
type SessionOpener = Callable[
    [VibeConfigSchema, dict[str, TaskHandler]], Awaitable[VoiceSession]
]
type Notifier = Callable[[str, ProtocolModel], Awaitable[None]]

_SETTLED = frozenset({"done", "failed", "interrupted"})


@dataclass
class _Task:
    id: str
    status: str = "running"
    text: str = ""
    changed: asyncio.Event = field(default_factory=asyncio.Event)


def _build_tools(function_tool: Any, handlers: Mapping[str, Any]) -> list[Any]:
    """The voice agent's tools; a tool without a filler sends none (the backend refuses an empty text)."""
    return [
        function_tool(
            name=name,
            description=(handler.__doc__ or "").strip(),
            # The backend rejects an empty filler text: no filler is None.
            filler={"text": filler} if filler else None,
            timeout_ms=30000,
        )(handler)
        for name, filler, handler in (
            ("run_task", "On it.", handlers["run_task"]),
            ("wait_for_task", None, handlers["wait_for_task"]),
            ("cancel_task", "Stopping.", handlers["cancel_task"]),
        )
    ]


MAX_ECHO_DELAY_MS = 500


def _clamped_audio_interface(base: type) -> Any:
    """The SDK's audio interface with an echo delay the canceller accepts (0-500 ms).

    A slow output device (Bluetooth, a deep audio-server buffer) reports more than 500 ms
    and the canceller then refuses it, which ended the conversation at once.
    """

    class ClampedAudioInterface(base):  # type: ignore[misc, valid-type]
        def _current_echo_delay_ms(self) -> int:
            return max(0, min(super()._current_echo_delay_ms(), MAX_ECHO_DELAY_MS))

    return ClampedAudioInterface()


async def _open_real_session(
    config: VibeConfigSchema, handlers: dict[str, TaskHandler]
) -> VoiceSession:
    """Open the SDK's session; the imports stay here, out of the server's startup."""
    try:
        from mistralai.client import Mistral
        from mistralai.extra.voice_agents import DefaultAudioInterface, function_tool
    except ImportError as exc:
        raise RuntimeError(MISSING_FEATURE) from exc
    from vibe.app_server._credential_selection import cli_process_credentials
    from vibe.core.platform_auth import PlatformCredentialRequired
    from vibe.core.platform_auth._mistral import resolve_snapshot
    from vibe.utils.http import VibeAsyncHTTPClient, build_ssl_context

    provider = config.get_tts_provider_for_model(config.get_active_tts_model())
    snapshot = await resolve_snapshot(
        cli_process_credentials(provider.api_key_env_var), provider.api_base
    )
    if isinstance(snapshot, PlatformCredentialRequired):
        raise RuntimeError(
            f"Conversation mode needs an API key: set {provider.api_key_env_var}"
        )
    http = VibeAsyncHTTPClient(verify=build_ssl_context())
    http.follow_redirects = snapshot.follows_redirects
    client = Mistral(api_key="", server_url=provider.api_base, async_client=http)
    tools = _build_tools(function_tool, handlers)
    session = await client.audio.sessions.init(
        llm={"model": config.conversation_model},
        tts={"voice_id": config.conversation_voice_id},
        instructions=INSTRUCTIONS,
        tools=tools,
        audio_interface=_clamped_audio_interface(DefaultAudioInterface),
        http_headers=dict(snapshot.headers),
    )
    return cast(VoiceSession, session)


class ConversationController:
    """``conversation/start``, ``stop`` and ``taskResult`` over one voice session at a time."""

    def __init__(
        self,
        *,
        require_session: Callable[[str], None],
        config_getter: Callable[[], VibeConfigSchema],
        notify: Notifier,
        open_session: SessionOpener = _open_real_session,
    ) -> None:
        self._require_session = require_session
        self._config_getter = config_getter
        self._notify = notify
        self._open_session = open_session
        self._session: VoiceSession | None = None
        self._session_id: str | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._task: _Task | None = None
        self._noted = False
        self._noting: asyncio.Task[None] | None = None
        self._waiting_since: float | None = None
        self._spoke = False

    @property
    def active(self) -> bool:
        return self._session is not None

    async def _push(self, method: str, params: ProtocolModel) -> None:
        try:
            await self._notify(method, params)
        except Exception:
            logger.warning("Failed to emit %s", method, exc_info=True)

    async def _state(self, state: Any, error: str | None = None) -> None:
        if self._session_id is not None:
            await self._push(
                CONVERSATION_STATE_METHOD,
                ConversationStateParams(
                    session_id=self._session_id, state=state, error=error
                ),
            )

    # -- Lifecycle ──────────────────────────────────────────────────

    async def start(self, session_id: str) -> ConversationStartResponse:
        if self._session is not None:
            return ConversationStartResponse(ok=True)
        config = self._config_getter()
        if not config.conversation_mode_enabled:
            return ConversationStartResponse(
                ok=False, error="Conversation mode is off: turn it on in /voice."
            )
        self._session_id = session_id
        await self._state("connecting")
        handlers = {
            "run_task": self._run_task,
            "wait_for_task": self._wait_for_task,
            "cancel_task": self._cancel_task,
        }
        try:
            session = await self._open_session(config, handlers)
            self._bind(session)
            await session.connect()
        except Exception as exc:
            logger.warning("Conversation start failed", exc_info=True)
            await self._teardown(str(exc) or type(exc).__name__)
            return ConversationStartResponse(
                ok=False, error=str(exc) or type(exc).__name__
            )
        self._session = session
        self._watcher = asyncio.ensure_future(self._watch(session))
        await self._state("listening")
        return ConversationStartResponse(ok=True)

    def _bind(self, session: VoiceSession) -> None:
        session.on("transcript", self._on_transcript)
        session.on("agent_state_changed", self._on_state)
        session.on("error", self._on_error)

    def _on_transcript(self, event: Any) -> None:
        if self._session_id is None or event.role not in {"user", "assistant"}:
            return
        if (
            event.role == "user"
            and getattr(event, "final", True)
            and str(event.content).strip()
        ):
            self._user_spoke()
        asyncio.ensure_future(
            self._push(
                CONVERSATION_TRANSCRIPT_METHOD,
                ConversationTranscriptParams(
                    session_id=self._session_id,
                    role=event.role,
                    content=event.content,
                    final=bool(getattr(event, "final", True)),
                ),
            )
        )

    def _on_state(self, event: Any) -> None:
        state = str(getattr(event.state, "value", event.state))
        if state in {"listening", "thinking", "speaking"}:
            asyncio.ensure_future(self._state(state))

    def _on_error(self, event: Any) -> None:
        if getattr(event, "fatal", False):
            asyncio.ensure_future(self.stop(error=str(event.message)))

    async def _watch(self, session: VoiceSession) -> None:
        try:
            await session.wait()
        except Exception as exc:
            logger.warning("Conversation ended with an error", exc_info=True)
            await self.stop(error=str(exc))
            return
        if self._session is session:
            await self.stop()

    async def stop(self, *, error: str | None = None) -> ConversationStopResponse:
        await self._teardown(error)
        return ConversationStopResponse(ok=True)

    async def _teardown(self, error: str | None = None) -> None:
        session, self._session = self._session, None
        watcher, self._watcher = self._watcher, None
        task, self._task = self._task, None
        self._noted = False
        if self._noting is not None:
            self._noting.cancel()
            self._noting = None
        if task is not None:
            task.status = "interrupted"
            task.changed.set()
        if watcher is not None and watcher is not asyncio.current_task():
            watcher.cancel()
        if session is not None:
            try:
                await session.close()
            except Exception:
                logger.warning("Failed to close the voice session", exc_info=True)
        await self._state("stopped", error)
        self._session_id = None

    async def close(self) -> None:
        await self._teardown()

    # -- The voice agent's tools ────────────────────────────────────

    async def _ask_client(
        self, task: _Task, action: Literal["run", "cancel"], prompt: str = ""
    ) -> None:
        if self._session_id is not None:
            await self._push(
                CONVERSATION_TASK_REQUEST_METHOD,
                ConversationTaskRequestParams(
                    session_id=self._session_id,
                    task_id=task.id,
                    action=action,
                    prompt=prompt,
                ),
            )

    def _report(self, task: _Task) -> dict[str, Any]:
        return {"task_id": task.id, "status": task.status, "result": task.text}

    def _user_spoke(self) -> None:
        """The user said something: end the wait in flight so the agent can answer at once."""
        since, task = self._waiting_since, self._task
        if since is None or task is None:
            return
        if asyncio.get_running_loop().time() - since >= SPEECH_GRACE_SECONDS:
            self._spoke = True
            task.changed.set()

    async def _settle(self, task: _Task, seconds: float) -> dict[str, Any]:
        """Wait until the task ends, needs approval, the user speaks or `seconds` pass; then say where it stands."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        self._waiting_since, self._spoke = loop.time(), False
        try:
            while task.status not in _SETTLED:
                left = deadline - loop.time()
                if left <= 0:
                    break
                task.changed.clear()
                try:
                    await asyncio.wait_for(task.changed.wait(), left)
                except TimeoutError:
                    break
                if task.status == "needs_approval" or self._spoke:
                    break
        finally:
            self._waiting_since = None
        report = self._report(task)
        if self._spoke and task.status not in _SETTLED:
            report["note"] = SPOKE_NOTE
        return report

    async def _note(self, instructions: str) -> None:
        """Best effort: the live session takes new instructions at its next turn."""
        session = self._session
        if session is None:
            return
        try:
            await session.update(instructions=instructions)
        except Exception:
            logger.warning("Failed to update the voice instructions", exc_info=True)

    def _announce(self, task: _Task) -> None:
        """A finished result no waiting tool call may carry (the user talked over it): put it in the instructions."""
        note = RESULT_NOTE.format(task_id=task.id, status=task.status, text=task.text)
        self._noted = True
        self._noting = asyncio.ensure_future(self._note(INSTRUCTIONS + note))

    async def _run_task(self, request: str) -> dict[str, Any]:
        """Give the coding agent a coding or repository request in plain words, e.g. "run the tests and fix failures". Returns when it finishes, needs approval, or after about 20 seconds with status running."""
        if self._task is not None and self._task.status not in _SETTLED:
            return {**self._report(self._task), "status": "busy"}
        if self._noted:
            self._noted = False
            await self._note(INSTRUCTIONS)
        self._task = task = _Task(id=uuid4().hex[:8])
        await self._state("working")
        await self._ask_client(task, "run", request)
        return await self._settle(task, WAIT_SECONDS)

    async def _wait_for_task(self, task_id: str) -> dict[str, Any]:
        """Keep waiting for a task that was still running; give the task_id run_task returned."""
        task = self._task
        if task is None or task.id != task_id:
            return {"task_id": task_id, "status": "unknown", "result": "No such task."}
        return await self._settle(task, WAIT_SECONDS)

    async def _cancel_task(self, task_id: str) -> dict[str, Any]:
        """Stop the running task; give the task_id run_task returned."""
        task = self._task
        if task is None or task.id != task_id or task.status in _SETTLED:
            return {
                "task_id": task_id,
                "status": "unknown",
                "result": "Nothing is running.",
            }
        await self._ask_client(task, "cancel")
        return await self._settle(task, CANCEL_SECONDS)

    async def task_result(self, params: ConversationTaskResultParams) -> ProtocolModel:
        task = self._task
        if task is not None and task.id == params.task_id:
            task.status, task.text = params.status, params.text
            task.changed.set()
            if params.status in _SETTLED and self._session is not None:
                await self._state("thinking")
                self._announce(task)
        return ConversationTaskResultResponse(ok=True)

    # -- Routing ────────────────────────────────────────────────────

    async def dispatch(self, method: str, raw_params: dict[str, Any]) -> DispatchResult:
        match method:
            case "conversation/start":
                params = validate_wire(ConversationStartParams, raw_params)
                self._require_session(params.session_id)
                return DispatchResult(await self.start(params.session_id))
            case "conversation/stop":
                params = validate_wire(ConversationStopParams, raw_params)
                self._require_session(params.session_id)
                return DispatchResult(await self.stop())
            case "conversation/taskResult":
                params = validate_wire(ConversationTaskResultParams, raw_params)
                self._require_session(params.session_id)
                return DispatchResult(await self.task_result(params))
            case _:
                raise method_not_found(method)
