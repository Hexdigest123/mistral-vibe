from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.conftest import build_test_vibe_app, build_test_vibe_config, wait_until
from vibe.app_server.protocol import (
    AppServerResponseError,
    ModelCatalogEntryView,
    ModelsRefreshResponse,
    ProtocolError,
    ProtocolErrorCode,
)
from vibe.cli.commands import CommandRegistry
from vibe.cli.textual_ui.widgets.messages import ErrorMessage, UserCommandMessage
from vibe.core.config import ModelConfig


def test_models_command_is_registered() -> None:
    registry = CommandRegistry()
    assert registry.get_command_name("/models") == "models"
    command = registry.get("models")
    assert command is not None
    assert command.handler == "_models_command"


def test_models_command_parses_refresh_argument() -> None:
    registry = CommandRegistry()
    parsed = registry.parse_command("/models refresh")
    assert parsed is not None
    cmd_name, _command, cmd_args = parsed
    assert cmd_name == "models"
    assert cmd_args == "refresh"


def _app():
    config = build_test_vibe_config(
        models=[ModelConfig(name="model-a", provider="mistral", alias="alpha")],
        active_model="alpha",
    )
    return build_test_vibe_app(config=config)


def _ok_response() -> ModelsRefreshResponse:
    return ModelsRefreshResponse(
        entries=[
            ModelCatalogEntryView(
                provider_name="openrouter",
                endpoint="https://openrouter.ai/api/v1/models",
                model_ids=["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"],
            )
        ],
        total_models=2,
    )


def _mock_refresh(app, response: ModelsRefreshResponse | None = None) -> AsyncMock:
    mock = AsyncMock(return_value=response) if response is not None else AsyncMock()
    app.app_server.resources.config.refresh_models = mock
    return mock


@pytest.mark.asyncio
async def test_models_refresh_reports_discovered_models() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        mock = _mock_refresh(app, _ok_response())
        await app._models_command(cmd_args="refresh")
        await wait_until(
            pilot,
            lambda: any(
                isinstance(m, UserCommandMessage)
                and "2 models found" in str(m.render())
                for m in app.query(UserCommandMessage)
            ),
        )
        mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_models_without_subcommand_shows_usage() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        mock = _mock_refresh(app, _ok_response())
        await app._models_command(cmd_args="")
        await wait_until(
            pilot,
            lambda: any(
                "Usage: /models refresh" in str(m.render())
                for m in app.query(UserCommandMessage)
            ),
        )
        mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_models_unknown_subcommand_shows_error() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        mock = _mock_refresh(app, _ok_response())
        await app._models_command(cmd_args="bogus")
        await wait_until(
            pilot,
            lambda: any(
                "Unknown /models subcommand" in str(m.render())
                for m in app.query(ErrorMessage)
            ),
        )
        mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_models_refresh_failure_shows_error() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        mock = AsyncMock(
            side_effect=AppServerResponseError(
                ProtocolError(code=ProtocolErrorCode.INTERNAL_ERROR, message="boom")
            )
        )
        app.app_server.resources.config.refresh_models = mock
        await app._models_command(cmd_args="refresh")
        await wait_until(
            pilot,
            lambda: any(
                "refresh failed" in str(m.render()) for m in app.query(ErrorMessage)
            ),
        )


@pytest.mark.asyncio
async def test_models_refresh_without_targets_hints_at_model_blocks() -> None:
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        _mock_refresh(app, ModelsRefreshResponse(entries=[], total_models=0))
        await app._models_command(cmd_args="refresh")
        await wait_until(
            pilot,
            lambda: any(
                "[[model]]" in str(m.render()) for m in app.query(UserCommandMessage)
            ),
        )
