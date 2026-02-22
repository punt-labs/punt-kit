---
description: Scaffold missing files for a Punt Labs project
argument-hint: "[project-path]"
allowed-tools: Bash(punt:*)
---

# Punt Init

Run the deterministic scaffolding tool for a Punt Labs project.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

Run the init command:

```bash
punt init $ARGUMENTS
```

Report the output to the user. Explain what files were generated and what manual steps remain.

If the user wants contextual reconciliation (workflow diffing, CLAUDE.md quality review, permission cleanup), suggest `/punt reconcile` as the next step.
