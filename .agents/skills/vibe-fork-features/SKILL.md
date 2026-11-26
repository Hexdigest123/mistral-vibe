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
- `/config` keeps its category sections (Popular, Fork features, the topic
  sections such as Models/Subagents/MCP & connectors/Telemetry & logging,
  Advanced) when a search has more than `MERGED_MATCHES` rows: `filtered()`
  then returns fields in section order, since the sectioned rows are numbered
  in that order. Rows show a readable label (`config_label::humanize`:
  `max_concurrent_subagents` -> `Max concurrent subagents`, acronyms cased,
  `experimental_enable_x` -> `X (experimental)`); search ranks the raw key first
  and falls back to the label, so both find the row, and the editor's title
  shows the label with the raw `config.toml` key dim beside it.

Map: `vibe/cli-rust/src/utils/fzf.rs` (the only matcher for lists; the older
`utils/fuzzy.rs` stays for path and command completion), `model_picker.rs`,
`config.rs` (`filtered`), `config_label.rs`, `config_sections.rs`,
`config_edit/search.rs`, `ui/config_edit/search.rs`,
`resume_picker/search.rs` (the fzf `shown` over session titles/previews; since
upstream v3.1 `/resume` opens the sessions page, `sessions_page/model.rs` ranks
its rows through it), `mcp/rows.rs`, `plugins/rows.rs`; dependency
`nucleo-matcher` in `vibe/cli-rust/Cargo.toml`.

Guards: `tests/units/{fzf_rank,config_filter,model_picker_search,fork_features}.rs`
(`config_labels.rs` and `config_sections.rs` cover the labels and sections);
scenarios `model/model_search`, `model/model_fzf_terms`,
`slash_command/resume_search`, `slash_command/config_edit_choice_search`,
`config/config_search`, `config/config_labels`, `config/config_label_edit`.

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
  tab) on the same connection and runs **at once**, even while a turn, a queue
  or a shell command runs (explicit product decision, overriding the old
  "queue until idle" rule): the server **parks** the session whose turn still
  runs, and `session/resume` of a parked session re-attaches it live (the
  server re-announces `turn/started`, history replays, `adopt_active_turn`
  shows the loader). Only a session that is still `Starting`/`Failed`, or a
  running `/compact` (its answer belongs to the session being left), refuses a
  tab action, with a notice (`session_tabs::ready`). There is no tab queue any
  more. The in-flight switch rides the Sessions page's `switching` record, so
  input/Esc/Ctrl+C gating is shared, and while it is in flight the left
  session's late notifications are dropped (`is_foreign_session_notification`).
  A tab whose session is already attached (the server reused it) switches
  locally with no round-trip. A switch whose resume fails `session_not_found`
  removes the target tab from the list instead of leaving a dead tab.
- Server dependency (ADR 0022, `vibe/app_server/_parked_sessions.py`): parking
  only happens when the TUI declares `initialize.capabilities.parkRunningSession
  = true` (`startup::initialize_connection`, `ClientCapabilities.park_running_session`;
  guard: `session_tabs.rs::the_client_opts_in_to_parking_a_running_session_on_a_switch`)
  and declares no `agentPlugins`/`clientToolDefinitions` (it declares neither).
  Without it the server replaces the attached session and the turn is stopped,
  so never drop the capability. An idle old session is shut down as before; a
  failed switch leaves the connection on its session. A parked session's
  approvals/questions (`callback/call`) are re-sent when it is attached again,
  so the switch landing closes the left session's callback UI unanswered
  (`session_tabs/stale.rs`, `approval::State::forget`, `question_app::forget`).
  Quitting stops parked sessions.
- Background marks (`Tab.activity`): leaving a tab whose turn runs (status
  generating, or a live non-paused queue) marks it `Running` (`●`, theme
  `primary`); a poll flips it to `Waiting` (`!`, `warning`, status `blocked`),
  `Done` (`✓`, `success`, the turn ended while away) or `Idle` (session not
  listed). Landing on a tab clears its mark. The poll is `session/list` with
  `sessionIds` of the background tabs only (a host method, no root needed),
  armed by `poll_at` (3 s, UI clock) in the steady loop
  (`session_tabs::poll`/`apply_event`, `UiEvent::Tabs`) and re-armed only
  while a tab is `Running`/`Waiting`: no background tab, no polling.
- Empty tabs: the server drops a session nothing was run in when the
  connection leaves it, so the tab is removed from the bar when the switch
  lands (`pending_close` + `pending_empty`, notice "Closed the empty tab N").
  Empty = no server-owned entry in the transcript (`Snapshot::has_server_entries`)
  and no running turn/queue; the Sessions page leaving an empty tab drops it
  too (`drop_empty`). A failed switch keeps it. An index that no longer exists
  is ignored by every action.
- UI: a one-row tab bar above the conversation, shown when more than one tab
  is open or the chord is armed (`1 Title  2 Title …`, active tab on the
  cursor bar, `Ctrl+X tabs` hint at the right edge, or the chord keys while
  armed). Left click switches, middle click closes.
