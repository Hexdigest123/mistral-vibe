"""Live per-child stats behind the inline subagent blocks.

`ChildSessionUpdated` carries a child's status and token usage but not what it
is doing, so while a child runs this reads the tail of its history (throttled,
one in-flight read per child) to count tool uses and surface the latest ones.
When a child settles, one final read of its whole history makes the count exact.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import time
from weakref import WeakSet

from vibe.app_server.models import (
    PublicChildSession,
    PublicEffectEntry,
    PublicHistoryEntry,
)
from vibe.cli.textual_ui.widgets.subagent_runs import (
    RECENT_TOOL_USES,
    SubagentActivity,
    SubagentRunRow,
    child_run_status,
    effect_activity_text,
)
from vibe.observability.logging import logger

HistoryReader = Callable[[str, int], Awaitable[Sequence[PublicHistoryEntry]]]
ChildLookup = Callable[[str], PublicChildSession | None]

ACTIVITY_TAIL_LIMIT = 40
# The session/read page maximum; a shorter page is the complete history.
FULL_HISTORY_LIMIT = 500
MIN_READ_INTERVAL_S = 0.5
MAX_CONCURRENT_READS = 2

_EMPTY = SubagentActivity()


class SubagentActivityTracker:
    def __init__(
        self,
        read_history: HistoryReader,
        *,
        child_lookup: ChildLookup | None = None,
        on_change: Callable[[str], None] | None = None,
        min_interval_s: float = MIN_READ_INTERVAL_S,
    ) -> None:
        self._read_history = read_history
        self._child_lookup = child_lookup
        self._on_change = on_change
        self._min_interval_s = min_interval_s
        self._children: dict[str, PublicChildSession] = {}
        self._activity: dict[str, SubagentActivity] = {}
        self._seen_effects: dict[str, set[str]] = {}
        self._rows: dict[str, WeakSet[SubagentRunRow]] = {}
        self._pending: dict[str, bool] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_read: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_READS)

    def child(self, session_id: str) -> PublicChildSession | None:
        child = self._children.get(session_id)
        if child is None and self._child_lookup is not None:
            child = self._child_lookup(session_id)
            if child is not None:
                self._children[session_id] = child
        return child

    def activity(self, session_id: str) -> SubagentActivity:
        return self._activity.get(session_id, _EMPTY)

    def register(self, row: SubagentRunRow) -> None:
        session_id = row.child_session_id
        if session_id is None:
            return
        self._rows.setdefault(session_id, WeakSet()).add(row)
        child = self.child(session_id)
        row.apply_child(child, self.activity(session_id))
        if session_id not in self._activity:
            # A row from a resumed transcript: one read fills in its stats.
            active = child is not None and child_run_status(child).active
            self._schedule(session_id, full=not active)

    def child_updated(self, child: PublicChildSession) -> None:
        previous = self._children.get(child.id)
        self._children[child.id] = child
        self._push(child.id)
        if child_run_status(child).active:
            self._schedule(child.id, full=False)
        elif previous is not None and child_run_status(previous).active:
            self._schedule(child.id, full=True)

    async def reset(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._children.clear()
        self._activity.clear()
        self._seen_effects.clear()
        self._rows.clear()
        self._pending.clear()
        self._tasks.clear()
        self._last_read.clear()

    def _schedule(self, session_id: str, *, full: bool) -> None:
        self._pending[session_id] = self._pending.get(session_id, False) or full
        if session_id in self._tasks:
            return
        self._tasks[session_id] = asyncio.create_task(
            self._drain(session_id), name=f"subagent-activity-{session_id}"
        )

    async def _drain(self, session_id: str) -> None:
        try:
            while session_id in self._pending:
                wait = self._min_interval_s - (
                    time.monotonic() - self._last_read.get(session_id, float("-inf"))
                )
                if wait > 0:
                    await asyncio.sleep(wait)
                full = self._pending.pop(session_id, False)
                limit = FULL_HISTORY_LIMIT if full else ACTIVITY_TAIL_LIMIT
                async with self._semaphore:
                    history = await self._read_history(session_id, limit)
                self._last_read[session_id] = time.monotonic()
                self._ingest(
                    session_id, history, complete=full and len(history) < limit
                )
                self._push(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stats are decoration: a failed read must never disturb the chat.
            logger.debug(
                "Failed to read subagent activity %s", session_id, exc_info=True
            )
        finally:
            self._tasks.pop(session_id, None)

    def _ingest(
        self, session_id: str, history: Sequence[PublicHistoryEntry], *, complete: bool
    ) -> None:
        effects = [entry for entry in history if isinstance(entry, PublicEffectEntry)]
        seen = self._seen_effects.setdefault(session_id, set())
        if complete:
            seen.clear()
        seen.update(entry.id for entry in effects)
        previous = self._activity.get(session_id, _EMPTY)
        recent = (
            tuple(effect_activity_text(entry) for entry in effects[-RECENT_TOOL_USES:])
            if effects
            else previous.recent
        )
        self._activity[session_id] = SubagentActivity(
            tool_uses=len(seen), recent=recent
        )

    def _push(self, session_id: str) -> None:
        child = self.child(session_id)
        activity = self.activity(session_id)
        for row in list(self._rows.get(session_id, ())):
            if row.is_attached:
                row.apply_child(child, activity)
        if self._on_change is not None:
            self._on_change(session_id)
