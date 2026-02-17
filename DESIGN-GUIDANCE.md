# Punt Labs Design Guidance

Standards and best practices for Claude-related projects. Use this document to audit existing projects and guide new ones.

---

## 1. Distribution

Every project must have a frictionless install path appropriate to its type.

### Plugin projects (Claude Code)

Must have a `curl | bash` installer (`install.sh`) that:
- Clones the repo to `~/.claude/plugins/local-plugins/plugins/<name>`
- Checks out the latest semver tag
- Registers the plugin in `marketplace.json`
- Checks for runtime dependencies (or prompts to install them)
- Clears the plugin cache
- Prints a success message with the entry-point command

Pattern: `prfaq/install.sh`, `claude-dungeon/install.sh`.

### MCP server projects (Claude Code + Claude Desktop)

Must be published to **PyPI** and installable via `pip install <name>` or `uv tool install <name>`.

Must have an `install` subcommand that configures the MCP server for Claude Code (`claude mcp add ...`).

Should have a **`.mcpb` bundle** for one-click Claude Desktop installation. Build with `@anthropic-ai/mcpb` via a `scripts/build-mcpb.sh` script. The `.mcpb` must be attached to GitHub releases.

Should have a `curl | bash` installer for the CLI path.

Pattern: `quarry-mcp`, `langlearn-tts`.

### Native apps

Distributed through platform-appropriate channels (App Store, TestFlight, Homebrew, or source build). Document build steps in the README.

---

## 2. CLI + Plugin Duality

Most tools should work two ways: as a standalone CLI and as a plugin or MCP server inside Claude. The CLI is for scripted and non-AI workflows. The plugin/MCP layer is for AI-assisted workflows. Users should not need Claude to perform deterministic operations.

**Deterministic operations belong in the CLI:**
- Compilation, formatting, linting
- Health checks and diagnostics
- Scaffolding and initialization
- Dependency verification

**AI-driven operations belong in the plugin:**
- Generation, analysis, review
- Natural language interaction
- Multi-step orchestration
- Agentic workflows

Projects that are inherently AI-driven (e.g., Dungeon, where Claude *is* the game engine) are exempt from CLI duality.

---

## 3. Doctor Commands

Every project with external dependencies must have a `doctor` command that reports pass/fail per dependency.

**CLI projects:** `<tool> doctor` (e.g., `biff doctor`, `quarry doctor`)

**Plugin-only projects:** `/<tool> doctor` slash command or equivalent (e.g., `/z doctor`)

The doctor command must check:
- Required binaries found and executable
- Required libraries/packages installed
- Correct versions where applicable
- Plugin registration (for Claude Code plugins)
- MCP server configuration (for MCP projects)
- Network connectivity (for projects with relay/API dependencies)

The installer should run `doctor` as its final step.

Pattern: `biff doctor`, `quarry doctor`, `langlearn-tts doctor`.

---

## 4. Plugin Structure

### plugin.json

Every Claude Code plugin must have a `plugin.json` with at minimum:

```json
{
  "name": "<project-name>",
  "description": "<one-line description>",
  "version": "<semver>",
  "author": {
    "name": "<author>",
    "email": "<email>",
    "organization": "Punt Labs"
  }
}
```

The `version` field is required. Omitting it is a defect.

### Extension point selection

Choose the right extension point for each capability:

| Extension Point | When to Use |
|----------------|-------------|
| **Skill** | Complex multi-phase workflows with branching logic. The skill defines *how Claude should behave* for the duration of a task. Use sparingly — most projects need zero or one. |
| **Command** | A discrete, user-invocable operation mapped to a slash command. One command per slash command. Self-contained. |
| **Agent** | A specialized sub-task that a skill or command delegates to. Has a distinct role, model preference, and tool restrictions. Use when the sub-task benefits from isolation or a different model. |
| **Hook** | Event-driven automation triggered by tool calls or lifecycle events. Use for output suppression, validation, or side effects. |
| **MCP Server** | Exposes tools that Claude (or any MCP client) can call. Use when the project has deterministic operations (I/O, computation, state management) that should not be prompt-driven. |

### Output suppression

Any project that uses MCP tools inside Claude Code must have a **PostToolUse hook** that suppresses raw MCP tool output. Without this, JSON payloads from tool calls pollute the conversation.

Pattern: `biff/hooks/suppress-output.sh`, `claude-dungeon/hooks/hooks.json`.

The hook should match the project's MCP tool name pattern (e.g., `mcp__biff__*`, `mcp__plugin_dungeon_game__*`).

