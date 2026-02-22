---
description: Scaffold missing files for a Punt Labs project
argument-hint: "[project-path]"
allowed-tools: Bash(punt:*), AskUserQuestion
---

# Punt Init

Run the deterministic scaffolding tool for a Punt Labs project.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

First, run detection to see what we're working with:

```bash
punt init --language "" $ARGUMENTS 2>&1 || true
```

If the output shows `Language: none`, ask the user which language the project
uses (python, node, swift) via AskUserQuestion, then re-run with the flag:

```bash
punt init --language <chosen-language> $ARGUMENTS
```

If a language was detected, just run:

```bash
punt init $ARGUMENTS
```

Report the output to the user. Explain what files were generated and what manual steps remain.

If the user wants contextual reconciliation (workflow diffing, CLAUDE.md quality review, permission cleanup), suggest `/punt reconcile` as the next step.
