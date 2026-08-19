---
description: Scan for personally identifiable information
argument-hint: "[project-path] [--staged] [--config FILE]"
allowed-tools: Bash(punt:*)
---

# Punt PII

Scan a repository for personally identifiable information (emails, local paths, hostnames).

## Input

Arguments: $ARGUMENTS (defaults to `.` if empty; pass `--staged` for pre-commit use)

## Process

Run the PII scanner:

```bash
punt pii $ARGUMENTS
```

Report the output to the user. If findings are detected, explain each category and suggest remediation (replace personal emails with org identity, use relative paths, etc.).

If the user wants to configure allowlists, point them to `[tool.punt.pii]` in `pyproject.toml` or `.punt-pii.toml` for non-Python projects.
