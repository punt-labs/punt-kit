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

## 6. Pre-PR Checklist

Before creating a pull request, verify:

- [ ] Quality gates pass (see section 5)
- [ ] README updated if user-facing behavior changed (new flags, commands, defaults, config)
- [ ] CHANGELOG entry added for notable changes (if the project maintains one)
- [ ] Version bumped if user-facing behavior changed (if the project uses semver)

---

## 7. Code Review Flow

Do **not** merge immediately after creating a PR. The full flow is:

1. **Create PR** — push branch, open PR.
2. **Trigger GitHub Copilot code review** — request review so Copilot analyzes the diff.
3. **Watch for feedback** — background the watch so you stay productive:

   ```bash
   gh pr checks <number> --watch         # Background this — blocks until all checks resolve
   ```

4. **Read feedback** — when the watch completes, read review comments:

   ```bash
   gh pr view <number> --comments        # Copilot feedback and inline comments
   ```

5. **Evaluate feedback** — read each comment; decide which are valid and actionable.
6. **Address valid issues** — commit fixes; push; ensure quality gates pass on each change.
7. **Merge only when** — all review feedback has been evaluated (addressed or explicitly declined), GitHub Actions are green, and local quality gates pass.

Quality gates apply at every step. Each commit that addresses review feedback must pass both local checks and CI.

---

## 8. Session Close Protocol

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

## 9. Design Decision Logs

Projects with non-trivial architecture should maintain a design decision log. See [Design Decision Log](../patterns/design-decision-log.md) for the full pattern.

### Quick reference

- Use `DESIGN.md` at the repo root (split into multiple files for distinct concern areas).
- Each decision gets a numbered entry with status (SETTLED / OPEN / SUPERSEDED), reasoning, and rejected alternatives.
- **Before proposing any design change**, consult the log for prior decisions on the same topic.
- **Do not revisit** a settled decision without new evidence.
- **Log before implementing** — the decision record must exist before the code change.

---

## 10. Cross-Project Integration

Projects may optionally integrate with other Punt Labs tools. Integrations must be:

- **Optional** — the project works fully without the dependency
- **Graceful** — check for the dependency at runtime, fall back silently if absent
- **One-way** — project A may use project B, but B must not know about A

Current integrations:

- **PR/FAQ uses Quarry** — researcher agent searches indexed documents during `/prfaq:research` and Phase 0 discovery
- **Z Spec should use Quarry** — domain docs could inform spec generation (planned, `claude-z-spec-plugin-p81`)

When adding an integration, document it in the consuming project's README and PROJECTS.md. Do not add references in the upstream project.
