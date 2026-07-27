# Agent Instructions

This is **punt-kit** — the standards, design patterns, and scaffolding repo for Punt Labs. When working in any Punt Labs project, consult these standards and patterns.

## Beads

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Standards

Each standard lives in its own document under `standards/`.

| Standard | What it covers |
|----------|---------------|
| [Distribution](standards/distribution.md) | Install paths (marketplace, PyPI, .mcpb), dependency pinning, installation scope, init vs install, uninstall requirements |
| [CLI](standards/cli.md) | CLI + plugin duality, required subcommands (install, doctor, version, serve), --json flag, shell completion |
| [Tool Enable/Disable](standards/tool-enable-disable.md) | User-owned CLAUDE.md, the bare `@`-import line, the zoned `.punt-labs/<tool>/` subtree (vendored zone tool-owned), the `enabled` marker, enable/disable verbs, audit checks, sentinel migration |
| [Plugins](standards/plugins.md) | plugin.json, MCP server declaration, extension points, required hooks (SessionStart + PostToolUse), tool naming, gitignore checklist |
| [Hooks](standards/hooks.md) | Claude Code state machine, three-layer dispatch, shell gates, Python handlers, decision-block and workflow-gate patterns, startup performance, audit checklist |
| [Permissions](standards/permissions.md) | Allow/prompt/deny tiers, settings.json vs settings.local.json, required allow and deny rules, plugin-distributed permissions |
| [Filesystem](standards/filesystem.md) | `~/.punt-labs/<tool>/` home layout, reserved subdirectories, per-project activation marker, migration from legacy dot-directories |
| [Repo-Local State Directory](standards/punt-labs-dir.md) | `<repo>/.punt-labs/<tool>/` tool roots plus the machine-local `.punt-labs/local/` zone, committed except local-convention paths (`local/`, `*.local`, `*.local.*`), live state never tracked (the seal pattern, chunk-based), the canonical gitignore block, subtree zones (vendored/config/local/marker) |
| [Integration](standards/integration.md) | Peer-tool discovery tiers L0–L5, presence markers, graceful degradation, integration matrix, bundled integrations |
| [Logging](standards/logging.md) | Centralized dictConfig, log locations, atomic append, file permissions, content escaping |
| [Naming](standards/naming.md) | Repo names, PyPI names, CLI names, slash commands, versioning (semver) |
| [GitHub](standards/github.md) | Branch protection, CI/CD workflows, Copilot code review, required status checks, repo settings |
| [Workflow](standards/workflow.md) | Issue tracking, workflow tiers, branch discipline, commits, quality gates, code review, session close protocol, design decision logs, cross-project integration |
| [PR and Review](standards/pr-review.md) | Local-first review: the PR as merge gate, review agents, remote reviewers as second opinion |
| [Release Process](standards/release-process.md) | The `/punt:auto release` playbook, deterministic phases 1–11, cross-repo propagation |
| [Release Requirements](standards/release-requirements.md) | End-state artifacts a release must satisfy in the originating repo and siblings |
| [README](standards/readme.md) | Required README structure, install trust tiers, tone and positioning |
| [Makefile](standards/makefile.md) | Required Makefile targets; `make check` as the quality-gate entry point |
| [Shell](standards/shell.md) | POSIX sh vs bash, strict mode, shellcheck, install-script rules |
| [Agent Engineering](standards/agent-engineering.md) | Operating defaults for AI coding agents: judgment, scope, verification |
| [Architecture](standards/architecture.md) | The engine-and-clients model: one engine, thin library/CLI/MCP/REST client surfaces |
| [OO](standards/oo.md) | The object-oriented stance shared by Python, Swift, and Pharo |
| [Python](standards/python.md) | uv, ruff, mypy, pyright, pytest, typer + rich, FastMCP, the OO ratchet, release workflow |
| [Go](standards/go.md) | Idiomatic Go: modules, small interfaces, explicit errors, go vet + staticcheck |
| [C](standards/c.md) | Idiomatic C: memory ownership, `-Werror`, sanitizers |
| [Swift](standards/swift.md) | Idiomatic + protocol-oriented Swift; swiftformat, swiftlint, XcodeGen, XCTest |
| [Pharo](standards/pharo.md) | Pharo/Smalltalk, image-based development, in-image linting |

### Introduced dates

Every standard records when it was introduced, so a consumer repo can tell at
a glance whether a rule predates its last sync.

- **Field names.** `**Introduced:**` for the origin date; `**Updated:**` for
  the most recent normative amendment.
- **Placement.** A single bold line immediately under the H1 title, before the
  intro prose. Not YAML frontmatter — these are prose docs, and an inline bold
  line matches the DESIGN.md ADR style (`**Date:** …`) and needs no parser.
- **Format.** ISO 8601 `YYYY-MM-DD`. One line, mid-dot separator when both
  fields are present:

  ```markdown
  # CLI Standards

  **Introduced:** 2026-07-19 · **Updated:** 2026-08-01

  Standards for command-line interfaces…
  ```

  A doc never amended carries only `**Introduced:** YYYY-MM-DD`.
- **Forward-only — no backfill.** The field starts on docs created, or
  normatively amended, after this convention landed (2026-07-19). Existing
  standards are not given retroactive dates — no git archaeology, no uniform
  stamp. A doc that predates the convention gains `**Updated:** YYYY-MM-DD`
  **alone** — the third shape — on its first normative amendment: no
  backfilled `**Introduced:**`, because a truthful origin date takes
  archaeology and a fabricated one falsely advertises an old doc as new.
  Until a doc is amended it has no date line at all, and that is correct.