- Keys (composer only): `Ctrl+X` arms a chord, even with a single tab (`n` is
  how the second tab opens); the next key `1-9` switches to that tab, `n` opens
  a new one, `c` closes the active one; any other key cancels the chord and
  falls through to the upstream `Ctrl+X` rail chord (a priority key such as
  Ctrl+C cancels it too). `Tab`/`Shift+Tab`/`Alt+1-9` do not touch tabs
  (`focus::tab_navigates` stays false for the composer).
- `/tab [new|next|prev|close [N]|N]` runs the same actions and is never
  rejected or delayed while busy (ADR 0012 amendment: every command but the
  history rewrites runs at once; `/clear` `/compact` `/rewind` `/resume`
  `/retry` are `deferred` in `commands.rs` and scheduled in one slot,
  `commands/deferred.rs`, run by `deferred::run_when_idle` from the steady
  loop, cancelled by Esc, dropped on a session change);
  hidden from help and completion while the feature is off
  (`Feature::SessionTabs`), typing it while off shows a notice. Opening a
  session from the Sessions page opens it as a new tab (or switches to its tab
  if already open). `/clear`/`/compact` still replace the active tab's session
  in place.
- Config: `enable_session_tabs: bool = true` in `vibe_schema.py`, projected
  in `ConfigView` (`app_server/config.py`, `_projection.py`, ADR 0014 default
  `yes` in the Rust `proto_runtime.rs`), read by `startup::read_enable_session_tabs`
  and applied on ready and `runtime/updated`. While off, no tab bar, no tab
  keys, and `on_session_id` leaves the tab list alone. The field is in
  `FORK_SETTINGS`, so it renders in `/config`'s "Fork features" section.
  README.md "Session tabs" documents it.

Map: `vibe/cli-rust/src/session_tabs/` (`mod.rs` state + tab bookkeeping,
`actions.rs` new/switch/close/step/click, `switch.rs` the switch mechanics,
`background.rs` the poll and marks, `keys.rs`, `command.rs`), `src/ui/session_tabs.rs`
(tab bar + marks), `src/commands/deferred.rs` (the scheduled history command).
Hooks marked `Fork feature (AGENTS.md "Fork features")` in
`src/lib.rs`, `src/app.rs` (`set_session_id`, `deferred_command`), `src/event_handler.rs` (flag +
titles, foreign-notification guard), `src/input.rs`, `src/focus.rs`, `src/mouse.rs` + `src/mouse/dispatch.rs`,
`src/ui/mod.rs`, `src/ui_event.rs` (`Tabs`), `src/event_loop/steady.rs` (poll +
`run_when_idle`), `src/commands/{commands,dispatch,submission}.rs`, `src/ui/composer_title.rs`,
`src/bin/replay.rs` (`session/resume#<id>` pins),
`src/sessions_page/{mod,requests,switch,adopt}.rs`, `src/server/proto_runtime.rs`,
`src/startup/{mod,reads}.rs`, `src/transcript.rs` (`Snapshot: Clone`),
`src/event_loop/keys.rs` (the armed chord takes the next key before the
composer-level bindings).
Python: `vibe/core/config/vibe_schema.py`, `vibe/app_server/config.py`,
`vibe/app_server/_projection.py`, `vibe/app_server/_config_introspect.py`,
`vibe/app_server/_harness_errors.py` (`HarnessSessionNotFoundError` maps to
NOT_FOUND with `data.harnessCode = "session_not_found"`, which the client
recognizes to drop a gone tab).

Guards: `vibe/cli-rust/tests/units/{session_tabs,command_submission}.rs`, scenarios
`client-e2e/scenarios/session_tabs/{new_switch,disabled,chord_new_single_tab,gone_tab_removed,empty_tab_dropped,busy_switch,busy_switch_back}.py`,
`client-e2e/scenarios/slash_command/{compact_deferred,compact_deferred_cancel,model_while_busy}.py`,
`tests/app_server/test_projection.py::test_config_view_projects_enable_session_tabs`,
`tests/test_fork_features.py`.

## 8. TTFT and TPS in the bottom bar

