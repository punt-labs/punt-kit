---
description: Check compliance against Punt Labs standards
argument-hint: "[project-path] [--fix]"
allowed-tools: Bash(punt:*)
---

# Punt Audit

Run the deterministic compliance checker for a Punt Labs project.

## Input

Arguments: $ARGUMENTS (defaults to `.` if empty; pass `--fix` to auto-create missing mechanical files)

## Process

Run the audit command:

```bash
punt audit $ARGUMENTS
```

Report the output to the user. Summarize the pass/fail results.

If there are failures that `--fix` can resolve, suggest re-running with `--fix`. For issues requiring contextual judgment, suggest `/punt reconcile`.
