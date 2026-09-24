"""Builtin post-tool hook that describes image files read by a blind agent.

A model without ``supports_images`` can still discover image files with the
shell (``find``, ``ls``), but ``file_system.read_file`` on one hands it the
decoded bytes: latin-1 mojibake that wastes context and says nothing. This hook
substitutes the session's vision fallback model's transcription (the
``vision_model`` in ``config.toml``, or the same-provider vision pick) in place
of those bytes, so a blind agent can genuinely read an image it found.

The description is produced by the session's ``SessionImageDescriber`` -- the
same describer, cache and telemetry the turn-input path uses for pasted images.
The hook body is Host-global (``image_describe_hook_handlers``); the
per-session describer reaches it through the adapter config's
``image_describer`` sink, which child sessions inherit through the ``replace()``
copies ``_subagents/_configuration`` builds, so subagent reads are described
too. Only the binding rides the session's compiled hooks (see
``merge_image_describe_hook``), mirroring ``_agents_md_hooks``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mistralai_vibe_local_harness.protocol import (
    RustHarnessHookBinding,
    RustHarnessHookToolKey,
    RustPostToolCallHookInput,
    RustPostToolCallHookResult,
    RustPostToolCallOutput,
    RustRuntimeBuiltinToolCall,
    RustToolKeysHookSelector,
    RustToolResult,
    RustToolSuccessResult,
)
from mistralai_vibe_local_harness.vibe import CompiledHooks, HookHandlers

from vibe.app_server._agents_md_hooks import _read_file_path
from vibe.utils.images import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES

if TYPE_CHECKING:
    from mistralai_vibe_local_harness.vibe import HookContext
    from pydantic import JsonValue

    from vibe.app_server._vision import SessionImageDescriber

logger = logging.getLogger(__name__)

IMAGE_DESCRIBE_HOOK_BINDING_ID = "builtin:image_describe"
_READ_FILE_TOOL_NAME = "file_system.read_file"


@dataclass(slots=True)
class ImageDescribePort:
    """The session-scoped bind point the adapter config's sink resolves through.

    The adapter config is derived before the session's ``SessionImageDescriber``
    exists (the describer needs the adapter's notice and telemetry sinks), so the
    config carries ``describe`` and the adapter binds the real describer once it
    is constructed. Unbound (a closed session) reads pass through untouched.
    """

    describer: SessionImageDescriber | None = None

    def bind(self, describer: SessionImageDescriber) -> None:
        self.describer = describer

    def unbind(self) -> None:
        self.describer = None

    async def describe(self, path: Path) -> str | None:
        describer = self.describer
        if describer is None:
            return None
        return await describer.describe_file(path)


def _passthrough(tool_result: RustToolResult) -> RustPostToolCallHookResult:
    return RustPostToolCallHookResult(
        output=RustPostToolCallOutput(tool_result=tool_result)
    )


def _describable_image(path: Path) -> bool:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    try:
        return path.stat().st_size <= MAX_IMAGE_BYTES
    except OSError:
        return False


def _with_description(
    result: RustToolSuccessResult, *, description: str
) -> RustToolSuccessResult:
    structured = result.structured_content
    if not isinstance(structured, dict):
        # An unexpected shape is not ours to rewrite; the read lands as-is.
        return result
    updated: dict[str, JsonValue] = dict(structured)
    updated.update({
        "content": description,
        "offset": 0,
        "lines_read": len(description.splitlines()),
        "returned_bytes": len(description.encode("utf-8")),
        "was_truncated": False,
    })
    return result.model_copy(update={"structured_content": updated})


async def image_describe_hook(
    hook_input: RustPostToolCallHookInput, context: HookContext
) -> RustPostToolCallHookResult:
    tool_result = hook_input.tool_result
    call = hook_input.tool_call.call
    describer = context.config.image_describer
    if (
        describer is None
        or not isinstance(call, RustRuntimeBuiltinToolCall)
        or call.name != _READ_FILE_TOOL_NAME
        or not isinstance(tool_result, RustToolSuccessResult)
    ):
        return _passthrough(tool_result)
    path = _read_file_path(call, context)
    if path is None or not _describable_image(path):
        return _passthrough(tool_result)
    try:
        description = await describer(path)
    except Exception:
        # A broken describer must not break the read the agent already made.
        logger.exception("Describing %s failed", path)
        return _passthrough(tool_result)
    if description is None:
        # A session with no vision fallback (or a model that sees images) keeps
        # its read untouched.
        return _passthrough(tool_result)
    return RustPostToolCallHookResult(
        output=RustPostToolCallOutput(
            tool_result=_with_description(tool_result, description=description)
        )
    )


def image_describe_hook_handlers() -> HookHandlers:
    """The Host-global builtin registry payload for ``configure_hook_handlers``."""
    return HookHandlers(
        post_tool_call={IMAGE_DESCRIBE_HOOK_BINDING_ID: image_describe_hook}
    )


def merge_image_describe_hook(hooks: CompiledHooks) -> CompiledHooks:
    """Bind the image-describe builtin hook point on a session's Core.

    Only the binding: the handler is Host-global (see
    ``image_describe_hook_handlers``), so it never lands in the per-session
    handler map that marks hooks foreign. Scoped to the one tool it rewrites,
    so no other tool call pays the dispatch. The order slots after the last
    existing binding for the same reason as ``merge_agents_md_hook``.
    """
    binding = RustHarnessHookBinding(
        id=IMAGE_DESCRIBE_HOOK_BINDING_ID,
        point="post_tool_call",
        order=max((binding.order for binding in hooks.bindings), default=-1) + 1,
        selector=RustToolKeysHookSelector(
            tool_keys=[
                RustHarnessHookToolKey(
                    target="filesystem", qualified_name=_READ_FILE_TOOL_NAME
                )
            ]
        ),
    )
    return replace(hooks, bindings=(*hooks.bindings, binding))


__all__ = [
    "IMAGE_DESCRIBE_HOOK_BINDING_ID",
    "ImageDescribePort",
    "image_describe_hook",
    "image_describe_hook_handlers",
    "merge_image_describe_hook",
]
