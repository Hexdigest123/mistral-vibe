"""Inline, live subagent blocks for the transcript (Claude Code style).

A ``subagent.spawn`` effect renders as its own block instead of folding into a
collapsed tool group::

    ● Explore(auth-audit) · Inspect the auth module
      ⎿  Read vibe/core/auth.py
         Grep token
         +5 more tool uses · 12.1k tokens · 34s

Consecutive spawns (parallel agents) share one block drawn as a tree::

    ● Running 2 agents…
      ├─ Explore(auth) · 5 tool uses · 12.1k tokens · 34s
      │  ⎿  Read vibe/core/auth.py
      └─ Plan(refactor) · 3 tool uses · 8k tokens · 21s
         ⎿  Done

Rows only ever change their text in place (``layout=False``) unless their line
count changes, so the live ticking never forces a reflow of a long history.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum, auto
import re
import time
from typing import Any, TypeGuard

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static

from vibe.app_server.models import (
    ArchivedSessionStatus,
    BlockedSessionStatus,
    CancelledEffectState,
    CompletedEffectState,
    FailedEffectState,
    FailedSessionStatus,
    IdleSessionStatus,
    PublicChildSession,
    PublicEffectEntry,
    PublicHistoryEntry,
    RunningSessionStatus,
    SkippedEffectState,
    SubagentEffectDetail,
)
from vibe.cli.textual_ui.count_format import format_compact_count
from vibe.cli.textual_ui.widgets.collapsible import ClickWithoutDragMixin

BULLET = "●"
RESULT_ELBOW = "⎿"
RECENT_TOOL_USES = 3
TICK_INTERVAL_S = 0.5
_MUTED = "$text-muted"
_WORD_BOUNDARY = re.compile(r"[-_]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Timestamps below this are seconds, not milliseconds (1e11 ms is 1973).
_MS_THRESHOLD = 100_000_000_000


def agent_display_name(value: str) -> str:
    if " " in value:
        return value
    return " ".join(
        word.capitalize() if word.islower() else word
        for word in _WORD_BOUNDARY.split(value)
        if word
    )


def _agent_title(agent_type: str, name: str) -> Content:
    """``Explore(Auth Audit)``: the same identity the agent list shows."""
    agent_label = agent_display_name(agent_type)
    name_label = agent_display_name(name) if name else ""
    if not name_label or name_label == agent_label:
        return Content.styled(agent_label, "bold")
    return Content.assemble((agent_label, "bold"), f"({name_label})")


def is_subagent_run_entry(entry: PublicHistoryEntry) -> TypeGuard[PublicEffectEntry]:
    return isinstance(entry, PublicEffectEntry) and isinstance(
        entry.detail, SubagentEffectDetail
    )


def format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    if total < 60:  # noqa: PLR2004
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def effect_activity_text(entry: PublicEffectEntry) -> str:
    """One-line description of a child's tool use, e.g. ``Read vibe/app.py``."""
    display = entry.detail.display
    if isinstance(
        entry.state, CompletedEffectState | SkippedEffectState | CancelledEffectState
    ):
        verb = display.settled_verb or display.verb
        message = display.settled_message or display.message or display.summary
    else:
        verb = display.verb
        message = display.message if display.message is not None else display.summary
    text = f"{verb} {message}" if verb and message else (message or verb)
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class SubagentActivity:
    tool_uses: int = 0
    recent: tuple[str, ...] = ()


class SubagentRunStatus(StrEnum):
    RUNNING = auto()
    WAITING = auto()
    DONE = auto()
    FAILED = auto()
    STOPPED = auto()

    @property
    def active(self) -> bool:
        return self in {SubagentRunStatus.RUNNING, SubagentRunStatus.WAITING}

    @property
    def color(self) -> str:
        match self:
            case SubagentRunStatus.RUNNING | SubagentRunStatus.DONE:
                return "$success"
            case SubagentRunStatus.WAITING:
                return "$warning"
            case SubagentRunStatus.FAILED:
                return "$error"
            case SubagentRunStatus.STOPPED:
                return _MUTED


def child_run_status(child: PublicChildSession) -> SubagentRunStatus:
    match child.status:
        case RunningSessionStatus():
            return SubagentRunStatus.RUNNING
        case BlockedSessionStatus():
            return SubagentRunStatus.WAITING
        case FailedSessionStatus():
            return SubagentRunStatus.FAILED
        case ArchivedSessionStatus():
            return SubagentRunStatus.STOPPED
        case IdleSessionStatus() if child.token_usage.total_tokens == 0:
            # Spawned but its first turn has not produced anything yet.
            return SubagentRunStatus.RUNNING
        case _:
            return SubagentRunStatus.DONE


