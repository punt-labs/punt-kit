# Punt Labs Design Guidance

Standards and best practices for Punt Labs projects. Each standard lives in its own document under `standards/`. This page is the index and the audit checklist.

---

## Standards

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

---

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
