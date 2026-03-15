# Workflow Standards

How Punt Labs teams track work, develop code, and collaborate.

---

## 1. Issue Tracking

All projects use **beads** (`bd`) for issue tracking.

### Setup

Every repo must have beads initialized (`bd init`). The `.beads/` directory is committed to git.

### Workflow

- `bd create "title"` to create issues with `--type` (task, bug, feature, spike) and `--priority` (1-5)
- `bd ready` to find available work
- `bd update <id> --status in_progress` before starting
- `bd close <id>` when complete
- Work is not complete until `git push` succeeds

### Issue Quality

Issues must have:

- A clear title in imperative form
- A description with enough context for another engineer (or agent) to act on
- Correct type and priority
- Dependencies declared (`--blocks`, `--blocked-by`) when applicable

### Beads vs TodoWrite

| Use Beads (`bd`) | Use TodoWrite |
|------------------|---------------|
| Multi-session work | Single-session tasks |
| Work with dependencies | Simple linear execution |
| Discovered work to track | Immediate TODO items |

---

## 2. Workflow Tiers

Match the workflow to the scope. The deciding factor is **design ambiguity**, not size.

| Tier | Tool | When | Tracking |
|------|------|------|----------|
| **T1: Feature Dev** | `/feature-dev` | Features, multi-file, clear goal but needs exploration | Beads + TodoWrite (internal) |
| **T2: Direct** | Plan mode or manual | Tasks, bugs, obvious implementation path | Beads |

### Decision flow

1. Does it touch multiple files and benefit from codebase exploration? → **T1: Feature Dev**
2. Otherwise → **T2: Direct** (plan mode if >3 files, manual if fewer)

### Escalation

Escalation only goes up. If T2 reveals unexpected scope, escalate to T1. Never demote mid-flight.

---

## 3. Coordination

### Biff plan

When biff is enabled, set a biff plan (`/plan "short description"` — this is the biff `/plan` command, not Claude plan mode) before starting work so teammates and other agents can see what you're doing.

### Worktree sharing

If `/who` shows more than 1 user active in the same repo (human or agent), work in a worktree to avoid file conflicts. Use `git worktree add` or the `--worktree` session flag.

---

## 4. Branch Discipline

All code changes go on feature branches. Never commit directly to main. Branch protection rulesets enforce this — there are zero bypass actors, so even admins cannot push to main.

```bash
git checkout -b feat/short-description main
# ... work, commit, push ...
# create PR, complete code review, merge, then delete branch
```

### Branch prefixes

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code improvements |
| `docs/` | Documentation only |
| `release/` | Release version bumps (created by `punt release`) |
| `post-release/` | Post-release cleanup (created by `punt release`) |
| `propagate/` | Cross-repo propagation (created by `punt release`) |
| `chore/` | Maintenance and housekeeping |

---

## 5. Commits

### Micro-commits

One logical change per commit. 1–5 files, under 100 lines. Quality gates pass before every commit.

### Conventional commit messages

Format: `type(scope): description`

| Prefix | Use |
|--------|-----|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `refactor:` | Code change, no behavior change |
| `test:` | Adding or updating tests |
| `docs:` | Documentation |
| `chore:` | Build, dependencies, CI |

The `(scope)` is optional. Use it when the repo has distinct modules (e.g., `feat(relay): add heartbeat`).

---

## 6. Quality Gates

Quality gates must pass before every commit. The specific commands depend on the project type.

### By project type

| Project type | Quality gates |
|-------------|---------------|
| Python | `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy src/ tests/` · `uv run pyright` · `uv run pytest` |
| Node.js | `npm run lint` · `npm test` |
| Plugin (prompts) | `markdownlint-cli2 "**/*.md"` |
| Docs/standards | `markdownlint-cli2 "**/*.md"` |
| Shell scripts (cross-cutting) | `shellcheck <scripts>` — applies to any project with `.sh` files. See [Shell standards](shell.md). |

Zero violations, zero errors, all tests green. No exceptions.

### When gates fail