def subagent_run_status(
    entry: PublicEffectEntry, child: PublicChildSession | None
) -> SubagentRunStatus:
    state = entry.state
    if isinstance(state, FailedEffectState) or (
        isinstance(state, CompletedEffectState) and not state.display.success
    ):
        return SubagentRunStatus.FAILED
    if child is not None:
        return child_run_status(child)
    match state:
        case CompletedEffectState():
            return SubagentRunStatus.DONE
        case CancelledEffectState() | SkippedEffectState():
            return SubagentRunStatus.STOPPED
        case _:
            return SubagentRunStatus.RUNNING


def _to_ms(value: int) -> int:
    return value * 1000 if value < _MS_THRESHOLD else value


def run_elapsed_s(
    entry: PublicEffectEntry | None,
    child: PublicChildSession | None,
    status: SubagentRunStatus,
    now_ms: int,
) -> float | None:
    if child is not None:
        start, end = child.created_at, child.updated_at
    elif entry is not None:
        start, end = entry.created_at, entry.updated_at
    else:
        return None
    start_ms = _to_ms(start)
    end_ms = now_ms if status.active else _to_ms(end)
    return max(end_ms - start_ms, 0) / 1000


def run_stats_text(
    activity: SubagentActivity,
    child: PublicChildSession | None,
    elapsed_s: float | None,
    *,
    include_tool_uses: bool = True,
) -> str:
    parts: list[str] = []
    if include_tool_uses and activity.tool_uses:
        noun = "tool use" if activity.tool_uses == 1 else "tool uses"
        parts.append(f"{activity.tool_uses} {noun}")
    if child is not None and child.token_usage.total_tokens:
        parts.append(f"{format_compact_count(child.token_usage.total_tokens)} tokens")
    if elapsed_s is not None:
        parts.append(format_duration(elapsed_s))
    return " · ".join(parts)


