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

## 3. Branch Discipline

All code changes go on feature branches. Never commit directly to main.

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

---

## 4. Commits

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

## 5. Quality Gates

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

## 6. CHANGELOG Discipline

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

## 7. Pre-PR Checklist

Before creating a pull request, verify:

- [ ] Quality gates pass (see section 5)
- [ ] **CHANGELOG entry included in the PR diff** under `## [Unreleased]` for notable changes (see section 6)
- [ ] **README updated** if user-facing behavior changed (new flags, commands, defaults, config)
- [ ] **prfaq.tex updated** if the change shifts product direction or validates/invalidates a risk
- [ ] Version bumped if user-facing behavior changed (if the project uses semver)

---

## 8. Code Review Flow

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

5. **Take every comment seriously** — read each comment and address it. Do not dismiss feedback as "unrelated to the change" or "pre-existing." If a reviewer flags it, it matters. If you genuinely disagree, explain why in a reply — do not silently ignore.
6. **Fix and re-push** — commit fixes, push, and re-run quality gates. Each fix commit triggers a new review cycle.
7. **Repeat steps 3–6** until the latest review cycle is **uneventful** — no new comments, no requested changes, all checks green.
8. **Merge only when the last review was clean** — use `mcp__github__merge_pull_request` (not `gh pr merge`, which has local side effects). A PR is ready to merge when:
   - The most recent Copilot/Bugbot review raised **zero new issues**
   - All GitHub Actions are green
   - Local quality gates pass

Quality gates apply at every step. Each commit that addresses review feedback must pass both local checks and CI. A typical PR takes 2–6 cycles. Do not rush to merge after the first review.

---

## 9. Session Close Protocol

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

## 10. Design Decision Logs

Projects with non-trivial architecture should maintain a design decision log. See [Design Decision Log](../patterns/design-decision-log.md) for the full pattern.

### Quick reference

- Use `DESIGN.md` at the repo root (split into multiple files for distinct concern areas).
- Each decision gets a numbered entry with status (SETTLED / OPEN / SUPERSEDED), reasoning, and rejected alternatives.
- **Before proposing any design change**, consult the log for prior decisions on the same topic.
- **Do not revisit** a settled decision without new evidence.
- **Log before implementing** — the decision record must exist before the code change.

---

## 11. Cross-Project Integration

Projects may optionally integrate with other Punt Labs tools. Integrations must be:

- **Optional** — the project works fully without the dependency
- **Graceful** — check for the dependency at runtime, fall back silently if absent
- **One-way** — project A may use project B, but B must not know about A

Current integrations:

- **PR/FAQ uses Quarry** — researcher agent searches indexed documents during `/prfaq:research` and Phase 0 discovery
- **Z Spec should use Quarry** — domain docs could inform spec generation (planned, `claude-z-spec-plugin-p81`)

When adding an integration, document it in the consuming project's README and PROJECTS.md. Do not add references in the upstream project.
