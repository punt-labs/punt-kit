---
description: "[DEV] Scaffold missing files using the working tree"
argument-hint: "[project-path]"
allowed-tools: Bash(uv:*), Bash(punt:*), AskUserQuestion
---

# Punt Init (Dev)

Run the scaffolding tool from the **local working tree** (not the installed CLI).
Use this when developing punt-kit to test changes before publishing.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

First, run detection to see what we're working with:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt init --language "" $ARGUMENTS 2>&1 || true
```

If the output shows `Language: none`, ask the user which language the project
uses (python, node, swift) via AskUserQuestion, then re-run with the flag:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt init --language <chosen-language> $ARGUMENTS
```

If a language was detected, just run:

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT} punt init $ARGUMENTS
```

Report the output to the user. Explain what files were generated and what manual steps remain.

If the user wants contextual reconciliation, suggest `/punt reconcile` as the next step.
