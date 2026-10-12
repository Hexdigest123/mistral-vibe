from __future__ import annotations

import asyncio

import pytest

from vibe.app_server.models import (
    CompletedEffectState,
    EffectCallDisplay,
    EffectResultDisplay,
    GenericEffectDetail,
    IdleSessionStatus,
    PublicChildSession,
    PublicEffectEntry,
    PublicEntryGenerationStatus,
    PublicHistoryEntry,
    RunningSessionStatus,
    TokenUsage,
)
from vibe.cli.textual_ui.subagent_activity import (
    ACTIVITY_TAIL_LIMIT,
    FULL_HISTORY_LIMIT,
    SubagentActivityTracker,
)


def _tool_use(index: int) -> PublicEffectEntry:
    return PublicEffectEntry(
        id=f"effect-{index}",
        session_id="child-1",
        created_at=index,
        updated_at=index,
        generation_status=PublicEntryGenerationStatus.COMPLETED,
        title="Read",
        detail=GenericEffectDetail(
            tool_name="read_file",
            display=EffectCallDisplay(
                summary=f"Reading f{index}.py",
                verb="Reading",
                message=f"f{index}.py",
                settled_verb="Read",
                status_text="Reading",
            ),
        ),
        state=CompletedEffectState(
            display=EffectResultDisplay(success=True, message=f"f{index}.py")
        ),
    )


def _child(*, running: bool) -> PublicChildSession:
    return PublicChildSession(
        id="child-1",
        name="auth-audit",
        agent_type="explore",
        status=(
            RunningSessionStatus(active_turn_id="turn-1")
            if running
            else IdleSessionStatus()
        ),
        token_usage=TokenUsage(total_tokens=10),
        created_at=1,
        updated_at=2,
    )


class _FakeHistory:
    def __init__(self) -> None:
        self.entries: list[PublicHistoryEntry] = []
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, session_id: str, limit: int) -> list[PublicHistoryEntry]:
        self.calls.append((session_id, limit))
        return self.entries[-limit:]


async def _settle(tracker: SubagentActivityTracker) -> None:
    for _ in range(50):
        await asyncio.sleep(0)
        if not tracker._tasks:
            return
    await asyncio.gather(*tracker._tasks.values())


@pytest.mark.asyncio
async def test_running_child_reads_a_tail_and_counts_tool_uses() -> None:
    history = _FakeHistory()
    history.entries = [_tool_use(i) for i in range(5)]
    changes: list[str] = []
    tracker = SubagentActivityTracker(
        history, on_change=changes.append, min_interval_s=0
    )

    tracker.child_updated(_child(running=True))
    await _settle(tracker)

    assert history.calls == [("child-1", ACTIVITY_TAIL_LIMIT)]
    activity = tracker.activity("child-1")
    assert activity.tool_uses == 5
    assert activity.recent == ("Read f2.py", "Read f3.py", "Read f4.py")
    assert changes and changes[-1] == "child-1"


@pytest.mark.asyncio
async def test_tool_uses_accumulate_across_tails_and_settle_exactly() -> None:
    history = _FakeHistory()
    tracker = SubagentActivityTracker(history, min_interval_s=0)

    history.entries = [_tool_use(i) for i in range(3)]
    tracker.child_updated(_child(running=True))
    await _settle(tracker)
    history.entries += [_tool_use(i) for i in range(3, 6)]
    tracker.child_updated(_child(running=True))
    await _settle(tracker)
    assert tracker.activity("child-1").tool_uses == 6

    tracker.child_updated(_child(running=False))
    await _settle(tracker)

    # Settling reads the whole history once so the final count is exact.
    assert history.calls[-1] == ("child-1", FULL_HISTORY_LIMIT)
    assert tracker.activity("child-1").tool_uses == 6


@pytest.mark.asyncio
async def test_reads_are_throttled_and_coalesced() -> None:
    history = _FakeHistory()
    history.entries = [_tool_use(0)]
    tracker = SubagentActivityTracker(history, min_interval_s=0.05)

    tracker.child_updated(_child(running=True))
    await _settle(tracker)
    for _ in range(10):
        tracker.child_updated(_child(running=True))
    await _settle(tracker)

    # One read for the first update, one coalesced read for the burst.
    assert len(history.calls) == 2


@pytest.mark.asyncio
async def test_failed_reads_never_raise() -> None:
    async def broken(session_id: str, limit: int) -> list[PublicHistoryEntry]:
        raise RuntimeError("boom")

    tracker = SubagentActivityTracker(broken, min_interval_s=0)
    tracker.child_updated(_child(running=True))
    await _settle(tracker)

    assert tracker.activity("child-1").tool_uses == 0
    assert not tracker._tasks
