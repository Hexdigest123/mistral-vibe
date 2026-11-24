---
name: vibe-fork-features
description: The features only this fork of Mistral Vibe has (fzf list search, discover providers with a boot cache, /model refresh, Linux clipboard image paste, image-read vision fallback, make build -> vibes) - their behavior contracts, where they live, how they hook into upstream code, and how to re-implement them when an upstream merge rewrites their area. Use before any upstream merge or conflict resolution, before refactoring or deleting code in the files listed here, and whenever a guard test in tests/test_fork_features.py fails.
metadata:
  display-name: Vibe Fork Features
  short-description: Contracts, file map and rebuild steps for the fork-only features
  default-prompt: Use $vibe-fork-features to keep every fork feature working through this change.
---

# Vibe Fork Features

This fork (`Hexdigest123/mistral-vibe`) adds the features below to upstream
Mistral Vibe. Each section is the feature's **contract**: what must stay true,
whatever the code looks like. If a merge or refactor changes the code, keep the
contract; if upstream deleted or rewrote the code a feature lived in, rebuild
the feature on the new code from its contract, in the same change.

## Ground rules

- Never remove, disable, hide, or degrade a feature here, and never weaken,
  skip, or delete its guard tests or goldens. "Upstream does not have it" is
  not a reason. Ask the user before changing a contract.
- Keep fork code in fork-only modules with thin hooks into upstream files.
  Mark every hook `Fork feature (AGENTS.md "Fork features")` so a merge
  conflict shows what to keep.
- Follow the repo's own rules while doing it: `vibe/cli-rust/AGENTS.md` (files
  ≤300 lines, pure reducer, tests in `tests/units/`, a client-e2e scenario and
  golden for every visible change) and the `vibe-rust-tui` skill (search model,
  hints, list cursor, colors).

## After every upstream merge

1. `git diff <old-upstream>..<new-upstream> --stat` and look for changes to the
   files in each section's map; when a map file was deleted or rewritten,
   re-implement that feature on its replacement.
2. Grep fork-only Python for imports of dependencies upstream removed or swapped
   (v3.0.4 swapped runtime `httpx` for `httpx2`: fork code still importing
   `httpx` crashed the `--no-dev` PyInstaller bundle).
3. Run `uv run pytest tests/test_fork_features.py`, every feature's guard
   tests below, `make test_rust QUIET=1` and `make test_golden` (from the repo
   root, with the release binary rebuilt).
4. `make build`, then smoke-test `dist/vibe-app-server-dir/vibe-app-server`
   before installing: the banner version comes from the cached
   `~/.vibe/ui_startup_config.json`, so a stale version there means the new
   server never booted.

## 1. fzf search for every long list (Rust TUI)

