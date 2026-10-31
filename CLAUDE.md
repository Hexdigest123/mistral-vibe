# CLAUDE.md

Instructions for Claude Code in this repository. The project's agent guide is
`AGENTS.md`, imported here in full; follow all of it.

@AGENTS.md

## Fork features: mandatory in every task

This repository is a fork with features upstream Mistral Vibe does not have.
They are listed in the `AGENTS.md` "Fork features" table and specified, with
their contracts and rebuild steps, in the skill imported at the end of this
file. These rules hold in every scenario and override any pull toward
simplifying, cleaning up, or matching upstream:

- Never remove, disable, hide, or degrade a fork feature: not in a feature
  task, a refactor, a cleanup, an upstream merge, or a conflict resolution.
  "Upstream does not have it" or "it conflicts with upstream" is never a reason.
- When an upstream merge rewrites or deletes the code a fork feature lives in,
  re-implement the feature on the new code in that same merge, from its
  contract. Do not report a merge as done while a fork feature is missing.
- Before reporting any change as done, run `uv run pytest
  tests/test_fork_features.py` and the guard tests of every fork feature the
  change touches (plus `make test_golden` for TUI changes). If a guard fails,
  fix the code; never the guard.
- Never delete, skip, xfail, or weaken a guard test or fork golden, and never
  shorten `GUARD_TESTS` in `tests/test_fork_features.py`.
- Mark every hook from upstream code into fork code with `Fork feature
  (AGENTS.md "Fork features")`, and register any new fork feature in the
  `AGENTS.md` table, the skill, and `GUARD_TESTS` in the same change.
- If a request would remove or change what a fork feature does, tell the user
  and get their explicit go-ahead first.

@.agents/skills/vibe-fork-features/SKILL.md