Contract:
- The bottom bar's right side ends with the turn's pace after the `ctx` gauge:
  `… · ctx ▏ 0/800k · 0.8s ttft · 20.0 tok/s` (labels are OpenCode's footer wording).
- Measured like OpenCode's TUI, client-side from the app-server notifications: TTFT runs
  from `turn/started` to the first streamed text (an `history/entryAdded` in-progress
  assistant/reasoning entry with text, or the first `history/entryUpdated` patch appending
  `/content/<n>/text` or `/text`). TPS divides output tokens by the sum of per-entry decode
  windows — each streamed entry's last-to-first token span, so tool time and waits between
  entries are excluded — OpenCode's `tokensPerSecond`, which weights each step by its own
  provider-active duration.
- While streaming, the wire carries cumulative text only, so the live rate estimates
  tokens as chars/4 (OpenCode's plugins do the same) over the summed windows (`now` extends
  only the latest entry's). Once `session/statsUpdated` reports
  `lastTurnCompletionTokens`, the shown reading uses the exact count instead of the
  estimate.
- The last finished turn's reading stays in the bar when idle; a new session
  (`set_session_id`) resets it. A turn that streamed nothing shows no segment.
- Under narrow widths the segment is the first to shrink: full form, then tok/s only,
  then hidden — after the gauges have turned to levels; the gauges never hide.
- The UI clock drives all of it (`clock::now`), so replay scenarios advance it with
  `advance(ms)` and goldens are deterministic.

Map: `vibe/cli-rust/src/stream_pace.rs` (tracker + hooks; the only fork-only module),
hooks marked `Fork feature (AGENTS.md "Fork features")` in `src/lib.rs`, `src/app.rs`
(`Session.pace`, reset in `set_session_id`), `src/event_handler.rs` (`turn/started`,
`history/entryAdded`, `history/entryUpdated`, `turn/completed`, `session/statsUpdated`);
presentation in `src/ui/footer_gauge.rs` (`pace_forms`), `src/ui/footer_fit.rs` (the
third segment, `Slot::Pace` last in the `LADDER`), `src/ui/bottom_bar.rs`.

Guards: `vibe/cli-rust/tests/units/stream_pace.rs`, scenario
`client-e2e/scenarios/footer/stream_pace.py`, `tests/test_fork_features.py`.

## 9. Ctrl+X chord keys and the prompt stash (Rust TUI)

Contract:
- `Ctrl+X` on the free composer arms a one-key chord: `m` opens the model picker,
  `c` the settings, `s` stashes the draft (the prompt is cleared), `p` pops the
  latest stash at the cursor as a paste, `t` toggles conversation mode,
  `1-9`/`n`/`w` drive session tabs. Any other key falls through to the status
  rail, as `Ctrl+X` always did. With `enable_session_tabs` off the chord still
  works (`ctrl_x.armed`) and the rail still shows its letters.
- The rail's jump letters moved so they never collide: `o` loops, `a` agents,
  `b` tasks, `r` PRs, `g` goal, `d` todo list (`h`/`l` stay the rail's vim steps).
- `/stash <text>` stashes text, `/stash list` lists newest first (one line each),
  `/pop` takes the latest back; one in-memory LIFO stack per process shared by
  all tabs. `Ctrl+S` keeps its own single-slot swap and never touches the stack.

Map: `vibe/cli-rust/src/{ctrl_x,prompt_stash}.rs`, hooks in `event_loop/keys.rs`,
`input.rs` and `session_tabs/keys.rs`, `rail.rs` (`Item::letter`), the `/stash`
and `/pop` rows of `commands/commands.rs`.

Guards: `vibe/cli-rust/tests/units/{prompt_stash,ctrl_x_chord}.rs`, client-e2e
`stash/*` and `ctrl_x/*`.

## 10. Conversation mode and the `make build` feature chooser

Contract:
- `conversation_mode_enabled` (a third toggle in `/voice`, off by default) allows
  `Ctrl+X t`. Starting asks `session/approvalPolicy/update` for `smart-approve`
  with `optIn` (the startup `--smart-approve` bypass of the rollout gate), then
  `conversation/start`; a failed start restores the previous policy at once, and
  ending the conversation restores it too.
- The app server hosts the voice session (`_conversation_controller.py`) and
  imports the voice SDK only inside `_open_real_session`; `conversation/stop`
  closes it. The voice agent's `run_task`/`wait_for_task`/`cancel_task` tools
  round-trip through the client (`conversation/taskRequest` out,
  `conversation/taskResult` back): the prompt runs through the TUI's ordinary
  queue, so approvals and smart-approve apply; a tool answers within 20 s or says
  `running`, and `needs_approval` returns early.
- All rows of a conversation come through the notification channel (the "on" row
  is the first `listening` state), so goldens stay deterministic.
- `make build` runs `pyinstaller/build_features.py select` first; `make features`
  or `FEATURES=a,b|all|none` skip the question; `voice-agents` is the project
  extra `mistralai[voice-agents]` (livekit, numpy, pyaudio + system PortAudio).

Map: `vibe/app_server/_conversation_controller.py`, `protocol.py` (`conversation/*`,
`ApprovalPolicySwitchParams.opt_in`), `core/agents/manager.py`
(`aswitch_policy(opt_in=)`), `vibe_schema.py` (`conversation_*`),
`vibe/cli-rust/src/conversation.rs` and its hooks (`event_handler.rs`,
`ui/composer_title.rs`, `voice_app.rs`), `pyinstaller/build_features.py`,
`Makefile`, `vibe-app-server.spec`, `pyproject.toml` extra.

Guards: `tests/app_server/test_conversation.py`,
`vibe/cli-rust/tests/units/conversation.rs`, client-e2e `conversation_mode/*`,
`tests/test_fork_features.py`.

## Adding a fork feature

Add its row to the AGENTS.md "Fork features" table, its section here
(contract, map, guards, rebuild), and its guard tests to `GUARD_TESTS` in
`tests/test_fork_features.py`, in the same change.
