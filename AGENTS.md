# AGENTS.md

Conventions for AI agents and humans contributing to **Mistral Vibe** — a CLI coding assistant: a Rust terminal UI over a Python 3.12+ app server managed with `uv`.

Layout: Unified Harness Core and Runtime are external dependencies that execute and persist sessions; `vibe/app_server` hosts sessions and exposes product features and RPCs to every client, including Vibe Desktop; `vibe/core` retains shared config, tool, permission and other utilities; `vibe/cli-rust` is the terminal UI (Rust, Ratatui), a thin client over `vibe-app-server`; `vibe/cli` holds the `vibe` launcher that execs it and the audio helpers `vibe/acp` uses; `vibe/acp` bridges to the Agent Client Protocol; `vibe/setup` holds auth and onboarding config shared by the app server and `vibe-acp`. Tests live in `tests/` with autouse fixtures in `conftest.py` and test doubles in `tests/stubs/`.

## Fork features (never drop)

This checkout is the `Hexdigest123/mistral-vibe` fork. The features below exist only here, and they are requirements: no task, refactor, cleanup, simplification, upstream merge or conflict resolution may remove, disable, hide or degrade one, and "upstream does not have it" is never a reason. Their contracts, file maps and rebuild steps are in the `vibe-fork-features` skill (`.agents/skills/vibe-fork-features/SKILL.md`): read it before an upstream merge, before changing a file it lists, and whenever `tests/test_fork_features.py` fails.

| Fork feature | Guard tests |
| --- | --- |
| fzf search (nucleo: every term matches, `'exact`, `^prefix`, `suffix$`, `!not`) in `/model`, `/config` and its long choice lists, `/resume`, `/mcp`, `/plugins` | `vibe/cli-rust/tests/units/{fork_features,fzf_rank,config_filter,model_picker_search}.rs`; client-e2e `model/model_search`, `model/model_fzf_terms`, `slash_command/resume_search`, `slash_command/config_edit_choice_search` |
| `[[providers]] discover = true`: every model the provider's `/models` lists, fetched once per boot and cached in `/tmp/vibe-<uid>/discovered-models.json`; `/model refresh` refetches | `tests/core/models/`, `tests/app_server/test_provider_model_discovery.py`, `vibe/cli-rust/tests/units/model_refresh.rs`; client-e2e `model/model_refresh*` |
| Linux clipboard image paste (`Ctrl+V`, `/paste-image`): PNG/JPEG/WebP/GIF, file-manager copies, native X11/Wayland fallback without wl-clipboard or xclip | `vibe/cli-rust/tests/units/paste_image.rs` |
| Vision fallback for blind models, including images read with `read_file` (`builtin:image_describe`) and a `vision_model` on another provider | `tests/app_server/test_image_read_hooks.py`, `tests/app_server/test_vision.py` |
| `make build` → standalone `~/.local/bin/vibes` | `tests/test_fork_features.py` |

1. Before you finish any change, and after every upstream merge, run `uv run pytest tests/test_fork_features.py` and the guard tests of every feature the change touches, plus `make test_golden` when the TUI changed. A failing guard means a fork feature broke: fix the code, never the guard.
2. Never delete, skip, xfail or weaken a guard test or a fork golden, and never shorten `GUARD_TESTS` in `tests/test_fork_features.py`. Only the user's explicit decision to change a feature changes its guards.
3. In an upstream merge, keep both upstream's change and the fork feature. When upstream rewrote or deleted the code a feature lived in (v3.0 replaced the Python TUI with `vibe/cli-rust` and silently dropped the fork's picker search and clipboard paste), re-implement the feature on the new code in that same merge, from its contract in the skill. Never land a merge with a fork feature missing.
4. Fork-only code must follow upstream's dependency swaps (v3.0.4 moved runtime HTTP from `httpx` to `httpx2`): after a merge, grep the fork-only modules for removed imports and smoke-test the `make build` bundle.
5. Keep fork code in fork-only modules with thin hooks into upstream files, each hook marked `Fork feature (AGENTS.md "Fork features")`. A new fork feature gets its row here, its section in the skill and its `GUARD_TESTS` entries in the same change.
6. If a request would remove or change what one of these features does, say so and get the user's explicit go-ahead first.