- **`**Updated:**` bumps on normative change only** — not for typo or
  formatting fixes. The field is an at-a-glance signal, not a changelog; git
  history is the full record.
- **Enforcement is format-only, not presence.** Because the rule is
  forward-only, validation must not require every doc to carry the field. It
  checks only that a doc which does carry an `**Introduced:**` line has it
  well-formed. The `**Updated:**`-only shape needs no rule of its own — the
  grep anchors on `**Introduced:**` lines and never inspects it:

  ```bash
  # Fails only a doc whose Introduced line exists but is malformed. Accepts both
  # "**Introduced:** YYYY-MM-DD" and the combined
  # "**Introduced:** YYYY-MM-DD · **Updated:** YYYY-MM-DD"; anchored to end of line.
  grep -HE '^\*\*Introduced:\*\*' standards/*.md \
    | grep -vE ':\*\*Introduced:\*\* [0-9]{4}-[0-9]{2}-[0-9]{2}( · \*\*Updated:\*\* [0-9]{4}-[0-9]{2}-[0-9]{2})?$'
  ```

## Patterns

Reusable design patterns for Claude Code plugin and MCP server development, extracted from production experience. Each pattern follows the Problem/Forces/Solution/Consequences structure.

| Pattern | What it solves |
|---------|---------------|
| [Two-Channel Display](patterns/two-channel-display.md) | MCP output truncated in Claude Code — split into panel summary + model-emitted full output |
| [Prior-Context Priming](patterns/prior-context-priming.md) | Formatting guidance ignored on same-turn delivery — use MCP `instructions` field |
| [Dynamic Description Notify](patterns/dynamic-description-notify.md) | No push notifications in MCP — mutate tool descriptions + `tools/list_changed` |
| [Stash and Wrap](patterns/stash-and-wrap.md) | Status line is a single command — stash original, wrap at runtime |
| [Two-Phase Install](patterns/two-phase-install.md) | `pip install` can't run `claude mcp add` — separate package install from tool registration |
| [Copy, Not Symlink](patterns/copy-not-symlink.md) | Plugin files break on package upgrade — copy via `importlib.resources`, not symlink |
| [Dual Command Path](patterns/dual-command-path.md) | Plugin commands are namespaced — deploy to both plugin and user command directories |
| [Sibling PPID](patterns/sibling-ppid.md) | MCP server and status line need shared identity — both are children of Claude Code |
| [Doctor Checks](patterns/doctor-checks.md) | Post-install verification — required vs informational health checks |
| [Design Decision Log](patterns/design-decision-log.md) | Decisions lost across sessions — structured log prevents re-debating settled issues |

## Audit Checklist

Use this checklist to audit a project for compliance:

- [ ] **Install path exists** — marketplace, PyPI, `.mcpb`, or documented build steps ([distribution](standards/distribution.md))
- [ ] **Doctor command exists** — if the project has external dependencies ([cli](standards/cli.md))
- [ ] **CLI available** — for deterministic operations; exempt: purely AI-driven projects ([cli](standards/cli.md))
- [ ] **CLI supports `--json`** — global flag for machine-readable output ([cli](standards/cli.md))
- [ ] **PyPI name matches CLI name** — no `-mcp` suffix on dual CLI+MCP tools ([naming](standards/naming.md))
- [ ] **MCP scope is correct** — plugins use `--scope user`; standalone MCP servers default to per-project ([distribution](standards/distribution.md))
- [ ] **`init` command exists** — if the project has per-repo configuration ([distribution](standards/distribution.md))
- [ ] **plugin.json has version** — if the project is a Claude Code plugin ([plugins](standards/plugins.md))
- [ ] **Required hooks exist** — SessionStart + PostToolUse for marketplace plugins with MCP tools ([plugins](standards/plugins.md))
- [ ] **`.mcp.json` is gitignored** — if the project is a Claude Code plugin ([plugins](standards/plugins.md))
- [ ] **Beads initialized** — `.beads/` directory exists and is committed ([workflow](standards/workflow.md))
- [ ] **Quality gates defined** — project CLAUDE.md lists the quality gate commands for this project type ([workflow](standards/workflow.md))
- [ ] **Design decision log exists** — `DESIGN.md` if the project has non-trivial architecture decisions ([workflow](standards/workflow.md))
- [ ] **README documents installation** — clear, copy-pasteable install instructions
- [ ] **Linting and type checking configured** — per language standards ([python](standards/python.md), [go](standards/go.md), [c](standards/c.md), [swift](standards/swift.md))
- [ ] **Tests exist and pass** — `pytest`, `XCTest`, or equivalent
- [ ] **Branch protection on main** — require PR with 1 approval, require status checks, prevent force push ([github](standards/github.md))
- [ ] **CI workflow exists** — lint, test, or docs validation per project type ([github](standards/github.md))
- [ ] **Required status checks configured** — CI must pass before merge ([github](standards/github.md))
- [ ] **Copilot code review enabled** — automatic review on PRs ([github](standards/github.md))
- [ ] **Dependabot and secret scanning enabled** — security baseline ([github](standards/github.md))
- [ ] **Auto-delete head branches enabled** — clean up after merge ([github](standards/github.md))
- [ ] **Cross-project integrations are optional and one-way** — no circular dependencies ([workflow](standards/workflow.md))

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** — Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) — Tests, linters, builds
3. **Update issue status** — Close finished work, update in-progress items
4. **PUSH TO REMOTE**:

   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```

5. **Verify** — All changes committed AND pushed

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — that leaves work stranded locally
- NEVER say "ready to push when you are" — YOU must push
- If push fails, resolve and retry until it succeeds
