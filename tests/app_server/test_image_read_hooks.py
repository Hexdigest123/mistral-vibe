from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mistralai_vibe_local_harness.vibe")

from mistralai_vibe_local_harness.protocol import (
    RustAlwaysHookSelector,
    RustHarnessHookBinding,
    RustHookToolCall,
    RustPostToolCallHookInput,
    RustProtocolError,
    RustRuntimeBuiltinToolCall,
    RustToolFailureResult,
    RustToolKeysHookSelector,
    RustToolSuccessResult,
)
from mistralai_vibe_local_harness.vibe import (
    CompiledHooks,
    HookContext,
    LocalRuntimeAdapterConfig,
)
from pydantic import BaseModel

from vibe.app_server._image_read_hooks import (
    IMAGE_DESCRIBE_HOOK_BINDING_ID,
    ImageDescribePort,
    image_describe_hook,
    merge_image_describe_hook,
)
from vibe.utils.images import MAX_IMAGE_BYTES

_DESCRIPTION = "a red error dialog"


class _ReadResult(BaseModel):
    """The read_file structured content, validated like the UI projection does."""

    path: str
    content: str
    file_size_bytes: int
    returned_bytes: int
    offset: int
    lines_read: int
    was_truncated: bool


def _read(result: RustToolSuccessResult) -> _ReadResult:
    assert isinstance(result.structured_content, dict)
    return _ReadResult.model_validate(result.structured_content)


def _assert_mojibake(tool_result: object) -> None:
    # Every passthrough keeps the read exactly as the runtime produced it.
    assert isinstance(tool_result, RustToolSuccessResult)
    assert _read(tool_result).content == "mojibake"


async def _describes_everything(path: Path) -> str | None:
    return _DESCRIPTION


def _context(
    tmp_path: Path, *, describer: object | None = _describes_everything
) -> HookContext:
    return HookContext(
        config=LocalRuntimeAdapterConfig(
            cwd=tmp_path,
            workspace_roots=(tmp_path,),
            image_describer=describer,  # type: ignore[arg-type]
        ),
        messages=(),
        session_id="session-1",
    )


def _read_call(path: str) -> RustHookToolCall:
    return RustHookToolCall(
        action_id="action-1",
        call_id="call-1",
        call=RustRuntimeBuiltinToolCall(
            name="file_system.read_file", arguments={"path": path}
        ),
    )


def _hook_input(
    call: RustHookToolCall, result: RustToolSuccessResult | RustToolFailureResult
) -> RustPostToolCallHookInput:
    return RustPostToolCallHookInput(tool_call=call, tool_result=result)


def _success(path: Path) -> RustToolSuccessResult:
    return RustToolSuccessResult(
        structured_content={
            "path": str(path),
            "content": "mojibake",
            "file_size_bytes": 12,
            "returned_bytes": 7,
            "offset": 0,
            "lines_read": 1,
            "was_truncated": True,
        }
    )


def _image(tmp_path: Path, name: str = "shot.png", size: int | None = None) -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (size or 16))
    return path


@pytest.mark.asyncio
async def test_a_read_image_is_replaced_by_its_description(tmp_path: Path) -> None:
    image = _image(tmp_path)

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), _success(image)), _context(tmp_path)
    )

    rewritten = result.output.tool_result
    assert isinstance(rewritten, RustToolSuccessResult)
    read = _read(rewritten)
    assert read.content == _DESCRIPTION
    assert read.offset == 0
    assert read.lines_read == 1
    assert read.returned_bytes == len(_DESCRIPTION)
    assert read.was_truncated is False
    # Honest file facts survive the rewrite.
    assert read.path == str(image)
    assert read.file_size_bytes == 12


@pytest.mark.asyncio
async def test_a_session_without_a_describer_passes_through(tmp_path: Path) -> None:
    image = _image(tmp_path)

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), _success(image)),
        _context(tmp_path, describer=None),
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_a_describer_with_nothing_to_say_passes_through(tmp_path: Path) -> None:
    # A session whose active model sees images, or has no vision fallback.
    image = _image(tmp_path)

    async def no_fallback(path: Path) -> str | None:
        return None

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), _success(image)),
        _context(tmp_path, describer=no_fallback),
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_a_non_image_read_passes_through(tmp_path: Path) -> None:
    text = tmp_path / "notes.md"
    text.write_text("hello", encoding="utf-8")

    result = await image_describe_hook(
        _hook_input(_read_call(str(text)), _success(text)), _context(tmp_path)
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_a_failed_read_passes_through(tmp_path: Path) -> None:
    image = _image(tmp_path)
    failure = RustToolFailureResult(
        error=RustProtocolError(code="tool_failed", message="boom", retryable=False)
    )

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), failure), _context(tmp_path)
    )

    assert result.output.tool_result is failure


@pytest.mark.asyncio
async def test_an_oversized_image_passes_through(tmp_path: Path) -> None:
    image = _image(tmp_path, size=MAX_IMAGE_BYTES + 1)

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), _success(image)), _context(tmp_path)
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_a_missing_image_passes_through(tmp_path: Path) -> None:
    missing = tmp_path / "gone.png"

    result = await image_describe_hook(
        _hook_input(_read_call(str(missing)), _success(missing)), _context(tmp_path)
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_a_crashing_describer_does_not_break_the_read(tmp_path: Path) -> None:
    image = _image(tmp_path)

    async def boom(path: Path) -> str | None:
        raise RuntimeError("describer exploded")

    result = await image_describe_hook(
        _hook_input(_read_call(str(image)), _success(image)),
        _context(tmp_path, describer=boom),
    )

    _assert_mojibake(result.output.tool_result)


@pytest.mark.asyncio
async def test_the_port_delegates_to_the_bound_describer(tmp_path: Path) -> None:
    class FakeDescriber:
        async def describe_file(self, path: Path) -> str | None:
            return _DESCRIPTION

    port = ImageDescribePort()
    assert await port.describe(tmp_path) is None

    port.bind(FakeDescriber())  # type: ignore[arg-type]
    assert await port.describe(tmp_path) == _DESCRIPTION

    port.unbind()
    assert await port.describe(tmp_path) is None


def test_merge_binds_only_the_binding() -> None:
    merged = merge_image_describe_hook(CompiledHooks())
    assert [binding.id for binding in merged.bindings] == [
        IMAGE_DESCRIBE_HOOK_BINDING_ID
    ]
    binding = merged.bindings[0]
    assert binding.point == "post_tool_call"
    # The handler stays Host-global: a session's handler map is the foreign
    # channel, which surfaces public run notices a builtin must not emit.
    assert not merged.handlers.post_tool_call


def test_merge_scopes_the_binding_to_read_file() -> None:
    merged = merge_image_describe_hook(CompiledHooks())
    selector = merged.bindings[0].selector
    assert isinstance(selector, RustToolKeysHookSelector)
    [(key)] = selector.tool_keys
    assert (key.target, key.qualified_name) == ("filesystem", "file_system.read_file")


def test_merge_takes_an_order_unique_against_existing_bindings() -> None:
    foreign = RustHarnessHookBinding(
        id="builtin:agents_md",
        point="post_tool_call",
        order=0,
        selector=RustAlwaysHookSelector(),
    )
    merged = merge_image_describe_hook(CompiledHooks(bindings=(foreign,)))
    assert [binding.order for binding in merged.bindings] == [0, 1]
