---
description: "Autonomous bead-driven development loop"
allowed-tools:
  - "Bash(git:*)"
  - "Bash(gh:*)"
  - "Bash(bd:*)"
  - "Bash(uv:*)"
  - "Bash(make:*)"
  - "Bash(shellcheck:*)"
  - "Bash(npx:*)"
  - "Bash(npm:*)"
  - "mcp__github__*"
  - "mcp__plugin_github_github__*"
---

# /autopilot — Autonomous Development Loop

Run a continuous bead-driven development cycle. Minimize permission prompts — use allowed tools above and avoid unnecessary confirmations.

## Setup

On first iteration only:

1. Check `/who` for other active sessions.
2. If other sessions are active, use `EnterWorktree` to avoid interfering with their working tree. One worktree per session — branch freely inside it for each PR.
3. If no other sessions are active, work directly on feature branches.

Never remove a worktree from inside it — the session cwd becomes invalid. Let `/exit` handle worktree cleanup at session end.

## Loop

Repeat continuously until the user interrupts or no beads remain:

### 1. Pick a bead

Run `bd ready` to show available work. Pick the highest-priority unblocked bead. If multiple beads share the same priority, ask the user. Once selected, run `bd show <id>` and `bd update <id> --status=in_progress`.

### 2. Assess complexity

Read the bead, identify affected files, and classify:

- **Small** (1-3 files, <50 lines): proceed directly
- **Medium** (3-8 files, 50-200 lines): use EnterPlanMode, get approval, then implement
- **Large** (8+ files or architectural): use EnterPlanMode, break into sub-tasks if needed

### 3. Branch

Create a feature branch from latest main:

```bash
# In a worktree (detached HEAD):
git fetch origin main && git checkout origin/main
git checkout -b <prefix>/<short-name>

# On main directly:
git checkout -b <prefix>/<short-name> main
```

Use the appropriate prefix: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.

### 4. Implement

Write the solution. Follow CLAUDE.md standards. Micro-commits are fine but not required — one clean commit per bead is acceptable.

### 5. Quality gates

Run the project's quality gates as defined in its CLAUDE.md. Fix any failures before proceeding. Do not skip or weaken gates.

If ruff format fails, run `uv run ruff format src/ tests/` and re-check. If lint or type errors, fix them. If tests fail, fix the root cause.

### 6. Commit and push

Stage changed files by name (not `git add -A`). Commit with `type(scope): description` format. Push with `-u`.

### 7. Open PR

Use `gh pr create` with a summary and test plan. Keep title under 70 chars. Never target main with a direct push — always go through a PR.

### 8. CI and Copilot review

This step is **hard-blocking**. Do not proceed to merge until both CI passes and Copilot review arrives. No exceptions. No theories about why a review might not come. Copilot always reviews — it just takes 5-10 minutes.

1. Request Copilot review:

   ```bash
   # Use MCP tool (works in worktrees, no local side effects)
   mcp__github__request_copilot_review(owner="punt-labs", repo="<repo>", pullNumber=<N>)
   ```

2. Wait for CI checks to pass:

   ```bash
   gh pr checks <number> --watch    # Blocks until all checks resolve
   ```

3. Wait for Copilot review. CI passing does NOT mean Copilot has reviewed — those are independent. Poll until the review appears:

   ```bash
   gh pr view <number> --json reviews --jq '.reviews[] | select(.author.login == "copilot-pull-request-reviewer") | .submittedAt'
   ```

   If empty, wait 60 seconds and poll again. **Keep polling for at least 15 minutes.** Do not invent theories about why the review is absent (e.g., "Copilot doesn't review markdown files" — wrong). If no review after 15 minutes, ask the user whether to continue waiting or merge without review.

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

Use the MCP tool to merge — never `gh pr merge` (it tries to checkout main locally, which fails in worktrees):

```bash
mcp__github__merge_pull_request(owner="punt-labs", repo="<repo>", pullNumber=<N>, merge_method="squash")
```

Then update local state for the next branch:

```bash
# In a worktree (can't checkout main branch):
git fetch origin main && git checkout origin/main

# On main directly:
git checkout main && git pull
```

### 10. Close bead and continue

Run `bd close <id>`. Then immediately go to step 1 for the next bead. Do not ask "Ready for the next bead?" — keep the flow continuous. The user will interrupt if they want to stop.

When there are no more beads or the user stops the loop, run the session close protocol:

```bash
bd sync
git status    # Must be clean
```

If in a worktree, do not clean it up manually — `/exit` prompts to keep or remove it.

## Principles

- Never push directly to main. All changes go through PRs.
- Never skip Copilot review. Always wait for CI and review before merging.
- Never use `gh pr merge` — use the MCP merge tool.
- Do not ask for permission for routine operations (git, tests, lint, PR creation). The allowed-tools list covers these.
- Do ask the user before: architectural decisions not covered by the bead, or anything that changes project scope.
- If blocked, diagnose the root cause. Do not retry blindly.
- If a quality gate fails, fix it. Do not skip it.
- Update CHANGELOG.md for user-visible changes.