Contract:
- `/model`, `/config` (setting rows and every choice list longer than
  `MAX_VISIBLE_CHOICES`, e.g. `active_model`), `/resume`, `/mcp` and `/plugins`
  search with nucleo (fzf's algorithm), case-insensitive.
- Every space-separated term must match; `'exact`, `^prefix`, `suffix$` and
  `!exclude` work. Names match fuzzily; prose (setting descriptions, plugin
  descriptions, session previews) matches each term as typed and ranks after
  every name match. Ties keep the list's own order.
- `/model` matches one haystack of display name, alias, id and provider, so
  terms can span fields (`openrouter gpt`); each row shows its provider.
- The interaction is the `vibe-rust-tui` search model: `/` focuses, typing
  filters live, `↑↓`/Enter act on the list while the field is focused, Esc
  leaves the field, then clears the filter, then closes; the search row sits
  under the title (`/  Search …`); typing never resizes the box.
- `/config` keeps its Popular/Advanced sections when a search has more than
  `MERGED_MATCHES` rows: `filtered()` then returns popular fields first, since
  the sectioned rows are numbered in that order.

Map: `vibe/cli-rust/src/utils/fzf.rs` (the only matcher for lists; the older
`utils/fuzzy.rs` stays for path and command completion), `model_picker.rs`,
`config.rs` (`filtered`), `config_edit/search.rs`, `ui/config_edit/search.rs`,
`resume_picker/search.rs` (the fzf `shown` over session titles/previews; since
upstream v3.1 `/resume` opens the sessions page, `sessions_page/model.rs` ranks
its rows through it), `mcp/rows.rs`, `plugins/rows.rs`; dependency
`nucleo-matcher` in `vibe/cli-rust/Cargo.toml`.

Guards: `tests/units/{fzf_rank,config_filter,model_picker_search,fork_features}.rs`;
scenarios `model/model_search`, `model/model_fzf_terms`,
`slash_command/resume_search`, `slash_command/config_edit_choice_search`,
`config/config_search`.

Rebuild: add one shared ranking helper (`rank(items, query, name, prose)`)
over nucleo's `Pattern::parse` (fuzzy) and `Pattern::new(…, Substring)`
(prose), reuse one thread-local `Matcher`, and call it from every list above.

## 2. Model discovery: `[[providers]] discover = true` with a boot cache

Contract:
- `ProviderConfig.discover: bool = False`. Only flagged providers are queried;
  nothing else (no `[[models]]` block) triggers discovery, and a config
  without one sends no request.
- Every config build and host read applies the discovered models
  (`apply_cached_layers` → `_apply_discovered_models`, last, so the org
  config's providers count): this boot's cache answers at once; a provider it
  holds nothing for is fetched then, concurrently, within
  `MODELS_LIST_TIMEOUT`. Discovery never fails a build.
- Cache: one file, `<system temp dir>/vibe-<uid>/discovered-models.json`
  (`/tmp/vibe-1000/…`), in a directory only this user owns and can enter
  (a symlink or foreign owner disables the cache). It records the boot id
  (`/proc/sys/kernel/random/boot_id`, else the boot minute), so a reboot empties
  it; each provider entry records its endpoint and a key fingerprint (never the
  key), so a changed `api_base` or key refetches that provider. Writes are
  atomic; failures are not cached. Discovery holds an `flock` on
  `.discovered-models.lock` in that directory, so starts racing on an empty
  cache (the connector warm-up and `config/read`, or two processes) fetch
  each provider once. Tests redirect `cache._CACHE_DIR`
  (autouse fixture in `tests/conftest.py`); never touch the real cache.
- Requests: `GET {api_base}/models` with `Bearer` auth; Anthropic style
  (`api_style = "anthropic"`) `GET …/v1/models?limit=1000` with `x-api-key`
  and `anthropic-version`; a CLI OIDC sign-in sends its OIDC headers; a
  configured `Authorization`/`x-api-key` header is sent as is.
- Parsing keeps Mistral, OpenRouter and Anthropic metadata (display name,
  `supports_images`, `max_context_length`) and drops models the endpoint
  marks as unable to chat with tools (`capabilities.completion_chat/
  function_calling = false`, OpenRouter `supported_parameters` without
  `tools`). Without metadata every id is kept.
- Models land in `ProviderModelsLayer` (just above the defaults): explicit
  `[[models]]` entries win field by field; an id another layer already uses as
  an alias for a different provider becomes `<provider>/<id>`.
- `/model refresh` → app-server `models/refresh` → `apply_discovered_models(
  refresh=True)`: refetches every flagged provider; one that fails keeps its
  cached models and reports the error; the response shape is
  `{entries: [{providerName, endpoint, modelIds}], totalModels, errors}` and a
  `runtime/updated` follows. The TUI reports `Models refreshed: <provider>
  <count>, …` or `Could not refresh …`.
- `session_config_inputs` includes the cache file, so a refresh rebuilds
  cached session configs.

Map: `vibe/core/models/` (`catalog.py` fetch and parse, `cache.py`,
`discovery.py`, `config_bridge.py`), `vibe/core/config/models.py`
(`ProviderConfig.discover`), `vibe/core/config/layers/provider_models.py`,
`vibe/core/config/default_orchestrator.py` (layer slot),
`vibe/app_server/_cached_layers.py`, `_session_config_cache.py`,
`_unified_harness_backend_adapter.py` (`refresh_models_catalog`),
`protocol.py`/`server.py`/`_session_backend_port.py` (`models/refresh`),
`config.py` + `_projection.py` (`ModelConfigView.provider`, the
provider-models model source); TUI `src/commands/model_refresh.rs`,
`commands/dispatch.rs`, `commands/commands.rs` (`.args("[refresh]")`).

Guards: `tests/core/models/`, `tests/core/config/test_provider_models_layer.py`,
`tests/app_server/test_provider_model_discovery.py`,
`tests/units/model_refresh.rs`, scenarios `model/model_refresh*`.

## 3. Linux clipboard image paste (Rust TUI)

Contract:
- `Ctrl+V` in the composer, an empty bracketed paste, and `/paste-image`
  (registered on Linux and macOS) attach the clipboard image as
  `[Image #N]`, stored under `$TMPDIR/vibe-pasted-images/` with its own
  extension (PNG, JPEG, WebP, GIF are accepted; others are not an image).
- Linux asks the reachable tool what is on offer (`wl-paste --list-types`
  when `WAYLAND_DISPLAY` is set, else/also `xclip -selection clipboard -t
  TARGETS -o` when `DISPLAY` is set) and reads the best image type, in
  `IMAGE_TYPES` order. Image files copied in a file manager (`text/uri-list`,
  `file://` URIs only, percent-decoded) attach like Finder copies and win over
  image data.
- With neither tool installed, the native clipboard (arboard: X11, Wayland
  data-control) is read, and its RGBA pixels re-encoded as PNG.
- Every tool run is bounded by a timeout; unit tests never read the host
  clipboard.

Map: `vibe/cli-rust/src/paste_image/{linux.rs,mod.rs,store.rs}`,
`src/paste_files.rs` (`read_clipboard_files`), `src/commands/commands.rs`
(`/paste-image` registration); dependencies `arboard` and `png`
(Linux-only) in `vibe/cli-rust/Cargo.toml`.

Guards: `tests/units/paste_image.rs`, `tests/units/fork_features.rs`.

## 4. Vision fallback for image reads

Contract: a blind active model that reads an image with `read_file` gets the
vision fallback model's transcription in place of the bytes (the
`builtin:image_describe` post-tool hook, inherited by subagents), using the
same describer and `vision_model` as pasted images; `vision_model` may sit on
another provider than the active model. Users pin both in `config.toml`, e.g.
`active_model = "mistral-large-4"` and a `[vision_model]` table for
`mistral-large-4-0` (`supports_images = true`).

Map: `vibe/app_server/_image_read_hooks.py`, `_vision.py`, `_runtime.py`
(`_builtin_hook_handlers`, `merge_image_describe_hook`, `ImageDescribePort`),
`_unified_harness_backend_adapter.py` (image describer binding).

Guards: `tests/app_server/test_image_read_hooks.py`,
`tests/app_server/test_vision.py`, `tests/test_fork_features.py`.

## 5. `make build` → `~/.local/bin/vibes`

Contract: `make build` builds the Rust TUI and the PyInstaller
`vibe-app-server` bundle from this checkout (every fork patch included) and
installs them behind a `~/.local/bin/vibes` wrapper; `make install` reinstalls
the last build. There is no experimental-flag variant.

Map: `Makefile`, `vibe-app-server.spec`, `vibe-acp.spec` (bundled builtin
plugin data).

Guards: `tests/test_fork_features.py`.

## 6. Telemetry kill switch `disable_all_telemetry`

Contract:
- `VibeConfigSchema.disable_all_telemetry: bool = False` — off by default, so
  installing the fork changes nothing; when `true`, every telemetry channel is
  off regardless of `enable_telemetry`: datalake events
  (`TelemetryClient._is_enabled`), Sentry crash reports
  (`crash_reports_allowed`), OpenTelemetry traces (`setup_tracing`), the
  GrowthBook eval and its identity fetches (`experiments_allowed`,
  `experiments/session.py`), and remote-plugin sync telemetry. The gate is
  `telemetry_active(config)` = `enable_telemetry and not kill switch`; the
  armed check is strict (`is True`) so test doubles read as disarmed.
- Arming it purges on-disk telemetry (`purge_local_telemetry`): the two
  GrowthBook eval caches under `~/.vibe/` and `telemetry event=` payload lines
  in `~/.vibe/logs/vibe.log`. Purged at app-server boot, after a successful
  `config/write`/`config/reload` that leaves it armed. Already-sent data is
  server-side and irremovable; the README documents it and the firewall hosts.
- Off-only merge rule, opposite polarity to `enable_telemetry`: a
  `project-toml` or `agent-profile` layer's `disable_all_telemetry = false` is
  dropped in `prepare_layers` (with a validation warning); `= true` is kept.
- The settings UI flags it: `ConfigFieldWire.dangerous` (defaulted for skew)
  is set in `build_field_wires`, the TUI renders the row in the error color
  and shows a ban-risk warning when it is switched on.

Map: `vibe/core/config/_telemetry_kill_switch.py` (all fork-only logic),
hooks in `vibe_schema.py` (field, `prepare_layers`, `check_layer_keys`),
`vibe/core/telemetry/send.py`, `vibe/core/config/_self_hosted.py`,
`vibe/core/tracing.py`, `vibe/core/experiments/session.py`,
`vibe/core/plugins/remote.py`, `vibe/app_server/protocol.py` (`dangerous`),
`vibe/app_server/_config_introspect.py`, `vibe/app_server/_host.py` (boot
purge), `vibe/app_server/server.py`, `vibe/app_server/_unified_harness_backend_adapter.py`
(write/reload purge); TUI `src/config_fields.rs`, `src/ui/config_options.rs`,
`src/ui/config.rs`, `src/config_edit.rs`. README.md "Telemetry kill switch".

Guards: `tests/core/config/test_telemetry_kill_switch.py`,
`vibe/cli-rust/tests/units/config_dangerous.rs`, scenario
`client-e2e/scenarios/config/telemetry_kill_switch.py`,
`tests/test_fork_features.py`.

## 7. Session tabs (`enable_session_tabs`, on by default)

Contract:
- Quick-switch tabs: only the active tab is attached to the app-server (one
  connection, one session, as before); the other tabs keep their transcript
  snapshot, scroll and composer draft client-side, and their session in the
  store. A tab switch sends `session/resume` (or `session/start` for a new
  tab) on the same connection, so it waits for the current turn to finish
  (same gate as the Sessions page's switch). The in-flight switch rides the
  Sessions page's `switching` record, so input/Esc/Ctrl+C gating is shared.
- UI: a one-row tab bar above the conversation, shown when more than one tab
  is open (`1 Title  2 Title …`, active tab on the cursor bar, `Tab switch
  tab` hint at the right edge). Left click switches, middle click closes.
- Keys (composer only): `Tab`/`Shift+Tab` step (wrapping), `Alt+1-9` jump.
  With 2+ tabs open, `focus::tab_navigates` is true for the composer, so
  Shift+Tab reaches the tabs instead of cycling approval policies.
- `/tab [new|next|prev|close [N]|N]` runs the same actions; hidden from help
  and completion while the feature is off (`Feature::SessionTabs`), typing it
  while off shows a notice. Opening a session from the Sessions page opens it
  as a new tab (or switches to its tab if already open). `/clear`/`/compact`
  still replace the active tab's session in place.
- Config: `enable_session_tabs: bool = true` in `vibe_schema.py`, projected
  in `ConfigView` (`app_server/config.py`, `_projection.py`, ADR 0014 default
  `yes` in the Rust `proto_runtime.rs`), read by `startup::read_enable_session_tabs`
  and applied on ready and `runtime/updated`. While off, no tab bar, no tab
  keys, and `on_session_id` leaves the tab list alone. The field is in
  `FORK_SETTINGS`, so it renders in `/config`'s "Fork features" section.
  README.md "Session tabs" documents it.

Map: `vibe/cli-rust/src/session_tabs/` (`mod.rs` state + tab bookkeeping,
`switch.rs` the switch mechanics, `keys.rs`, `command.rs`), `src/ui/session_tabs.rs`
(tab bar). Hooks marked `Fork feature (AGENTS.md "Fork features")` in
`src/lib.rs`, `src/app.rs` (`set_session_id`), `src/event_handler.rs` (flag +
titles), `src/input.rs`, `src/focus.rs`, `src/mouse.rs` + `src/mouse/dispatch.rs`,
`src/ui/mod.rs`, `src/commands/{commands,dispatch}.rs`,
`src/sessions_page/{mod,requests,switch,adopt}.rs`, `src/server/proto_runtime.rs`,
`src/startup/{mod,reads}.rs`, `src/transcript.rs` (`Snapshot: Clone`).
Python: `vibe/core/config/vibe_schema.py`, `vibe/app_server/config.py`,
`vibe/app_server/_projection.py`, `vibe/app_server/_config_introspect.py`.

Guards: `vibe/cli-rust/tests/units/session_tabs.rs`, scenarios
`client-e2e/scenarios/session_tabs/new_switch.py` and `disabled.py`,
`tests/app_server/test_projection.py::test_config_view_projects_enable_session_tabs`,
`tests/test_fork_features.py`.

## Adding a fork feature

Add its row to the AGENTS.md "Fork features" table, its section here
(contract, map, guards, rebuild), and its guard tests to `GUARD_TESTS` in
`tests/test_fork_features.py`, in the same change.
