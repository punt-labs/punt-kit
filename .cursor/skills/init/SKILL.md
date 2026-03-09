---
name: init
description: Scaffold missing files for a Punt Labs project
disable-model-invocation: true
---

# Punt Init

Run the deterministic scaffolding tool for a Punt Labs project.

## Input

If the user provided a project path as an argument, use it. Otherwise default to `.`.

## Process

First, run detection to see what we're working with:

```bash
punt init --language "" <path> 2>&1 || true
```

If the output shows `Language: none`, ask the user which language the project uses (python, node, swift), then re-run with the flag:

```bash
punt init --language <chosen-language> <path>
```

If a language was detected, just run:

```bash
punt init <path>
```

Report the output to the user. Explain what files were generated and what manual steps remain.

If the user wants contextual reconciliation (workflow diffing, CLAUDE.md quality review, permission cleanup), suggest the reconcile skill as the next step.