### Command tool restrictions

Commands that invoke external tools (compilers, linters, test runners) should declare `allowed-tools` in their frontmatter to restrict what Claude can execute. This prevents unintended side effects.

Pattern: Z Spec commands restrict Bash to `fuzz:*` and `probcli:*` calls only.

---

## 5. Cross-Project Integration

Projects may optionally integrate with other Punt Labs tools. Integrations must be:

- **Optional** — the project works fully without the dependency
- **Graceful** — check for the dependency at runtime, fall back silently if absent
- **One-way** — project A may use project B, but B must not know about A

Current integrations:
- **PR/FAQ uses Quarry** — researcher agent searches indexed documents during `/prfaq:research` and Phase 0 discovery
- **Z Spec should use Quarry** — domain docs could inform spec generation (planned, `claude-z-spec-plugin-p81`)

When adding an integration, document it in the consuming project's README and PROJECTS.md. Do not add references in the upstream project.

---

## 6. Issue Tracking

All projects use **beads** (`bd`) for issue tracking.

### Setup

Every repo must have beads initialized (`bd init`). The `.beads/` directory is committed to git.

### Workflow

- `bd create "title"` to create issues with `--type` (task, bug, feature, spike) and `--priority` (1-5)
- `bd ready` to find available work
- `bd update <id> --status in_progress` before starting
- `bd close <id>` when complete
- Work is not complete until `git push` succeeds

### Issue quality

Issues must have:
- A clear title in imperative form
- A description with enough context for another engineer (or agent) to act on
- Correct type and priority
- Dependencies declared (`--blocks`, `--blocked-by`) when applicable

---

## 7. Code Standards

Language-specific standards live in dedicated documents under `standards/`. These are the canonical references — individual project CLAUDE.md files should reference them, not duplicate them.

| Language | Standards Document | Projects |
|----------|-------------------|----------|
| Python | [`standards/python.md`](standards/python.md) | Biff, Quarry, LangLearn TTS |
| Node.js | [`standards/node.md`](standards/node.md) | Dungeon MCP server |
| Swift | (planned) | Quarry Menu Bar, Koch Trainer |
| Markdown-only | N/A — see Plugin Structure (§4) | PR/FAQ, Z Spec |

### Quick reference (Python)

uv, ruff, mypy, pyright, pytest, typer + rich, FastMCP. Published to PyPI. Quality gates pass before every commit. See [`standards/python.md`](standards/python.md) for full details.

### Quick reference (Node.js)

Node 20+, npm, `@modelcontextprotocol/sdk`, zod. ES modules (`.mjs`). See [`standards/node.md`](standards/node.md) for full details.

### Quick reference (Swift)

swiftformat, swiftlint, XcodeGen (from `project.yml`), SwiftUI with `@Observable`, XCTest.

### Markdown-only projects (PR/FAQ, Z Spec)

- No application code — all logic lives in prompts
- Skills, agents, commands, and reference guides are markdown files
- Shell scripts (`install.sh`, `compile_prfaq.sh`) handle deterministic operations

---

## 8. Versioning

Projects follow **semver** (`major.minor.patch`).

- Plugin projects: version in `plugin.json`
- PyPI projects: version in `pyproject.toml` (and `manifest.json` for `.mcpb` builds — must match)
- Swift projects: version in `project.yml`
- Installers: check out the latest semver git tag

---

## 9. Naming Conventions

### General rule

The project name is the CLI command name. That same name is used for the GitHub repo, the PyPI package, and the local directory. Do **not** add a `-mcp` suffix — it implies the project is only an MCP server when most of our tools are dual CLI+MCP.

| Component | Convention | Examples |
|-----------|-----------|---------|
| GitHub repo | `<org>/<name>` | `punt-labs/biff`, `punt-labs/quarry` |
| PyPI package | `<name>` (matches CLI) | `biff`, `quarry`, `langlearn-tts` |
| MCP server only (no CLI) | `<name>-mcp` | — (no current examples; avoid this pattern) |

### Other components

| Component | Convention | Examples |
|-----------|-----------|---------|
| CLI command | Short, lowercase, no prefix | `biff`, `quarry`, `langlearn-tts` |
| Slash command | `/<name>` or `/<name>:<subcommand>` | `/prfaq`, `/prfaq:review`, `/z check` |
| Plugin directory | Match the plugin name | `plugins/prfaq/`, `plugins/z-spec/` |
| Bead ID prefix | Auto-detected from directory name | `biff-*`, `prfaq-*`, `quarry-*` |

