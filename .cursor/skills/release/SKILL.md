---
name: release
description: Guided release workflow for a Punt Labs project
disable-model-invocation: true
---

# Release a Punt Labs Project

Run the deterministic release CLI, falling back to guided mode on failure.

## Input

If the user provided a version as an argument, use it. Otherwise it will be auto-detected from CHANGELOG.md.

## Step 1: Run the CLI

Run in the shell:

```bash
punt release [version]
```

If this succeeds, the release is complete. Print the summary and stop.

## Step 2: Handle failure

If `punt release` fails, read the error output carefully.

### Recoverable failures

- **Quality gate failure**: Fix the issue, then re-run `punt release [version]`.
- **CI failure**: The tag is already pushed. Wait for the user to fix CI, then resume
  from Phase 5 onward by running the remaining steps manually.
- **PyPI propagation timeout**: Re-run `punt release [version]`. If it fails
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

2. **Confirm before pushing.** Ask the user before any `git push`.
   The CLI prints a warning before pushing but does not prompt interactively.

3. **One project at a time.** Release the project in the current working directory.

4. **Follow the project's CLAUDE.md.** If the project documents additional release steps
   or overrides, follow those instead.
