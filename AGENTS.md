# Agent Instructions

This is **punt-kit** — the standards and scaffolding repo for Punt Labs. When working in any Punt Labs project, consult these standards.

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
| [Distribution](standards/distribution.md) | Install paths (curl\|bash, PyPI, .mcpb), installation scope (per-project vs global), init vs install, API keys and secrets |
| [CLI](standards/cli.md) | CLI + plugin duality, required subcommands (install, doctor, version, serve), --json flag, shell completion |
| [Plugins](standards/plugins.md) | plugin.json, extension point selection (skills, commands, agents, hooks, MCP), output suppression, tool restrictions |
| [Naming](standards/naming.md) | Repo names, PyPI names, CLI names, slash commands, versioning (semver) |
| [Workflow](standards/workflow.md) | Beads issue tracking, cross-project integration rules |
| [Python](standards/python.md) | uv, ruff, mypy, pyright, pytest, typer + rich, FastMCP, release workflow |
| [Node.js](standards/node.md) | Node 20+, npm, @modelcontextprotocol/sdk, zod, ES modules |
| Swift | (planned) — swiftformat, swiftlint, XcodeGen, SwiftUI, XCTest |

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

- [ ] **Install path exists** — `curl | bash`, PyPI, `.mcpb`, or documented build steps ([distribution](standards/distribution.md))
- [ ] **Doctor command exists** — if the project has external dependencies ([cli](standards/cli.md))
- [ ] **CLI available** — for deterministic operations; exempt: purely AI-driven projects ([cli](standards/cli.md))
- [ ] **CLI supports `--json`** — global flag for machine-readable output ([cli](standards/cli.md))
- [ ] **PyPI name matches CLI name** — no `-mcp` suffix on dual CLI+MCP tools ([naming](standards/naming.md))
- [ ] **MCP scope is per-project** — `claude mcp add` without `--scope user` unless justified ([distribution](standards/distribution.md))
- [ ] **`init` command exists** — if the project has per-repo configuration ([distribution](standards/distribution.md))
- [ ] **plugin.json has version** — if the project is a Claude Code plugin ([plugins](standards/plugins.md))
- [ ] **PostToolUse hook exists** — if the project uses MCP tools in Claude Code ([plugins](standards/plugins.md))
- [ ] **Beads initialized** — `.beads/` directory exists and is committed ([workflow](standards/workflow.md))
- [ ] **README documents installation** — clear, copy-pasteable install instructions
- [ ] **Linting and type checking configured** — per language standards ([python](standards/python.md), [node](standards/node.md))
- [ ] **Tests exist and pass** — `pytest`, `XCTest`, or equivalent
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
