"""A session whose channel closes while its turn runs keeps running, parked in
the process's ``OpenSessions``, and a ``session/resume`` on another channel of
the process attaches to it.

A session runs on its channel's ``ChannelRuntime`` (host, link, catalogs) and
reaches its client only through the link. Attaching swaps the two channels'
runtimes and repoints the link, so the live session moves as a whole; the
attaching channel's own, unused host goes to the closed channel and is shut
down.

Fork feature (AGENTS.md "Fork features"), ADR 0022: a connection that attaches
another session while its own has turn work parks it the same way, on a holder
of its own, so the old session keeps running and a later ``session/resume`` of
it, from this connection or another, attaches it live again.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from vibe.app_server import _left_turns
from vibe.app_server._dispatch import RequestFailure
from vibe.app_server._execution import cancel_tasks
from vibe.app_server._platform_credential_lenders import AccountKey, account_key
from vibe.app_server._session_backend_port import (
    SessionBackend,
    SessionBackendError,
    SessionBackendHostClientLoss,
    SessionBackendHostLeaseWatch,
    SessionBackendTurnWork,
)
from vibe.app_server.models import BlockedSessionStatus, RunningSessionStatus
from vibe.app_server.protocol import (
    ClientCapabilities,
    EventNotificationParams,
    ProtocolErrorCode,
    SessionReadParams,
    SessionReadResponse,
    SessionResumeParams,
    TurnInterruptParams,
)

if TYPE_CHECKING:
    from vibe.app_server._open_sessions import OpenSessions, ParkedSession
    from vibe.app_server.server import AppServer

logger = logging.getLogger(__name__)

_INTERRUPT_SETTLE_S = 5.0
_INTERRUPT_POLL_S = 0.05


class ParkedChannel:
    def __init__(self, server: AppServer) -> None:
        self.server = server

    def has_turn_work(self) -> bool:
        return _has_turn_work(self.server._root)

    async def stop(self) -> None:
        await self.server._close_root()


def _has_turn_work(root: SessionBackend | None) -> bool:
    return isinstance(root, SessionBackendTurnWork) and root.has_turn_work


def park_running_session(server: AppServer, open_sessions: OpenSessions) -> bool:
    root = server._root
    if root is None or not _has_turn_work(root):
        return False
    open_sessions.park(root.session_id, ParkedChannel(server))
    return True


def may_park_on_switch(server: AppServer) -> bool:
    """Whether the connection's client asked to keep its running session when
    it attaches another. Plugin client tools stay bound to the first link, so
    a connection declaring them never parks.
    """
    capabilities = server._client_capabilities
    return (
        capabilities.park_running_session
        and not capabilities.agent_plugins
        and not capabilities.client_tool_definitions
    )


class SwitchAway:
    """The running session a connection leaves while it attaches another.

    Its runtime (host, link) moves to ``holder``, so it keeps running with no
    client; ``detach`` then stops forwarding its events, ``park`` registers it
    for a later attach and ``abort`` takes everything back when the attach
    failed.
    """

    def __init__(
        self,
        server: AppServer,
        holder: AppServer,
        root: SessionBackend,
        open_sessions: OpenSessions,
    ) -> None:
        self.server = server
        self.holder = holder
        self.root = root
        self._open_sessions = open_sessions
        self._detached = False
        self.watches_artifacts = False

    async def detach(self) -> None:
        """The connection forwards no more of the session's events and holds
        no root: the new session replaces it without stopping this one.
        """
        server, session_id = self.server, self.root.session_id
        events = server._backend_event_task
        server._backend_event_task = None
        server._backend_event_backend = None
        if events is not None:
            await cancel_tasks([events], label="parked session events")
        server._root = None
        # What the session announced while the attach ran is in its history
        # still; replayed, it would reach the new session's stream.
        server._pending_notifications = [
            notification
            for notification in server._pending_notifications
            if not _is_event_of(notification.params, session_id)
        ]
        # Delivered to the client before it left: a refusal of one is no
        # rejection of the callback, which is sent again when the session is
        # attached again.
        for delivery in server._callback_deliveries.requests.values():
            delivery.answered = True
        _carry_watermark(server, self.holder, session_id)
        self._detached = True

    def park(self) -> None:
        self.server._switch_parked.add(self.root.session_id)
        self._open_sessions.park(self.root.session_id, ParkedChannel(self.holder))

    async def abort(self) -> None:
        """The attach failed: the connection runs its session again."""
        server, holder = self.server, self.holder
        server._stop_artifact_subscription()
        _swap_runtime(server, holder)
        holder._root = None
        await _follow_host(server, watches_artifacts=self.watches_artifacts)
        try:
            await holder._session_backend_host.shutdown()
        except Exception:
            logger.warning("Could not shut down an unused session host", exc_info=True)
        if self._detached:
            await _forward_again(server, self.root)


_RESUME_HISTORY_LIMIT = 200


async def _forward_again(server: AppServer, root: SessionBackend) -> None:
    """The connection holds ``root`` again, after a failed attach, and forwards
    its events.
    """
    try:
        await server._activate_backend(root, _RESUME_HISTORY_LIMIT)
    except Exception:
        logger.warning(
            "Could not forward the events of session %s again",
            root.session_id,
            exc_info=True,
        )
        server._root = root


async def begin_switch_away(
    server: AppServer, open_sessions: OpenSessions, target_session_id: str | None
) -> SwitchAway | None:
    """Move the connection's running session to a holder of its own, with a
    fresh runtime for the connection, before it opens ``target_session_id``;
    None when nothing is to be kept and the open replaces the session as ever.
    """
    root = server._root
    if (
        root is None
        or server._spawn_holder is None
        or not may_park_on_switch(server)
        or not _has_turn_work(root)
        or root.session_id == target_session_id
    ):
        return None
    holder = server._spawn_holder()
    _adopt_connection(server, holder)
    away = SwitchAway(server, holder, root, open_sessions)
    away.watches_artifacts = server._unsubscribe_artifacts is not None
    server._stop_artifact_subscription()
    _swap_runtime(server, holder)
    holder._root = root
    await _follow_host(server, watches_artifacts=away.watches_artifacts)
    return away


async def _follow_host(server: AppServer, *, watches_artifacts: bool) -> None:
    """The connection's host-bound subscriptions follow its runtime's host."""
    if watches_artifacts:
        server._subscribe_artifacts()
    host = server._session_backend_host
    if isinstance(host, SessionBackendHostLeaseWatch):
        try:
            await server._leases.follow(host)
        except Exception:
            logger.warning("Could not follow the new host's leases", exc_info=True)


def _adopt_connection(server: AppServer, holder: AppServer) -> None:
    """The holder answers for the session as the connection does: the same
    client, account and sign-in, and no way to reach the client itself.
    """
    holder._initialization = server._initialization
    holder._client_info = server._client_info
    holder._client_capabilities = server._client_capabilities
    holder._client_account = server._client_account
    holder._client_instance = server._client_instance
    holder._platform_credentials = server._platform_credentials
    holder._credential_selection = server._credential_selection
    holder._lending = server._lending
    holder._transport = None


def _carry_watermark(source: AppServer, target: AppServer, session_id: str) -> None:
    mark = source._event_watermark(session_id)
    if mark > target._event_watermark(session_id):
        target._event_watermarks[session_id] = mark


def _is_event_of(params: object, session_id: str) -> bool:
    return isinstance(params, EventNotificationParams) and (
        params.session_id == session_id
    )


def _account(server: AppServer) -> AccountKey | None:
    account = server._client_account
    return None if account is None else account_key(account)


def _still_busy(session_id: str) -> RequestFailure:
    # As the store answers a session another holder has open.
    return RequestFailure(
        ProtocolErrorCode.CONFLICT,
        f"Session is already open: {session_id}",
        {"harnessCode": "session_busy", "details": {"session_id": session_id}},
    )


async def _settled(
    server: AppServer, open_sessions: OpenSessions, session_id: str
) -> ParkedSession | None:
    """The process's own resume of it, a stop or another attach in flight
    settles first: the session is then parked again, attached elsewhere
    (busy), or stopped (opened from the store). The waits share the deadline
    the process's own resume has, so a resume that overruns it fails busy.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _left_turns.RESUME_TIMEOUT_S
    try:
        async with asyncio.timeout_at(deadline):
            while True:
                if (
                    open_sessions.resuming(session_id)
                    and server._left_turn_session != session_id
                ):
                    await open_sessions.wait_resumed(session_id)
                    continue
                if (parked := open_sessions.parked(session_id)) is not None:
                    return parked
                if not open_sessions.settling(session_id):
                    return None
                await open_sessions.wait_stopped(session_id)
    except TimeoutError:
        raise _still_busy(session_id) from None


