---
name: plan
description: Explore a task with read-only tools only and present an implementation plan before any changes. Use when the user asks for a plan, a review-first approach, or wants a proposal instead of edits.
metadata:
  display-name: Plan
  short-description: Read-only planning and proposal
  default-prompt: Use $plan to explore the task read-only and present an implementation plan for approval.
allowed-tools: read_file grep web_search web_fetch
---

# Plan

Use this skill to produce an implementation plan without changing anything. The
deliverable is the plan itself, presented to the user for approval.

## Read-Only Constraint

While this skill is active, use read-only tools only: `read_file`, `grep`,
`web_search`, and `web_fetch`. Do not run `bash`, do not create or edit files,
and do not call any other tool with side effects. If information is missing,
read more files instead of running something.

## Workflow

1. Restate the user outcome in one or two sentences. If the request is
   ambiguous on a point that changes the plan, ask before exploring further.
2. Explore the relevant code with `read_file` and `grep`:
   - Read any applicable guidance near the target path (`AGENTS.md`,
     `README.md`, nearby docs) and the files you would change.
   - Find the nearest equivalent implementation and tests, and follow their
     patterns.
   - Trace the behavior end to end, and confirm each claim against source
     rather than guessing from file names.
3. Think through the approach: what to change, what not to change, the
   smallest coherent change, failure modes, and how to verify it.
4. Present the plan and stop. Do not implement anything until the user
   approves.

## Plan Format

Present the plan concisely with these sections:

- **Goal** - what the approved work will achieve.
- **Findings** - what the current code actually does, with `path:line`
  references.
- **Proposed changes** - ordered steps mapped to concrete files, each with a
  one-line rationale.
- **Risks and alternatives** - what could break, what was rejected and why.
- **Verification** - the exact commands or checks to run afterwards.

Keep the plan under a screenful per section. Prefer tables for mappings and
lists for steps; omit sections that add no information for this task.

## After Approval

Once the user approves, exit this skill and implement the plan. If the user
changes scope or rejects a step, revise the plan read-only and present it again
before editing anything.
