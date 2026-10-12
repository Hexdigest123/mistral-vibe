from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from vibe.app_server.models import (
    CompletedEffectState,
    EffectCallDisplay,
    EffectResultDisplay,
    FailedSessionStatus,
    IdleSessionStatus,
    PublicChildSession,
    PublicEffectEntry,
    PublicEntryGenerationStatus,
    RunningEffectState,
    RunningSessionStatus,
    SubagentEffectDetail,
    SubagentEffectInput,
    TokenUsage,
)
from vibe.cli.textual_ui.widgets.subagent_runs import (
    SubagentActivity,
    SubagentRunGroup,
    SubagentRunRow,
    SubagentRunStatus,
    effect_activity_text,
    format_duration,
    subagent_run_status,
)

NOW_MS = 1_700_000_100_000
STARTED_MS = 1_700_000_037_000  # 63s before NOW_MS


def _spawn(
    entry_id: str = "spawn-1",
    *,
    child_id: str | None = "child-1",
    name: str = "auth-audit",
    agent: str = "explore",
    task: str = "Inspect the auth module\nand report back",
    completed: bool = True,
) -> PublicEffectEntry:
    return PublicEffectEntry(
        id=entry_id,
        session_id="main",
        created_at=STARTED_MS,
        updated_at=STARTED_MS,
        generation_status=PublicEntryGenerationStatus.COMPLETED,
        title="Spawn",
        detail=SubagentEffectDetail(
            tool_name="subagent.spawn",
            display=EffectCallDisplay(
                summary=f"Spawning {name}",
                verb="Spawning",
                message=name,
                status_text="Spawning subagent",
            ),
            input=SubagentEffectInput(task=task, agent=agent),
            child_session_id=child_id,
        ),
        state=(
            CompletedEffectState(
                display=EffectResultDisplay(success=True, message=name)
            )
            if completed
            else RunningEffectState()
        ),
    )


def _child(
    status: object, *, tokens: int = 12_100, child_id: str = "child-1"
) -> PublicChildSession:
    return PublicChildSession.model_validate({
        "id": child_id,
        "name": "auth-audit",
        "agent_type": "explore",
        "status": status,
        "token_usage": TokenUsage(total_tokens=tokens),
        "created_at": STARTED_MS,
        "updated_at": NOW_MS,
    })


def _running() -> RunningSessionStatus:
    return RunningSessionStatus(active_turn_id="turn-1")


def _plain(row: SubagentRunRow) -> list[str]:
    return row.build_content(row.status, NOW_MS).plain.split("\n")


def test_format_duration() -> None:
    assert format_duration(4.9) == "4s"
    assert format_duration(63) == "1m 3s"
    assert format_duration(3720) == "1h 2m"


def test_status_follows_the_child_not_the_completed_spawn() -> None:
    # Unified harness spawns return at once; the child keeps running.
    entry = _spawn(completed=True)
    assert subagent_run_status(entry, _child(_running())) is SubagentRunStatus.RUNNING
    assert (
        subagent_run_status(entry, _child(IdleSessionStatus()))
        is SubagentRunStatus.DONE
    )
    # Idle before its first turn produced anything is still starting up.
    assert (
        subagent_run_status(entry, _child(IdleSessionStatus(), tokens=0))
        is SubagentRunStatus.RUNNING
    )
    # Without a child summary (legacy task tool) the effect decides.
    assert subagent_run_status(_spawn(completed=False), None).active
    assert subagent_run_status(entry, None) is SubagentRunStatus.DONE


def test_running_row_lists_recent_tool_uses_like_claude_code() -> None:
    row = SubagentRunRow(_spawn())
    row.apply_child(
        _child(_running()),
        SubagentActivity(
            tool_uses=7, recent=("Read vibe/auth.py", "Grep token", "Bash uv run")
        ),
    )

    lines = _plain(row)

    assert lines[0] == "● Explore(Auth Audit) · Inspect the auth module"
    assert lines[1] == "  ⎿  Read vibe/auth.py"
    assert lines[2] == "     Grep token"
    assert lines[3] == "     Bash uv run"
    assert lines[4] == "     +4 more tool uses · 12.1k tokens · 1m 3s"


