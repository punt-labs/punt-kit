# CLI Standards

Standards for command-line interfaces across all Punt Labs projects. **beads** (`bd`) is the reference implementation.

---

## CLI + Plugin Duality

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

## Structure

- Framework: **typer** + **rich** (Python projects)
- Entry point: single command group (`app = typer.Typer()`)
- Subcommands: imperative verbs (`install`, `search`, `doctor`, `serve`)
- Help text: one-line description on the Typer app; per-command docstrings

---

## Required Subcommands

Every CLI must implement:

| Subcommand | Purpose |
|-----------|---------|
| `install` | Configure the tool for the current environment (MCP registration, data directories, models) |
| `doctor` | Check installation health — pass/fail per dependency |
| `version` | Print the version |
| `serve` | Start the MCP server (if the project has one) |

---

## Doctor Commands

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

## Machine-Readable Output (`--json`)

Every CLI must support a `--json` global flag that switches output to JSON. This enables agentic integration — scripts, CI pipelines, and other tools can parse the output programmatically.

Rules:
- `--json` is a **global flag**, not per-subcommand
- When `--json` is set, all output is valid JSON written to stdout
- Human-readable messages (progress, decoration) go to stderr or are suppressed
- Errors are JSON objects with at minimum `{"error": "<message>"}`
- List commands return JSON arrays; detail commands return JSON objects

Pattern: `bd --json list`, `bd --json show <id>`.

---

## Shell Completion

Every CLI should support shell completion via typer's built-in `--install-completion` and `--show-completion`.