---

## 10. CLI Standards

Every Python project with a CLI must follow these conventions. **beads** (`bd`) is the reference implementation.

### Structure

- Framework: **typer** + **rich**
- Entry point: single command group (`app = typer.Typer()`)
- Subcommands: imperative verbs (`install`, `search`, `doctor`, `serve`)
- Help text: one-line description on the Typer app; per-command docstrings

### Required subcommands

Every CLI must implement:

| Subcommand | Purpose |
|-----------|---------|
| `install` | Configure the tool for the current environment (MCP registration, data directories, models) |
| `doctor` | Check installation health — pass/fail per dependency |
| `version` | Print the version |
| `serve` | Start the MCP server (if the project has one) |

### Machine-readable output (`--json`)

Every CLI must support a `--json` global flag that switches output to JSON. This enables agentic integration — scripts, CI pipelines, and other tools can parse the output programmatically.

Rules:
- `--json` is a **global flag**, not per-subcommand
- When `--json` is set, all output is valid JSON written to stdout
- Human-readable messages (progress, decoration) go to stderr or are suppressed
- Errors are JSON objects with at minimum `{"error": "<message>"}`
- List commands return JSON arrays; detail commands return JSON objects

Pattern: `bd --json list`, `bd --json show <id>`.

### Shell completion

Every CLI should support shell completion via typer's built-in `--install-completion` and `--show-completion`.

---

## 11. Installation Scope

MCP servers and tools have different installation scopes. Choosing the wrong scope leaks credentials, creates confusion, or fails silently.

### Principles

1. **MCP servers install per-project by default.** Use `claude mcp add <name>` (no `--scope` flag) which defaults to local/project scope. This keeps API keys, relay tokens, and server configurations scoped to the project that needs them.

2. **Global installation is opt-in.** Use `claude mcp add --scope user <name>` only when the tool is genuinely global (e.g., a utility with no per-project configuration). The user must explicitly choose global scope.

3. **Per-project activation via `init`.** Projects with per-repo configuration (team rosters, relay URLs, database names, API keys) should have an `init` subcommand that creates the repo-level config file. This is distinct from `install` (which sets up the tool globally).

| Subcommand | Scope | What it does |
|-----------|-------|-------------|
| `install` | Global (one-time) | Download models, register MCP server, install plugin, verify dependencies |
| `init` | Per-repo | Create the repo-level config file (e.g., `.biff`, `.quarry.toml`), prompt for project-specific settings |

### Per-repo config files

Projects with per-repo state should use a dotfile at the git root:

| Project | Config File | Contents |
|---------|------------|----------|
| Biff | `.biff` | Team roster, relay URL, auth credentials |
| Quarry | `.quarry.toml` (proposed) | Database name, registered directories, collection defaults |
| Beads | `.beads/` | Issue database, config |

The config file should be committed to git (minus secrets). Secrets belong in environment variables or a `.local` file that is gitignored.

### API keys and secrets

- **Never embed API keys in MCP config files** (`claude_desktop_config.json`, `.mcp.json`). Use environment variables.
- **Never commit secrets to git.** Use `.env` files (gitignored) or system keychain.
- `doctor` should verify that required secrets are available without printing them.

---

## 12. Audit Checklist

Use this checklist to audit a project for compliance:

- [ ] **Install path exists** — `curl | bash`, PyPI, `.mcpb`, or documented build steps
- [ ] **Doctor command exists** — if the project has external dependencies
- [ ] **CLI available** — for deterministic operations (exempt: purely AI-driven projects)
- [ ] **CLI supports `--json`** — global flag for machine-readable output
- [ ] **PyPI name matches CLI name** — no `-mcp` suffix on dual CLI+MCP tools
- [ ] **MCP scope is per-project** — `claude mcp add` without `--scope user` unless justified
- [ ] **`init` command exists** — if the project has per-repo configuration
- [ ] **plugin.json has version** — if the project is a Claude Code plugin
- [ ] **PostToolUse hook exists** — if the project uses MCP tools in Claude Code
- [ ] **Beads initialized** — `.beads/` directory exists and is committed
- [ ] **README documents installation** — clear, copy-pasteable install instructions
- [ ] **Linting and type checking configured** — per language standards above
- [ ] **Tests exist and pass** — `pytest`, `XCTest`, or equivalent
- [ ] **Cross-project integrations are optional and one-way** — no circular dependencies