Fix the issue immediately. Do not commit with known failures. Do not skip gates with `--no-verify` or equivalent.

---

## 7. Test-Driven Development

Use a test-first approach when feasible: write failing tests, then write the code that makes them pass.

### When TDD applies

- New functions or methods
- Behavior changes to existing code
- Bug reproductions (the test proves the bug exists before the fix)

### When TDD does not apply

- Documentation-only changes
- Configuration or template changes
- Refactors with no behavior change (existing tests cover them)
- Exploratory spikes (but tests must be added before the spike code merges)

### Workflow

1. Write a test that expresses the expected behavior. Run it — confirm it fails.
2. Write the minimum code to make the test pass.
3. Run the repo's quality gates (see §6). Refactor if needed while keeping tests green.

This is not dogma. If writing the test first is impractical (e.g., you need to understand the interface before you can test it), write the code first and the test immediately after. The rule is: **tests and code land in the same commit**.

---

## 8. CHANGELOG Discipline

Projects that maintain a CHANGELOG follow [Keep a Changelog](https://keepachangelog.com/) format.

### Timing

CHANGELOG entries are written **in the PR branch, before merge** — not retroactively on main. The entry is part of the diff that gets reviewed. If a PR changes user-facing behavior and the diff does not include a CHANGELOG entry, the PR is not ready to merge.

### What gets an entry

- New commands, features, agents, or reference guides → `### Added`
- Behavior changes to existing commands → `### Changed`
- Bug fixes → `### Fixed`
- Removed features or commands → `### Removed`

### What does NOT get an entry

- Internal-only changes (CLAUDE.md, CI config, dev tooling, test-only changes)
- Dependency updates with no user-visible effect
- Plugin cache, session transcripts, research files

### Format

- Entries go under `## Unreleased` (or `## [Unreleased]` for semver projects)
- Group under `### Added`, `### Changed`, `### Fixed`, `### Removed` (in that order, omit empty groups)
- Each entry starts with the component name (e.g., `` `/prfaq:vote` ``, `Installer`, `Status line`)
- One logical change per bullet — sub-bullets for supporting detail
- At release time, move `Unreleased` entries to a versioned heading

---

## 9. Pre-PR Checklist

Before creating a pull request, verify:

- [ ] Quality gates pass (see §6)
- [ ] **CHANGELOG entry included in the PR diff** under `## [Unreleased]` for notable changes (see §8)
- [ ] **Local code review passed** (see §10) — `feature-dev:code-reviewer` + `pr-review-toolkit:silent-failure-hunter`
- [ ] **README updated** if user-facing behavior changed (new flags, commands, defaults, config)
- [ ] **prfaq.tex updated** if the change shifts product direction or validates/invalidates a risk
- [ ] Version bumped if user-facing behavior changed (if the project uses semver)

---

## 10. Local Code Review

Before creating a PR, run local code reviews to catch issues early. This reduces remote review cycles from 4–6 down to 2–3.

### Required agents

1. **`feature-dev:code-reviewer`** — reviews for bugs, logic errors, security issues, code quality, and project conventions.
2. **`pr-review-toolkit:silent-failure-hunter`** — reviews for silent failures, inadequate error handling, and inappropriate fallback behavior.

### Process

1. Run both agents on the current diff (unstaged changes or the branch diff vs main).
2. Read all findings. Fix valid issues — there is no "nice to have" vs "must fix" distinction during local review. If it's worth flagging, it's worth fixing.
3. Re-run agents after fixes. Repeat until reviews produce minor or no comments.
4. Only then proceed to create the PR.

### When to skip

Local review is not required for:
- Documentation-only PRs (no code changes)
- Version bumps and release mechanics
- Single-line config changes

---

## 11. Code Review Flow

Do **not** merge immediately after creating a PR. Expect **2–6 review cycles** before merging. The full flow is:

1. **Create PR** — push branch, open PR via `mcp__github__create_pull_request` (prefer MCP GitHub tools over `gh` CLI where possible).
2. **Request Copilot review** — use `mcp__github__request_copilot_review` so Copilot analyzes the diff.
3. **Watch for feedback without blocking your main shell** — run `gh pr checks <number> --watch` in a background task or separate session so it streams CI status while you work:

   ```bash
   gh pr checks <number> --watch         # Run in background task — notifies when checks resolve
   ```

   **Do not stop waiting for feedback.** Copilot and Bugbot may take 1–3 minutes to post after CI completes. Do not assume silence means approval.

4. **Read all feedback** — when the watch completes, read review comments using MCP:

   - `mcp__github__pull_request_read` with `get_reviews` — check review verdicts
   - `mcp__github__pull_request_read` with `get_review_comments` — read inline comments
   - `gh pr view <number> --comments` — fallback for threaded discussion

5. **Take every comment seriously** — read each comment and address it. There is no such thing as "pre-existing" or "unrelated to this change" — if you can see it, you own it. Fix it. If you genuinely disagree, explain why in a reply — do not silently ignore.
6. **Fix and re-push** — commit fixes, push, and re-run quality gates. Each fix commit triggers a new review cycle.
7. **Repeat steps 3–6** until the latest review cycle is **uneventful** — no new comments, no requested changes, all checks green.
8. **Merge only when the last review was clean** — use `mcp__github__merge_pull_request` (not `gh pr merge`, which has local side effects). A PR is ready to merge when:
   - The most recent Copilot/Bugbot review raised **zero new issues**
   - All GitHub Actions are green
   - Local quality gates pass

Quality gates apply at every step. Each commit that addresses review feedback must pass both local checks and CI. A typical PR takes 2–6 cycles. Do not rush to merge after the first review.

---

## 12. Session Close Protocol

Before ending any session, run this checklist:

```bash
git status              # Check for uncommitted work
git add <files>         # Stage changes
bd sync                 # Sync beads with git
git commit -m "..."     # Commit
bd sync                 # Sync any new beads changes
git push                # Push to remote
```

Work is **not** complete until `git push` succeeds.

---

## 13. Work Recap

After merging a PR, send a recap email to jim@punt-labs.com. Use `mcp__beadle-email__send_email` if the beadle-email MCP server is available; otherwise ask the user to send it manually or use an alternative.

### Format

- **Subject**: `[repo-name] PR #N merged: <title>`
- **Required content**: bead ID, PR link, 1-paragraph summary of what changed and why
- **Include when relevant**: key design decisions made, test coverage notes, follow-up work created, risks or caveats

The recap serves two purposes: it creates a searchable email trail of changes, and it forces a concise summary that catches gaps ("wait, I forgot to update the README").

### When to skip

- Trivial changes (typo fixes, dependency bumps with no behavior change)
- Changes the user made interactively and already knows about in full detail — ask first

---

## 14. Design Decision Logs

Projects with non-trivial architecture should maintain a design decision log. See [Design Decision Log](../patterns/design-decision-log.md) for the full pattern.

### Quick reference

- Use `DESIGN.md` at the repo root (split into multiple files for distinct concern areas).
- Each decision gets a numbered entry with status (SETTLED / OPEN / SUPERSEDED), reasoning, and rejected alternatives.
- **Before proposing any design change**, consult the log for prior decisions on the same topic.
- **Do not revisit** a settled decision without new evidence.
- **Log before implementing** — the decision record must exist before the code change.

---

## 15. Cross-Project Integration

Projects may optionally integrate with other Punt Labs tools. Integrations must be:

- **Optional** — the project works fully without the dependency
- **Graceful** — check for the dependency at runtime, fall back silently if absent
- **One-way** — project A may use project B, but B must not know about A

Current integrations:

- **PR/FAQ uses Quarry** — researcher agent searches indexed documents during `/prfaq:research` and Phase 0 discovery
- **Z Spec should use Quarry** — domain docs could inform spec generation (planned, `claude-z-spec-plugin-p81`)

When adding an integration, document it in the consuming project's README and PROJECTS.md. Do not add references in the upstream project.
