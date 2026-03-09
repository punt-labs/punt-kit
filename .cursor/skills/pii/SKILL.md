---
name: pii
description: Scan for personally identifiable information
disable-model-invocation: true
---

# Punt PII

Scan a repository for personally identifiable information (emails, local paths, hostnames).

## Input

If the user provided a project path as an argument, use it. Otherwise default to `.`. The user may also pass `--staged` for pre-commit use or `--config FILE` for a custom config.

## Process

Run in the shell:

```bash
punt pii <path> [--staged] [--config FILE]
```

using the path and flags from the user's input.

Report the output to the user. If findings are detected, explain each category and suggest remediation (replace personal emails with org identity, use relative paths, etc.).

If the user wants to configure allowlists, point them to `[tool.punt.pii]` in `pyproject.toml` or `.punt-pii.toml` for non-Python projects.
