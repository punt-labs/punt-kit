---
name: audit
description: Check compliance against Punt Labs standards
disable-model-invocation: true
---

# Punt Audit

Run the deterministic compliance checker for a Punt Labs project.

## Input

If the user provided a project path as an argument, use it. Otherwise default to `.`. The user may also pass `--fix` to auto-create missing mechanical files.

## Process

Run in the shell:

```bash
punt audit <path> [--fix]
```

using the path and flags from the user's input.

Report the output to the user. Summarize the pass/fail results.

If there are failures that `--fix` can resolve, suggest re-running with `--fix`. For issues requiring contextual judgment, suggest running the reconcile skill.
