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

- Added support for pasting images from the clipboard on Linux
- Custom provider tag \[provider\] with automatic discovery of the provider's models (see [Provider model auto-discovery](#provider-model-auto-discovery))
  - Also auto-discovers Mistral's model catalog, since `mistral-large-4` is still listed with a 400k max context window, which is simply false
- FZF search in settings and the model catalog
- Builds to `vibes` instead of `vibe` (for my personal testing)
- Optional telemetry kill switch `disable_all_telemetry` (see [Telemetry kill switch](#telemetry-kill-switch)): **off by default**, so installing this fork changes nothing; when you enable it, ALL telemetry is disabled and locally stored telemetry is deleted
  - It is flagged DANGEROUS in the settings: this might get you banned when they enact their new fascist dictator policies

**Where to find the settings**

- In the CLI: `/config` opens the settings screen (type `/` to search, e.g. `/telemetry`); every setting can also be edited there and is written to `~/.vibe/config.toml`
- Or edit the TOML directly: `~/.vibe/config.toml` (user-wide) or `.vibe/config.toml` in a trusted project
- `/model` lists the models, with fzf search and `/model refresh`

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
