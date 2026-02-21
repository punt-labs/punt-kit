# Distribution Standards

How users install and activate Punt Labs tools.

---

## Projection Model

Every project is a library first. The library is **projected** outward as a CLI,
MCP server, plugin, or REST API depending on who calls it and where they run.
Each projection has its own distribution channel:

| Projection | Caller | Channel |
|------------|--------|---------|
| Library | Python code (same process) | PyPI (`uv add punt-<name>`) |
| CLI | Human at terminal | PyPI (`uv tool install punt-<name>`) |
| MCP server | AI agent (same machine) | `<name> install` → `claude mcp add` |
| Plugin shell | AI agent (enhanced UX) | Marketplace (`claude plugin install`) |
| Desktop bundle | Claude Desktop user | `.mcpb` one-click install |
| Native app | End user | App Store, TestFlight, Homebrew |

Not every project needs every projection. Only build the projections that have
callers.

---

## Install Principle

**One command per use case.** A user should be able to install exactly what they
need with a single command. When that's not physically possible (e.g., a CLI
binary must exist before a plugin can reference it), the minimum is two commands
and the second command must handle all remaining setup.

| Use case | Commands | What the user runs |
|----------|----------|-------------------|
| Python library | 1 | `uv add punt-quarry` |
| CLI tool | 1 | `uv tool install punt-quarry` |
| Claude Code MCP server | 2 | `uv tool install punt-quarry && quarry install` |
| Claude Code plugin (pure) | 1 | `claude plugin install dungeon@punt-labs` |
| Claude Code plugin (hybrid) | 2 | `uv tool install punt-biff && biff install` |
| Claude Desktop | 1 | Double-click `.mcpb` bundle |

The `install` subcommand is the seam that hides complexity. It handles
marketplace registration, `claude mcp add`, plugin installation, and dependency
verification. The user never runs `claude plugin install` or `claude mcp add`
directly for Punt Labs tools.

### Marketplace registration

The punt-labs marketplace must be registered before plugin installs work. For
hybrid projects, the `install` subcommand handles this automatically. For users
who only want pure plugins, a one-time setup:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/claude-plugins/main/install.sh | sh
```

Or manually: `claude plugin marketplace add punt-labs/claude-plugins`.

---

## Project Types

### Pure plugins (no CLI binary)

Examples: dungeon, prfaq.

Single artifact distributed via the marketplace. No PyPI package. The plugin
contains commands, hooks, skills, and optionally an MCP server backed by a
bundled Node.js script (not a system binary).

```bash
claude plugin install dungeon@punt-labs
# Restart → SessionStart hook runs first-time setup
# Restart again → top-level commands active
```

### CLI + MCP server projects

Examples: quarry, langlearn-tts.

The library and CLI are the primary artifacts (PyPI). The `install` subcommand
registers the MCP server with Claude Code. No plugin shell — no hooks, no slash
commands, no marketplace involvement.

```bash
uv tool install punt-quarry    # CLI on PATH
quarry install                 # registers MCP server
```

Should also have a **`.mcpb` bundle** for one-click Claude Desktop installation.
Build with `@anthropic-ai/mcpb` via `scripts/build-mcpb.sh`. Attach to GitHub
releases.

### CLI + plugin hybrids

Examples: biff.

Two artifacts: a CLI tool (PyPI) and a plugin shell (marketplace). The plugin's
MCP server declaration references the CLI binary, so the CLI must be installed
first. The `install` subcommand sequences the rest.

```bash
uv tool install punt-biff      # CLI on PATH
biff install                   # registers marketplace + installs plugin
# Restart twice (SessionStart hook, then commands active)
```

Use the plugin shell only when the project needs hooks (output formatting,
session setup) or slash commands. If it's just MCP tools, use the simpler
CLI + MCP server pattern.

### Native apps

Distributed through platform-appropriate channels (App Store, TestFlight,
Homebrew, or source build). Document build steps in the README.

---

## Dependency Pinning for CLI Tools

`uv sync` respects the lockfile. `uv tool install` does **not** — it resolves
dependencies from scratch against pyproject.toml constraints. This means a
constraint like `fastmcp>=2.0.0` will happily install 3.x for end users even if
the lockfile pins 2.x in development.

**Rule**: Pin major versions for libraries with breaking changes in CLI tools
that end users install via `uv tool install`. The lockfile protects dev; the
pyproject.toml constraint protects production.

```toml
# Bad — allows any major version
"fastmcp>=2.0.0"

# Good — locks to compatible major version
"fastmcp>=3.0.0,<4"
```

---

## Installation Scope

MCP servers and tools have different installation scopes. Choosing the wrong
scope leaks credentials, creates confusion, or fails silently.

### Principles

1. **Marketplace plugins install globally (`--scope user`).** Plugin commands,
   hooks, and MCP servers are team infrastructure that should be available in
   every project.

2. **Standalone MCP servers install per-project by default.** Use
   `claude mcp add <name>` (no `--scope` flag) for MCP-only projects. This keeps
   API keys, relay tokens, and server configurations scoped to the project that
   needs them.

3. **Per-project activation via `init`.** Projects with per-repo configuration
   (team rosters, relay URLs, database names, API keys) should have an `init`
   subcommand that creates the repo-level config file. This is distinct from
   `install` (which sets up the tool globally).

| Subcommand | Scope | What it does |
|-----------|-------|-------------|
| `install` | Global (one-time) | Register marketplace, install plugin, verify dependencies |
| `init` | Per-repo | Create the repo-level config file (e.g., `.biff`, `.quarry.toml`), prompt for project-specific settings |

### Per-repo config files

Projects with per-repo state should use a dotfile at the git root:

| Project | Config File | Contents |
|---------|------------|----------|
| Biff | `.biff` | Team roster, relay URL, auth credentials |
| Quarry | `.quarry.toml` (proposed) | Database name, registered directories, collection defaults |
| Beads | `.beads/` | Issue database, config |

The config file should be committed to git (minus secrets). Secrets belong in
environment variables or a `.local` file that is gitignored.

### API keys and secrets

- **Never embed API keys in MCP config files** (`claude_desktop_config.json`,
  `.mcp.json`). Use environment variables.
- **Never commit secrets to git.** Use `.env` files (gitignored) or system
  keychain.
- `doctor` should verify that required secrets are available without printing
  them.

---

## Uninstall Requirements

`claude plugin uninstall` only removes the plugin from the registry and cache.
It does **not** clean up side effects created by install commands or hooks.

Every project with an `install` subcommand must also have `uninstall` that
handles all cleanup:

| Artifact | Created by | Cleaned up by |
|----------|-----------|---------------|
| Plugin registration | `claude plugin install` | `claude plugin uninstall` |
| Deployed commands in `~/.claude/commands/` | SessionStart hook | Project `uninstall` |
| Permission entries in `~/.claude/settings.json` | SessionStart hook | Project `uninstall` |
| Status line wrapping | `install-statusline` | Project `uninstall` |
| Marketplace registration | `install` | `uninstall` (keep if other punt-labs plugins installed) |
| Orphaned local plugin dirs | Previous install method | `uninstall` (migration cleanup) |
