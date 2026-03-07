---
description: "[DEV] Guided release workflow using the working tree"
argument-hint: "[version]"
allowed-tools: Bash(git:*), Bash(gh:*), Bash(uv:*), Bash(uvx:*), Bash(punt:*), Bash(rm:*), Bash(bash:*), Bash(claude:*), Read, Edit, Write, Glob, Grep, AskUserQuestion
---

# Release a Punt Labs Project (Dev)

This is the **working tree** version of `/punt release`. Use this when
developing punt-kit itself — it ensures the release workflow reads command
definitions from the local checkout rather than the installed plugin cache.

The current release workflow uses `git`, `gh`, `uv`, and `claude` directly
(no `punt` CLI calls). The dev variant exists so that when future phases add
`punt` subcommands (e.g., `punt release-check`), the dev path is already
wired to use `uv run --directory ${CLAUDE_PLUGIN_ROOT} punt <subcommand>`
instead of the installed binary.

## Input

Version: $ARGUMENTS (if empty, ask user in Phase 2)

## Process

Follow the full release workflow in `${CLAUDE_PLUGIN_ROOT}/commands/release.md`
(11 phases: pre-flight, version bump, build, tag, CI, GitHub release, PyPI
verify, marketplace, website, install-all, summary).

If any phase calls the `punt` CLI, replace with:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt <subcommand> $ARGUMENTS
```
