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
- Custom provider tag \[provider\] with automatic discovery of the provider's models
  - Also auto-discovers Mistral's model catalog, since `mistral-large-4` is still listed with a 400k max context window, which is simply false
- FZF search in settings and the model catalog
- Builds to `vibes` instead of `vibe` (for my personal testing)
- Removes all telemetry by default (it can be re-enabled in settings); by default, nothing besides your prompt and its required metadata is sent to mistral.ai
  - This might get you banned when they enact their new dictator policy

**Contribute**

- Just open a pull request and I will review it as soon as possible

**Contact**

[me@h3x.to](mailto:me@h3x.to)
[pierre@merckel.dev](mailto:pierre@merckel.dev)
