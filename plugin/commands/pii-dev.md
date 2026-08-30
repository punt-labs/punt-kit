---
description: "[DEV] Scan for PII using the working tree"
argument-hint: "[project-path] [--staged] [--config FILE]"
allowed-tools: Bash(uv:*), Bash(punt:*)
---

# Punt PII (Dev)

Scan a repository for PII using the **local working tree** (not the installed CLI).
Use this when developing punt-kit to test changes before publishing.

## Input

Arguments: $ARGUMENTS (defaults to `.` if empty; pass `--staged` for pre-commit use)

## Process

Run from the working tree. `${CLAUDE_PLUGIN_ROOT}` is the repo's `plugin/`
subdirectory, which carries no `pyproject.toml`; `uv run` needs the project
root, hence the `/..`.

```bash
uv run --directory ${CLAUDE_PLUGIN_ROOT}/.. punt pii $ARGUMENTS
```

Report the output to the user. If findings are detected, explain each category and suggest remediation.
