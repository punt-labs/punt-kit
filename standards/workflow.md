# Workflow Standards

How Punt Labs teams track work, integrate projects, and collaborate.

---

## Issue Tracking

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

---

## Cross-Project Integration

Projects may optionally integrate with other Punt Labs tools. Integrations must be:

- **Optional** — the project works fully without the dependency
- **Graceful** — check for the dependency at runtime, fall back silently if absent
- **One-way** — project A may use project B, but B must not know about A

Current integrations:
- **PR/FAQ uses Quarry** — researcher agent searches indexed documents during `/prfaq:research` and Phase 0 discovery
- **Z Spec should use Quarry** — domain docs could inform spec generation (planned, `claude-z-spec-plugin-p81`)

When adding an integration, document it in the consuming project's README and PROJECTS.md. Do not add references in the upstream project.
