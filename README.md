# Mistral Vibe

[![PyPI Version](https://img.shields.io/pypi/v/mistral-vibe)](https://pypi.org/project/mistral-vibe)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/release/python-3120/)
[![CI Status](https://github.com/mistralai/mistral-vibe/actions/workflows/ci.yml/badge.svg)](https://github.com/mistralai/mistral-vibe/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/mistralai/mistral-vibe)](https://github.com/mistralai/mistral-vibe/blob/main/LICENSE)

```
██████████████████░░
██████████████████░░
████  ██████  ████░░
████    ██    ████░░
████          ████░░
████  ██  ██  ████░░
██      ██      ██░░
██████████████████░░
██████████████████░░
```

Mistral Vibe is an open-source coding agent for your terminal. Describe what you want, and it reads your code, edits files and runs commands, asking before it does anything risky.

**What changes in this fork?**

- Clipboard image paste on Linux (see [Linux clipboard image paste](#linux-clipboard-image-paste)): `Ctrl+V` or `/paste-image` attaches the clipboard image, including image files copied in a file manager
- Vision fallback for blind models (see [Vision fallback for image reads](#vision-fallback-for-image-reads)): an active model without vision that reads an image with `read_file` gets the `vision_model`'s description of it
- Custom provider tag \[provider\] with automatic discovery of the provider's models (see [Provider model auto-discovery](#provider-model-auto-discovery))
  - Also auto-discovers Mistral's model catalog, since `mistral-large-4` is still listed with a 400k max context window, which is simply false
- FZF search in every long list: `/model`, `/config`, `/resume`, `/mcp` and `/plugins` (see [FZF search](#fzf-search))
- Session tabs (see [Session tabs](#session-tabs)): several sessions in one window, switched with `Tab`/`Shift+Tab`, `Alt+1-9`, a click on the tab bar, or `/tab`
- On Linux, child processes Vibe starts (MCP stdio servers, hooks, background processes) carry `PR_SET_PDEATHSIG`, so the kernel kills them if the app-server dies — no more orphaned `node`/shell processes after a `SIGKILL`
- Builds to `vibes` instead of `vibe` (for my personal testing)
- Optional telemetry kill switch `disable_all_telemetry` (see [Telemetry kill switch](#telemetry-kill-switch)): **off by default**, so installing this fork changes nothing; when you enable it, ALL telemetry is disabled and locally stored telemetry is deleted
  - It is flagged DANGEROUS in the settings: this might get you banned when they enact their new fascist dictator policies

**Where to find the settings**

- In the CLI: `/config` opens the settings screen (type `/` to search, e.g. `/telemetry`); every setting can also be edited there and is written to `~/.vibe/config.toml`. This fork's own settings (`disable_all_telemetry`, `enable_session_tabs`) get a "Fork features" section at the top
- Or edit the TOML directly: `~/.vibe/config.toml` (user-wide) or `.vibe/config.toml` in a trusted project
- `/model` lists the models, with fzf search and `/model refresh`

**FZF search**

`/model`, `/config` (setting rows and long choice lists like `active_model`), `/resume`, `/mcp` and `/plugins` all search with fzf's algorithm, case-insensitive. Every space-separated term must match, and `'exact`, `^prefix`, `suffix$` and `!not` work; `/model` matches across display name, alias, id and provider, so `openrouter gpt` finds OpenRouter's GPT models.

**Linux clipboard image paste**

`Ctrl+V` in the composer or `/paste-image` attaches the clipboard image as `[Image #N]` (PNG, JPEG, WebP and GIF are accepted), stored under `$TMPDIR/vibe-pasted-images/`. Image files copied in a file manager (`file://` URIs) attach the same way. On Linux the paste asks `wl-paste`/`xclip` what is on offer when they are installed and falls back to the native X11/Wayland clipboard otherwise — no `wl-clipboard` or `xclip` required.

**Vision fallback for image reads**

When the active model has no vision support but reads an image with `read_file`, the `builtin:image_describe` hook replaces the image bytes with the `vision_model`'s description (subagents inherit it). The `vision_model` may sit on another provider than the active model:

```toml
# ~/.vibe/config.toml
active_model = "mistral-large-4"   # blind: reads images via the fallback

[vision_model]                     # may sit on another provider
name = "mistral-large-4-0"
provider = "mistral"
alias = "vision"
supports_images = true             # required
```

**Provider model auto-discovery**

Flag a provider with `discover = true` and Vibe lists every model its `/models` endpoint offers in `/model` and `/config`'s `active_model`. Lists are fetched once per boot, cached in `/tmp/vibe-<uid>/discovered-models.json` (a private per-user directory, emptied on reboot), and `/model refresh` refetches them. Explicit `[[models]]` entries win field by field.

```toml
# ~/.vibe/config.toml
[[providers]]
name = "openrouter"
api_base = "https://openrouter.ai/api/v1"
api_key_env_var = "OPENROUTER_API_KEY"
discover = true  # list every model GET {api_base}/models returns

[[providers]]
name = "mistral"
api_base = "https://api.mistral.ai/v1"
api_key_env_var = "MISTRAL_API_KEY"
discover = true  # also auto-discovers Mistral's model catalog
```

**Session tabs**

Open several sessions side by side in one window. When more than one tab is open, a tab bar shows above the conversation:

- `/tab new` opens a fresh session in a new tab (opening a session from `/sessions` opens it as a new tab too)
- `Tab` / `Shift+Tab` step through the tabs (wrapping), `Alt+1-9` jumps to a numbered tab, a click on a tab switches to it, a middle click closes it
- `/tab next|prev|close [N]|N` does the same from the prompt
- Each tab keeps its conversation, scroll position and draft while another tab is active; switching waits for the current turn to finish (only the active tab is attached)

Tabs are **on by default**; hide the tab bar and disable the keys with:

```toml
# ~/.vibe/config.toml  (or toggle `enable_session_tabs` in /config)
enable_session_tabs = false
```

**Telemetry kill switch**

Vibe sends telemetry to Mistral when you use a Mistral API key or sign-in: usage/tool events to `api.mistral.ai/v1/datalake/events`, crash reports to Sentry (`*.ingest.sentry.io`), OpenTelemetry traces to `/telemetry/v1/traces` (with `enable_otel = true`), and GrowthBook A/B evals to `experiments.mistral.services`.

The kill switch disables **all** of it, regardless of `enable_telemetry`:

```toml
# ~/.vibe/config.toml  (or toggle `disable_all_telemetry` in /config)
disable_all_telemetry = true
```

- **Off by default** (`false`), so installing this fork does not change what is sent and cannot get you banned on its own.
- **DANGEROUS when enabled**: it is flagged red in `/config` and warns on save. Disabling telemetry may violate the Terms of Service — this might get you banned when they enact their new fascist dictator policies.
- When enabled, Vibe stops sending all of the above and **deletes the telemetry it stored on disk** (the GrowthBook eval caches under `~/.vibe/` and telemetry payload lines in `~/.vibe/logs/vibe.log`).
- A project's `.vibe/config.toml` or an agent profile can turn the kill switch **on** for its sessions but never off: their `disable_all_telemetry = false` is ignored, same rule as `enable_telemetry`.

**Irremovable telemetry.** Anything already delivered to Mistral's servers cannot be removed from the client: datalake events, Sentry crash reports and GrowthBook experiment assignments already sent, plus the API request, authentication and billing logs your API key generates no matter what (those exist independently of telemetry). The kill switch only stops future collection.

**Blocking at the firewall.** The kill switch already stops these client-side; to also block them network-wide (e.g. for other tools on the machine), block by host, since TLS hides URL paths (SNI-based filtering only matters if you must keep some paths on a shared host):

- `experiments.mistral.services` — GrowthBook experiment evals (safe to block entirely)
- `*.ingest.sentry.io` and regional variants `*.ingest.us.sentry.io`, `*.ingest.eu.sentry.io` — Sentry crash-report ingest (safe to block entirely)
- `api.mistral.ai` — hosts the telemetry paths `/v1/datalake/events` and `/telemetry/*`, but also the chat/completions API itself; block the whole host only with a self-hosted `api_base`, otherwise block just those paths through a TLS-terminating proxy

DNS sinkhole example (`/etc/hosts` works for exact hosts; use Pi-hole/AdGuard or a firewall for the `*.ingest.sentry.io` wildcard):

```
0.0.0.0 experiments.mistral.services
```

**Contribute**

- Just open a pull request and I will review it as soon as possible

**Contact**

[me@h3x.to](mailto:me@h3x.to)
[pierre@merckel.dev](mailto:pierre@merckel.dev)
