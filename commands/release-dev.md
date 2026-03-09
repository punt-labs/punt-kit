---
description: "[DEV] Guided release workflow using the working tree"
argument-hint: "[version]"
allowed-tools: Bash(git:*), Bash(gh:*), Bash(uv:*), Bash(uvx:*), Bash(punt:*), Bash(rm:*), Bash(bash:*), Bash(curl:*), Bash(python3:*), Bash(claude:*), Read, Edit, Write, Glob, Grep, AskUserQuestion
---

# Release a Punt Labs Project (Dev)

This is the **working tree** version of `/punt release`. Use this when
developing punt-kit itself — it ensures the release workflow reads command
definitions from the local checkout rather than the installed plugin cache.

## Input

Version: $ARGUMENTS (if empty, ask user in Phase 2)

## Process

Follow the full release workflow in `${CLAUDE_PLUGIN_ROOT}/commands/release.md`
(Steps 1-5: CLI, propagation merges, website sync, profile update, verification).

If any step calls the `punt` CLI, replace with:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt release $ARGUMENTS
```
