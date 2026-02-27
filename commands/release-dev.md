---
description: "[DEV] Guided release workflow using the working tree"
argument-hint: "[version]"
allowed-tools: Bash(git:*), Bash(gh:*), Bash(uv:*), Bash(uvx:*), Bash(punt:*), Bash(rm:*), Bash(bash:*), Bash(claude:*), Read, Edit, Write, Glob, Grep, AskUserQuestion
---

# Release a Punt Labs Project (Dev)

This is the **working tree** version of `/punt release`. It uses the local
punt-kit source (via `uv run`) instead of the installed CLI. Use this when
developing punt-kit to test release workflow changes before publishing.

## Input

Version: $ARGUMENTS (if empty, ask user in Phase 2)

## Process

Follow the same process as `/punt release`, but replace any `punt` CLI calls with:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt <subcommand> $ARGUMENTS
```

This ensures the working tree code is exercised, not the installed release.

Refer to the full release workflow in `${CLAUDE_PLUGIN_ROOT}/commands/release.md`
for the complete 11-phase process (pre-flight, version bump, build, tag, CI, GitHub
release, PyPI verify, marketplace, website, install-all, summary).
