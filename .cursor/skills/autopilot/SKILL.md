---
name: autopilot
description: Autonomous bead-driven development loop
disable-model-invocation: true
---

# Autopilot — Autonomous Development Loop

Run a continuous bead-driven development cycle.

## Setup

On first iteration only:

1. Check if other active sessions exist (e.g., via `biff who` or process list).
2. If other sessions are active, work in a separate git worktree to avoid interfering. Create one worktree and branch freely inside it for each PR.
3. If no other sessions are active, work directly on feature branches.

## Loop

Repeat continuously until the user interrupts or no beads remain:

### 1. Pick a bead

Run `bd ready` to show available work. Pick the highest-priority unblocked bead. If multiple beads share the same priority, ask the user. Once selected, run `bd show <id>` and `bd update <id> --status=in_progress`.

### 2. Assess complexity

Read the bead, identify affected files, and classify:

- **Small** (1-3 files, <50 lines): proceed directly
- **Medium** (3-8 files, 50-200 lines): plan first, get approval, then implement
- **Large** (8+ files or architectural): plan first, break into sub-tasks if needed

### 3. Branch

Create a feature branch from latest main:

```bash
git fetch origin main
git checkout -b <prefix>/<short-name> origin/main
```

Use the appropriate prefix: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.

### 4. Implement

Write the solution. Follow CLAUDE.md standards. One clean commit per bead is acceptable.

### 5. Quality gates

Run the project's quality gates as defined in its CLAUDE.md (typically `make check`). Fix any failures before proceeding. Do not skip or weaken gates.

If ruff format fails, run `uv run ruff format src/ tests/` and re-check. If lint or type errors, fix them. If tests fail, fix the root cause.

### 6. Commit and push

Stage changed files by name (not `git add -A`). Commit with `type(scope): description` format. Push with `-u`.

### 7. Open PR

Use `gh pr create` with a summary and test plan. Keep title under 70 chars. Never target main with a direct push — always go through a PR.

### 8. CI and Copilot review

This step is **hard-blocking**. Do not proceed to merge until both CI passes and Copilot review arrives.

1. Request Copilot review:

   ```bash
   gh api repos/punt-labs/<repo>/pulls/<N>/requested_reviewers -f '{"reviewers":["copilot-pull-request-reviewer"]}'
   ```

2. Wait for CI checks to pass:

   ```bash
   gh pr checks <number> --watch
   ```

3. Wait for Copilot review (poll until it appears):

   ```bash
   gh pr view <number> --json reviews --jq '.reviews[] | select(.author.login == "copilot-pull-request-reviewer") | .submittedAt'
   ```

   If empty, wait 60 seconds and poll again. Keep polling for at least 15 minutes. If no review after 15 minutes, ask the user whether to continue waiting or merge without review.

4. Read Copilot feedback:

   ```bash
   gh pr view <number> --comments
   ```

5. Address feedback:
   - **0 issues**: proceed to merge
   - **1-3 issues**: fix, push, request another review (up to 2 rounds)
   - **4+ issues**: fix, push, request another review (up to 3 rounds)

If issues persist after max rounds, summarize remaining items and ask the user whether to merge or continue iterating.

### 9. Merge

```bash
gh pr merge <number> --squash --delete-branch
```

Then update local state:

```bash
git checkout main && git pull
```

### 10. Close bead and continue

Run `bd close <id>`. Then immediately go to step 1 for the next bead. Do not ask "Ready for the next bead?" — keep the flow continuous. The user will interrupt if they want to stop.

When there are no more beads or the user stops the loop, run:

```bash
bd sync
git status    # Must be clean
```

## Principles

- Never push directly to main. All changes go through PRs.
- Never skip Copilot review. Always wait for CI and review before merging.
- Do not ask for permission for routine operations (git, tests, lint, PR creation).
- Do ask the user before: architectural decisions not covered by the bead, or anything that changes project scope.
- If blocked, diagnose the root cause. Do not retry blindly.
- If a quality gate fails, fix it. Do not skip it.
- Update CHANGELOG.md for user-visible changes.
