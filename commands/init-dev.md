---
description: "[DEV] Scaffold missing files using the working tree"
argument-hint: "[project-path]"
allowed-tools: Bash(uv:*), Bash(punt:*)
---

# Punt Init (Dev)

Run the scaffolding tool from the **local working tree** (not the installed CLI).
Use this when developing punt-kit to test changes before publishing.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

Run from the working tree:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt init $ARGUMENTS
```

Report the output to the user. Explain what files were generated and what manual steps remain.

If the user wants contextual reconciliation, suggest `/punt reconcile` as the next step.