def test_finished_row_collapses_to_a_done_summary() -> None:
    row = SubagentRunRow(_spawn())
    finished = _child(IdleSessionStatus()).model_copy(
        update={"updated_at": STARTED_MS + 63_000}
    )
    row.apply_child(finished, SubagentActivity(tool_uses=14, recent=("Read a.py",)))

    assert _plain(row) == [
        "● Explore(Auth Audit) · Inspect the auth module",
        "  ⎿  Done (14 tool uses · 12.1k tokens · 1m 3s)",
    ]


def test_failed_child_shows_its_error() -> None:
    row = SubagentRunRow(_spawn())
    row.apply_child(
        _child(FailedSessionStatus(message="rate\nlimited")), SubagentActivity()
    )

    assert _plain(row)[1] == "  ⎿  Failed: rate limited"


def test_tree_rows_draw_branches() -> None:
    first = SubagentRunRow(_spawn("spawn-1"))
    last = SubagentRunRow(_spawn("spawn-2", child_id="child-2", name="db-audit"))
    first.apply_child(_child(_running()), SubagentActivity(3, ("Read a.py",)))
    first.set_tree_position((0, 2))
    last.set_tree_position((1, 2))

    first_lines = _plain(first)
    last_lines = _plain(last)

    assert first_lines[0].startswith("  ├─ ● Explore(Auth Audit) · 3 tool uses")
    assert first_lines[1] == "  │  ⎿  Read a.py"
    assert last_lines[0].startswith("  └─ ● Explore(Db Audit)")
    assert last_lines[1] == "     ⎿  Done"


def test_effect_activity_text_prefers_the_settled_wording() -> None:
    entry = _spawn().model_copy(
        update={
            "detail": SubagentEffectDetail(
                tool_name="read_file",
                display=EffectCallDisplay(
                    summary="Reading x.py",
                    verb="Reading",
                    message="x.py",
                    settled_verb="Read",
                    status_text="Reading",
                ),
            )
        }
    )
    assert effect_activity_text(entry) == "Read x.py"
    running = entry.model_copy(update={"state": RunningEffectState()})
    assert effect_activity_text(running) == "Reading x.py"


class _GroupApp(App[None]):
    def __init__(self, group: SubagentRunGroup) -> None:
        super().__init__()
        self.group = group

    def compose(self) -> ComposeResult:
        yield self.group


@pytest.mark.asyncio
async def test_group_header_appears_with_parallel_agents() -> None:
    first = SubagentRunRow(_spawn("spawn-1", completed=False, child_id=None))
    group = SubagentRunGroup([first])
    app = _GroupApp(group)

    async with app.run_test() as pilot:
        await pilot.pause()
        header = group.query_one(".subagent-run-header", Static)
        assert not header.display
        assert first.tree_position is None

        second = SubagentRunRow(_spawn("spawn-2", completed=False, child_id=None))
        await group.add_row(second)
        await pilot.pause()

        assert header.display
        assert "Running 2 agents…" in str(header.content)
        assert first.tree_position == (0, 2)
        assert second.tree_position == (1, 2)


@pytest.mark.asyncio
async def test_clicking_a_row_asks_to_open_its_transcript() -> None:
    row = SubagentRunRow(_spawn())
    group = SubagentRunGroup([row])
    opened: list[str] = []

    class _App(_GroupApp):
        def on_subagent_run_row_open_requested(
            self, event: SubagentRunRow.OpenRequested
        ) -> None:
            opened.append(event.session_id)

    app = _App(group)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(SubagentRunRow)
        await pilot.pause()

    assert opened == ["child-1"]