class SubagentRunRow(ClickWithoutDragMixin, Static):
    """One subagent: title line plus its live activity / outcome lines."""

    class Attached(Message):
        """Posted when the row knows (or changes) its child session id."""

        def __init__(self, row: SubagentRunRow) -> None:
            self.row = row
            super().__init__()

    class OpenRequested(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(self, entry: PublicEffectEntry, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.add_class("subagent-run-row")
        self._entry = entry
        self._child: PublicChildSession | None = None
        self._activity = SubagentActivity()
        self._tree_position: tuple[int, int] | None = None
        self._blink_on = True
        self._line_count = 0
        self._last_status: SubagentRunStatus | None = None

    @property
    def entry_id(self) -> str:
        return self._entry.id

    @property
    def child_session_id(self) -> str | None:
        detail = self._entry.detail
        if isinstance(detail, SubagentEffectDetail):
            return detail.child_session_id
        return None

    @property
    def status(self) -> SubagentRunStatus:
        return subagent_run_status(self._entry, self._child)

    @property
    def tree_position(self) -> tuple[int, int] | None:
        return self._tree_position

    def on_mount(self) -> None:
        self.render_row()
        self.post_message(self.Attached(self))

    def update_entry(self, entry: PublicEffectEntry) -> None:
        previous_child = self.child_session_id
        self._entry = entry
        self.render_row()
        if self.is_attached and self.child_session_id != previous_child:
            self.post_message(self.Attached(self))

    def apply_child(
        self, child: PublicChildSession | None, activity: SubagentActivity
    ) -> None:
        if child is not None:
            self._child = child
        self._activity = activity
        self.render_row()

    def set_tree_position(self, position: tuple[int, int] | None) -> None:
        if position == self._tree_position:
            return
        self._tree_position = position
        self.render_row()

    def tick(self, blink_on: bool) -> None:
        self._blink_on = blink_on
        if self.status.active:
            self.render_row()

    def render_row(self) -> None:
        status = self.status
        content = self.build_content(status, int(time.time() * 1000))
        lines = content.plain.count("\n") + 1
        # Same line count means same height: skip the (whole screen) relayout.
        self.update(content, layout=lines != self._line_count)
        self._line_count = lines
        if status is not self._last_status:
            self._last_status = status
            if isinstance(self.parent, SubagentRunGroup):
                self.parent.refresh_state()

    def _title(self) -> Content:
        detail = self._entry.detail
        agent = (
            detail.input.agent
            if isinstance(detail, SubagentEffectDetail) and detail.input is not None
            else (
                detail.agent_name
                if isinstance(detail, SubagentEffectDetail) and detail.agent_name
                else "Agent"
            )
        )
        name = (
            self._child.name
            if self._child is not None
            else (detail.display.message or "")
        )
        return _agent_title(agent, name)

    def _task_preview(self) -> str:
        detail = self._entry.detail
        if not isinstance(detail, SubagentEffectDetail) or detail.input is None:
            return ""
        first_line = next(
            (line.strip() for line in detail.input.task.splitlines() if line.strip()),
            "",
        )
        return first_line

    def _bullet(self, status: SubagentRunStatus) -> Content:
        if status.active and not self._blink_on:
            return Content.styled(BULLET, _MUTED)
        return Content.styled(BULLET, status.color)

    def _outcome(
        self, status: SubagentRunStatus, stats: str, *, compact: bool
    ) -> Content:
        match status:
            case SubagentRunStatus.DONE:
                label = "Done" if compact or not stats else f"Done ({stats})"
                return Content.styled(label, "$success")
            case SubagentRunStatus.FAILED:
                return Content.styled(f"Failed: {self._failure_message()}", "$error")
            case SubagentRunStatus.STOPPED:
                label = "Stopped" if compact or not stats else f"Stopped ({stats})"
                return Content.styled(label, _MUTED)
            case SubagentRunStatus.WAITING:
                return Content.styled("Waiting for input", "$warning")
            case SubagentRunStatus.RUNNING:
                return Content.styled("Starting…", _MUTED)

    def _failure_message(self) -> str:
        if self._child is not None and isinstance(
            self._child.status, FailedSessionStatus
        ):
            return " ".join(self._child.status.message.split())
        state = self._entry.state
        if isinstance(state, FailedEffectState):
            return " ".join(state.error.message.split())
        if isinstance(state, CompletedEffectState):
            return " ".join(state.display.text.split())
        return "unknown error"

    def build_content(self, status: SubagentRunStatus, now_ms: int) -> Content:
        elapsed = run_elapsed_s(self._entry, self._child, status, now_ms)
        if self._tree_position is None:
            return self._build_single(status, elapsed)
        return self._build_tree_row(status, elapsed, *self._tree_position)

    def _build_single(
        self, status: SubagentRunStatus, elapsed: float | None
    ) -> Content:
        title = Content.assemble(self._bullet(status), " ", self._title())
        if task := self._task_preview():
            title = Content.assemble(title, Content.styled(f" · {task}", _MUTED))
        stats = run_stats_text(self._activity, self._child, elapsed)
        indent = "  "
        elbow_text = f"{indent}{RESULT_ELBOW}  "
        elbow = Content.styled(elbow_text, _MUTED)
        continuation = " " * len(elbow_text)
        lines: list[Content] = [title]
        recent = self._activity.recent if status.active else ()
        if recent:
            for index, text in enumerate(recent):
                prefix = elbow_text if index == 0 else continuation
                lines.append(Content.styled(f"{prefix}{text}", _MUTED))
            hidden = self._activity.tool_uses - len(recent)
            summary_stats = run_stats_text(
                self._activity, self._child, elapsed, include_tool_uses=False
            )
            summary_parts = [f"+{hidden} more tool uses"] if hidden > 0 else []
            if status is SubagentRunStatus.WAITING:
                summary_parts.insert(0, "waiting for input")
            if summary_stats:
                summary_parts.append(summary_stats)
            if summary_parts:
                lines.append(
                    Content.styled(f"{continuation}{' · '.join(summary_parts)}", _MUTED)
                )
        elif status.active:
            line = Content.assemble(elbow, self._outcome(status, stats, compact=True))
            if stats:
                line = Content.assemble(line, Content.styled(f" · {stats}", _MUTED))
            lines.append(line)
        else:
            lines.append(
                Content.assemble(elbow, self._outcome(status, stats, compact=False))
            )
        return Content("\n").join(lines)

    def _build_tree_row(
        self, status: SubagentRunStatus, elapsed: float | None, index: int, count: int
    ) -> Content:
        last = index == count - 1
        branch = "  └─ " if last else "  ├─ "
        stem = "     " if last else "  │  "
        stats = run_stats_text(self._activity, self._child, elapsed)
        title = Content.assemble(
            Content.styled(branch, _MUTED), self._bullet(status), " ", self._title()
        )
        if stats:
            title = Content.assemble(title, Content.styled(f" · {stats}", _MUTED))
        elbow = Content.styled(f"{stem}{RESULT_ELBOW}  ", _MUTED)
        if status is SubagentRunStatus.RUNNING and self._activity.recent:
            detail = Content.styled(self._activity.recent[-1], _MUTED)
        else:
            detail = self._outcome(status, stats, compact=True)
        return Content("\n").join([title, Content.assemble(elbow, detail)])

    async def on_click(self, event: events.Click) -> None:
        if self._click_is_passive(event):
            return
        session_id = self.child_session_id
        if session_id is None:
            return
        event.stop()
        self.post_message(self.OpenRequested(session_id))


class SubagentRunGroup(Vertical):
    """Consecutive subagent spawns; draws a tree once there are two or more."""

    def __init__(self, rows: Iterable[SubagentRunRow] = (), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class("subagent-run-group")
        self._header = Static("", classes="subagent-run-header")
        self._header.display = False
        self._pending_rows = list(rows)
        self._timer: Timer | None = None
        self._blink_on = True

    def compose(self) -> ComposeResult:
        yield self._header
        yield from self._pending_rows

    @property
    def rows(self) -> list[SubagentRunRow]:
        if not self.is_mounted:
            return list(self._pending_rows)
        return [child for child in self.children if isinstance(child, SubagentRunRow)]

    def on_mount(self) -> None:
        self._pending_rows = []
        self.refresh_state()

    def on_unmount(self) -> None:
        self._stop_timer()

    def add_pending_row(self, row: SubagentRunRow) -> None:
        """Add a row before the group is mounted (history rebuilds)."""
        if self.is_mounted:
            raise RuntimeError("use add_row() once the group is mounted")
        self._pending_rows.append(row)

    async def add_row(self, row: SubagentRunRow) -> None:
        await self.mount(row)
        self.refresh_state()

    def refresh_state(self) -> None:
        if not self.is_mounted:
            return
        rows = self.rows
        tree = len(rows) > 1
        if self._header.display != tree:
            self._header.display = tree
        for index, row in enumerate(rows):
            row.set_tree_position((index, len(rows)) if tree else None)
        self._update_header(rows)
        if any(row.status.active for row in rows):
            if self._timer is None:
                self._timer = self.set_interval(TICK_INTERVAL_S, self._tick)
        else:
            self._stop_timer()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._blink_on = not self._blink_on
        rows = self.rows
        for row in rows:
            row.tick(self._blink_on)
        self._update_header(rows)

    def _update_header(self, rows: list[SubagentRunRow]) -> None:
        if len(rows) < 2:  # noqa: PLR2004
            return
        statuses = [row.status for row in rows]
        active = sum(status.active for status in statuses)
        if active:
            color = SubagentRunStatus.RUNNING.color if self._blink_on else _MUTED
            label = f"Running {len(rows)} agents…"
            if active < len(rows):
                label = f"Running {len(rows)} agents… ({len(rows) - active} done)"
        else:
            failed = any(status is SubagentRunStatus.FAILED for status in statuses)
            color = "$error" if failed else "$success"
            label = f"{len(rows)} agents finished"
        self._header.update(
            Content.assemble(Content.styled(BULLET, color), " ", (label, "bold")),
            layout=False,
        )


class SubagentViewHeader(ClickWithoutDragMixin, Static):
    """Title bar of the read-only subagent transcript window."""

    class BackRequested(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._child: PublicChildSession | None = None
        self._activity = SubagentActivity()
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(1.0, self._render_header, pause=True)

    def show_child(
        self, child: PublicChildSession | None, activity: SubagentActivity
    ) -> None:
        self._child = child
        self._activity = activity
        self._render_header()
        if self._timer is not None:
            active = child is not None and child_run_status(child).active
            if active:
                self._timer.resume()
            else:
                self._timer.pause()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.pause()

    def _render_header(self) -> None:
        child = self._child
        back = Content.styled("‹ Main", "bold $primary")
        if child is None:
            self.update(Content.assemble(back, Content.styled(" · esc", _MUTED)))
            return
        status = child_run_status(child)
        elapsed = run_elapsed_s(None, child, status, int(time.time() * 1000))
        stats = run_stats_text(self._activity, child, elapsed)
        self.update(
            Content.assemble(
                back,
                Content.styled("  │  ", _MUTED),
                Content.styled(BULLET, status.color),
                " ",
                _agent_title(child.agent_type, child.name),
                Content.styled(f" · {status.value}", status.color),
                Content.styled(f" · {stats}" if stats else "", _MUTED),
            ),
            layout=False,
        )

    async def on_click(self, event: events.Click) -> None:
        if self._click_is_passive(event):
            return
        event.stop()
        self.post_message(self.BackRequested())