async def attach_parked(
    server: AppServer, open_sessions: OpenSessions, params: SessionResumeParams
) -> SessionReadResponse | None:
    """The parked session attached to ``server``; None when no closed channel
    left it running. The session runs on as it is: only the history page and
    ``interruptLeftTurn`` of the resume apply.
    """
    session_id = params.session_id
    while True:
        parked = await _settled(server, open_sessions, session_id)
        if parked is None or not isinstance(parked, ParkedChannel):
            return None
        holder = parked.server
        root = holder._root
        if root is None:
            return None
        # Checked while it is still parked: a refused attach must leave it so.
        await _check_attach(server, holder, root, params)
        # Another attach, or the process's own resume, may have taken it
        # during the checks: look again.
        if open_sessions.parked(session_id) is parked and (
            not open_sessions.resuming(session_id)
            or server._left_turn_session == session_id
        ):
            open_sessions.take_parked(session_id)
            break
    if params.interrupt_left_turn:
        try:
            await interrupt_running_turn(root)
            # What the interrupt left open must be answerable here too.
            await server._validate_open_callback_capabilities("session/resume", root)
        except BaseException:
            open_sessions.park(params.session_id, parked)
            raise
    current = server._root
    watches_artifacts = server._unsubscribe_artifacts is not None
    server._stop_artifact_subscription()
    away = await _exchange_runtimes(server, holder, open_sessions)
    try:
        response = await server._activate_lifecycle_backend(
            "session/resume", root, params.history_limit
        )
    except BaseException:
        backend_events = server._backend_event_task
        server._backend_event_task = None
        server._backend_event_backend = None
        if backend_events is not None:
            await cancel_tasks([backend_events], label="unattached session events")
        server._root = None
        _swap_runtime(server, holder)
        holder._root = root
        open_sessions.park(params.session_id, parked)
        if current is not None:
            await _forward_again(server, current)
        await _follow_host(server, watches_artifacts=watches_artifacts)
        raise
    _carry_watermark(holder, server, params.session_id)
    open_sessions.attached(params.session_id)
    if isinstance(server._session_backend_host, SessionBackendHostClientLoss):
        server._session_backend_host.mark_client_reconnected()
    await _follow_host(server, watches_artifacts=watches_artifacts)
    if away is not None:
        # The holder runs the session the connection left: it keeps its host.
        away.park()
        return response
    try:
        await holder._session_backend_host.shutdown()
    except Exception:
        logger.warning("Could not shut down an unused session host", exc_info=True)
    return response