### Local fork builds

- `make build` is the one build command: it builds the Rust TUI (`vibe-rs`) and the PyInstaller `vibe-app-server` bundle from the current source — every patch in this checkout included — and installs them behind a `~/.local/bin/vibes` wrapper. Do not add experimental-flag build variants; there is no `make build-experimental`.
- The Unified Harness is the only backend on every surface (CLI, ACP, app-server); upstream 3.0 removed the legacy loop and the `--experimental-harness`/`--legacy-harness` flags. A missing or incompatible harness fails startup with an actionable error.

## Architecture Decisions

Before architecture-affecting changes, read [0002 Ownership Boundaries](docs/adr/0002-core-engine-and-delivery-surfaces.md) and the matching ADR below. For new agent capabilities, also read [0018](docs/adr/0018-modular-app-server-capabilities.md), including its Runtime/Core scope rule. Flag conflicts with ADR direction before implementing. When writing ADRs, follow the `write-vibe-adr` skill.

| Change area | ADR |
| --- | --- |
| Architecture principles, module boundaries, startup/runtime speed, simple changes | [0001 Architecture Principles](docs/adr/0001-architecture-principles.md) |
| Core/Runtime/app-server ownership, session hosting, adapters, or delivery clients | [0002 Ownership Boundaries](docs/adr/0002-core-engine-and-delivery-surfaces.md) |
| Tool contracts, permissions, tool output, UI metadata, or tool adapters | [0004 Typed Permissioned Tools](docs/adr/0004-typed-permissioned-tools.md) |
| Config models, layering, defaults, migrations, reloads, or runtime overrides | [0005 Layered Configuration](docs/adr/0005-layered-configuration.md) |
| Session logging, resume, rewind, transcript metadata, or migrations | [0006 Local Sessions](docs/adr/0006-local-sessions.md) |
| Skills, agents, subagents, hooks, MCP, connectors, custom tools, or discovery | [0007 Extension Mechanisms](docs/adr/0007-extension-mechanisms.md) |
| Adding or changing analytics instrumentation, telemetry events, or event properties | [0008 Feature Instrumentation](docs/adr/0008-feature-instrumentation.md) |
| Client protocol, streaming, cancellation, projections, ordering, callbacks, or transports | [0009 App Server Client Boundary](docs/adr/0009-app-server-boundary.md) |
| Slash commands running while busy, side-channel commands, or idle-only settings persistence | [0012 Slash Commands While Busy](docs/adr/0012-two-phase-slash-command-execution.md) |
| Queued-prompt selection/edit mode, copy-on-write consumed edits, or promotion-race widget-identity tracking | [0013 Queue Selection and Edit Mode](docs/adr/0013-queue-edit-mode.md) |
| Parsing backend responses, connector/MCP bootstrap fields, or any client/backend wire-contract change that must tolerate self-hosted version skew | [0014 Backend Contract Compatibility](docs/adr/0014-backend-contract-compatibility.md) |
| Outbound TLS connections, certificate roots, or `enable_system_trust_store` | [0015 Outbound TLS Trust Policy](docs/adr/0015-outbound-tls-trust-policy.md) |
| Rust CLI delivery surface, thin-client boundary, unidirectional state, or bounded-resource rules | [0016 Rust CLI Delivery Surface](docs/adr/0016-rust-cli-delivery-surface.md) |
| Narration playback, TTS, audio output device following, or the `AudioPlayer`/`DeviceFollower`/`NarrationController` classes | [0017 Narration Playback in the ACP Subprocess](docs/adr/0017-narration-playback-in-subprocess.md) |
| Adding agent behavior, custom tools, built-in plugins/skills, RPC families, or feature-module dependencies | [0018 Modular App-Server Capabilities](docs/adr/0018-modular-app-server-capabilities.md) |
| Adding state shared by every channel or session of the process, a remote value refreshed for all sessions, or an app-server entry point | [0019 Process Services](docs/adr/0019-process-services.md) |

