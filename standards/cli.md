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

## Naming and Distribution

### PyPI package names

All Punt Labs packages use the `punt-` prefix on PyPI:

| Repo | PyPI package | Install command |
|------|-------------|-----------------|
| `punt-labs/quarry` | `punt-quarry` | `pip install punt-quarry` |
| `punt-labs/biff` | `punt-biff` | `pip install punt-biff` |
| `punt-labs/langlearn-tts` | `punt-langlearn-tts` | `pip install punt-langlearn-tts` |
| `punt-labs/punt-kit` | `punt-kit` | `pip install punt-kit` |

The prefix avoids name collisions on PyPI (which has no namespace/scope mechanism like npm's `@org/pkg`) and makes org affiliation clear.

### CLI entry point names

CLI entry points use the **short name** (no prefix): `quarry`, `biff`, `langlearn-tts`, `punt`. Users type the short name; the package name is only visible during install.

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
| `init` | Set up per-repo configuration (if the tool has repo-scoped state) |
| `doctor` | Check installation health — pass/fail per dependency |
| `version` | Print the version |
| `serve` | Start the MCP server (if the project has one) |

### `install` vs `init`

`install` is **machine-scoped** — run once per machine to register the MCP server, download models, or create global data directories. It makes the tool available system-wide.

`init` is **repo-scoped** — run once per repository to create project-specific configuration. It makes the tool active in a particular codebase.

Not every tool needs `init`. If the tool has no per-repo state (e.g., `punt-kit` is purely global), omit it. If the tool needs per-repo activation (e.g., biff needs a `.biff` team config, quarry needs a collection registration), `init` is required.

### `init` rules

1. **Idempotent.** If config already exists, report it and exit (do not overwrite). Users edit config directly after creation.
2. **Interactive.** Prompt for required values with sensible defaults. Use `typer.prompt()` for each configurable field.
3. **Git-aware.** Auto-detect the repo root. Fail clearly if not inside a git repository.
4. **Creates minimal config.** One config file (e.g., `.biff`, `quarry.toml`) at the repo root. Document its format in the project README.
5. **Updates `.gitignore`** if the config contains user-specific values that should not be committed.

Reference implementation: `biff init` creates a `.biff` file with team members, relay URL, and identity.

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
