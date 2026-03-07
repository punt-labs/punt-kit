---
description: Guided release workflow for a Punt Labs project
argument-hint: "[version]"
allowed-tools: Bash(punt:*), Bash(git:*), Bash(gh:*), Bash(uv:*), Bash(uvx:*), Bash(rm:*), Bash(bash:*), Read, Edit, Write, Glob, Grep, AskUserQuestion
---

# Release a Punt Labs Project

Run the deterministic release CLI, falling back to guided mode on failure.

## Input

Version: $ARGUMENTS (if empty, auto-detected from CHANGELOG.md)

## Step 1: Run the CLI

```bash
punt release $ARGUMENTS
```

If this succeeds, the release is complete. Print the summary and stop.

## Step 2: Handle failure

If `punt release` fails, read the error output carefully.

### Recoverable failures

- **Quality gate failure**: Fix the issue, then re-run `punt release $ARGUMENTS`.
- **CI failure**: The tag is already pushed. Wait for the user to fix CI, then resume
  from Phase 5 onward by running the remaining steps manually.
- **PyPI propagation timeout**: Re-run `punt release $ARGUMENTS`. If it fails
  early because the version has already been bumped or tagged, resume from the
  appropriate later phase manually.

### Non-recoverable failures

If the CLI is not installed or crashes unexpectedly, fall back to the guided workflow:

1. Ask the user for the target version if not provided.
2. Walk through each phase manually, using the phase structure from `punt release --dry-run`
   as a guide.
3. For each phase, run the equivalent commands directly.

## Important Rules

1. **Stop on failure.** Every phase is a gate. If quality gates fail, CI fails, or a build
   fails — stop and report. Do not skip phases.

2. **Confirm before pushing.** In guided mode, ask the user before any `git push`.
   The CLI prints a warning before pushing but does not prompt interactively.

3. **One project at a time.** Release the project in the current working directory.

4. **Follow the project's CLAUDE.md.** If the project documents additional release steps
   or overrides, follow those instead.