async def _exchange_runtimes(
    server: AppServer, holder: AppServer, open_sessions: OpenSessions
) -> SwitchAway | None:
    """The connection takes the parked session's runtime. The session it runs
    now goes to the holder, still running, if it has turn work; else it is
    replaced as an attach always did.
    """
    current = server._root
    _swap_runtime(server, holder)
    if current is None or not _has_turn_work(current):
        holder._root = None
        return None
    _adopt_connection(server, holder)
    away = SwitchAway(server, holder, current, open_sessions)
    holder._root = current
    await away.detach()
    return away


async def interrupt_running_turn(root: SessionBackend) -> None:
    """End the running turn, and wait a bounded time for it to settle, so the
    attach that follows shows it ended.
    """
    state = await root.read(
        SessionReadParams(session_id=root.session_id, history=None, turns=None)
    )
    status = state.state.session.status
    if not isinstance(status, RunningSessionStatus | BlockedSessionStatus):
        return
    try:
        result = await root.interrupt_turn(
            TurnInterruptParams(
                session_id=root.session_id, expected_turn_id=status.active_turn_id
            )
        )
    except SessionBackendError as exc:
        # The turn may have ended while the session attached; any other
        # failure fails the attach, which parks the session again.
        if exc.code not in {ProtocolErrorCode.STALE_TURN, ProtocolErrorCode.CONFLICT}:
            raise
        logger.info("The turn of session %s ended first", root.session_id)
        return
    if result.after_response is not None:
        result.after_response()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _INTERRUPT_SETTLE_S
    # Only the interrupted turn: a follow-up queued behind it may run on.
    while await _active_turn(root) == status.active_turn_id:
        if loop.time() >= deadline:
            logger.warning("The interrupted turn of %s did not settle", root.session_id)
            return
        await asyncio.sleep(_INTERRUPT_POLL_S)


async def _active_turn(root: SessionBackend) -> str | None:
    state = await root.read(
        SessionReadParams(session_id=root.session_id, history=None, turns=None)
    )
    status = state.state.session.status
    if isinstance(status, RunningSessionStatus | BlockedSessionStatus):
        return status.active_turn_id
    return None


async def _check_attach(
    server: AppServer,
    holder: AppServer,
    root: SessionBackend,
    params: SessionResumeParams,
) -> None:
    # Fork feature (AGENTS.md "Fork features"), ADR 0022: a client that keeps
    # its running session when it attaches another also attaches this one over
    # the session it has; any other holds one connection to one session.
    if server._root is not None and not may_park_on_switch(server):
        raise RequestFailure(
            ProtocolErrorCode.CONFLICT,
            "Resume a session that runs with no connection on a connection of its own",
        )
    if _client_tools(holder._client_capabilities) != _client_tools(
        server._client_capabilities
    ):
        raise RequestFailure(
            ProtocolErrorCode.CONFLICT,
            "The session runs with client tools this connection did not declare",
        )
    if _account(holder) != _account(server):
        raise RequestFailure(
            ProtocolErrorCode.CONFLICT,
            "The session runs for another account than this connection's",
        )
    if not params.interrupt_left_turn:
        await server._validate_open_callback_capabilities("session/resume", root)


def _swap_runtime(server: AppServer, other: AppServer) -> None:
    server._runtime, other._runtime = other._runtime, server._runtime
    server._runtime.link.server = server
    other._runtime.link.server = other


def _client_tools(
    capabilities: ClientCapabilities,
) -> tuple[list[str], list[str], list[str]]:
    return (
        sorted(capabilities.client_tools),
        sorted(plugin.model_dump_json() for plugin in capabilities.agent_plugins),
        sorted(tool.model_dump_json() for tool in capabilities.client_tool_definitions),
    )


__all__ = [
    "ParkedChannel",
    "SwitchAway",
    "attach_parked",
    "begin_switch_away",
    "interrupt_running_turn",
    "may_park_on_switch",
    "park_running_session",
]
