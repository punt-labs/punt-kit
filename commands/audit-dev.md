---
description: "[DEV] Check compliance using the working tree"
argument-hint: "[project-path] [--fix]"
allowed-tools: Bash(uv:*), Bash(punt:*)
---

# Punt Audit (Dev)

Run the compliance checker from the **local working tree** (not the installed CLI).
Use this when developing punt-kit to test changes before publishing.

## Input

Arguments: $ARGUMENTS (defaults to `.` if empty; pass `--fix` to auto-create missing mechanical files)

## Process

Run from the working tree:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt audit $ARGUMENTS
```

Report the output to the user. Summarize the pass/fail results.

If there are failures that `--fix` can resolve, suggest re-running with `--fix`. For issues requiring contextual judgment, suggest `/punt reconcile`.