Superseded records: [0003](docs/adr/0003-event-driven-agent-loop.md) → 0009; [0011](docs/adr/0011-unified-harness-backend.md) → 0002. Their paths remain for existing links.

## Cross-Surface Features

Vibe CLI and Vibe Desktop share the app server. When a CLI feature may also belong on Desktop, follow `.agents/skills/vibe-workflow/cross-surface.md` at the root of the dashboard monorepo. Skip this outside the dashboard monorepo.

## Terminal UI changes

The terminal UI is `vibe/cli-rust`. Follow `vibe/cli-rust/AGENTS.md` and the `vibe-rust-tui` skill, and cover every user-visible change with a `client-e2e` scenario and golden (see `client-e2e/AGENTS.md`).

- Put server-owned behavior (session, config and persistence, tools, network; see the ownership table in ADR 0002) behind an app-server method or notification so the TUI, Vibe Desktop, and `vibe-acp` only render it. Keep presentation state (widgets, layout, focus, selection, editing) in the client.
- `vibe-acp --setup` runs the Rust onboarding wizard (`vibe-rs --setup` with `VIBE_SETUP_ENTRYPOINT=acp`); change onboarding UI there only.

## Commands

Always go through `uv` — never invoke bare `python` or `pip`.

- `uv run vibe` / `uv run vibe-acp` — the two entry points.
- `uv run pytest` — full suite (parallel via `pytest-xdist`).
- `uv run pyright` — strict type check.
- `uv run ruff check --fix .` and `uv run ruff format .` — run both after every code change and report the files modified.
- `uv run pre-commit run --all-files` — full lint pass. Install once with `uv tool install pre-commit && uv run pre-commit install`.
- Useful uv basics: `uv sync --all-extras`, `uv add <pkg>`, `uv remove <pkg>`.

Never stop processes by name or pattern (`pkill`, `killall`, `pgrep | xargs kill`): names and patterns such as `vibe`, `vibe-rs`, `vibe-app-server`, `vibe-acp` or `client-e2e` match every Vibe session, IDE integration and test run on the machine, including the user's own. Stop only processes you started, by the PID or process group you recorded when you started them; if you do not have it, ask the user instead of guessing.

## Project layout & module conventions

- `__init__.py` exposes the public API via an explicit `__all__`.
- Private modules are prefixed with `_` (e.g. `_settings.py`, `_config.py`).
- Pydantic config models live in `models.py`; shared config defaults live in `_defaults.py`; the effective config schema lives in `vibe_schema.py`.
- Abstract interfaces use the `_port.py` suffix (hexagonal-style ports).
- Tests mirror the source layout: a test lives in the directory mirroring its source module's package. Tests for a `vibe/core` subpackage go under the matching `tests/core/<subpackage>/` (e.g. `vibe/core/utils/retry.py` → `tests/core/utils/test_retry.py`); tests for modules that sit directly in `vibe/core/` (e.g. `loop.py`, `types.py`) stay flat in `tests/core/`. No `__init__.py` is needed in test subdirectories — pytest runs in `--import-mode=importlib`. Test doubles in `tests/stubs/` are named `Fake*`.

## Autoimprovement

- When a change request can be generalized as a rule, prefer adding it to the relevant `.agents/skills/` SKILL.md rather than appending to AGENTS.md. AGENTS.md should stay small and universal; domain-specific conventions belong in skills so they load only when needed. Create a new skill when no existing one fits.
- Suggest updates to the README.md file according to feature changes or additions.
- Keep the builtin Vibe Skill (`vibe/plugins/builtins/vibe/skills/vibe/SKILL.md`) up-to-date. It documents the CLI's features, such as args, flags, config options and persistence, commands, built-in agents, file discovery logic.
- When adding or changing Vibe config fields, check whether Settings Manager's Vibe Code managed-config UI and Le Chat Web's backend allowlist/schema must be updated. If no update is needed, say so explicitly in the change notes.
