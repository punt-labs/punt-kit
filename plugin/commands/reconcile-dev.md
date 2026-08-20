---
description: "[DEV] LLM-powered standards reconciliation using the working tree"
argument-hint: "[project-path]"
allowed-tools: Read, Glob, Grep, Edit, Write, Bash(uv:*), Bash(punt:*), Bash(git:*)
---

# Reconcile Project with Punt Labs Standards (Dev)

This is the **working tree** version of `/punt reconcile`. It uses the local
punt-kit source (via `uv run`) instead of the installed CLI. Use this when
developing punt-kit to test reconciliation changes before publishing.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

Follow the same process as `/punt reconcile`, but replace any `punt` CLI calls with:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT}/.. punt <subcommand> $ARGUMENTS
```

This ensures the working tree code is exercised, not the installed release.
`${CLAUDE_PLUGIN_ROOT}` is the repo's `plugin/` subdirectory, which carries no
`pyproject.toml`; `uv run` needs the project root, hence the `/..`.

Refer to the full reconciliation process in `${CLAUDE_PLUGIN_ROOT}/commands/reconcile.md`
for the complete workflow (detect, audit, load standards, reconcile workflows/CLAUDE.md/pyproject.toml, report).
