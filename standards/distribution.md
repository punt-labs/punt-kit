# Distribution Standards

How users install and activate Punt Labs tools.

---

## Install Paths by Project Type

Every project must have a frictionless install path appropriate to its type.

### Plugin projects (Claude Code)

Distributed via the **punt-labs marketplace** (`punt-labs/claude-plugins`).

**Pure plugins** (no CLI binary — e.g., dungeon, prfaq):

```bash
claude plugin marketplace add punt-labs/claude-plugins   # one-time
claude plugin install <name>@punt-labs                   # install
# Restart → SessionStart hook runs first-time setup
# Restart again → top-level commands active
```

**CLI + plugin hybrids** (e.g., biff, quarry):

These projects have two artifacts: a CLI tool (PyPI/git) and a plugin
(marketplace). The CLI must be installed first because the plugin's MCP server
references the CLI binary.

```bash
uv tool install punt-<name>     # Step 1: CLI on PATH
<name> install                  # Step 2: registers marketplace + installs plugin
# Restart twice as above
```

The project's `install` subcommand handles marketplace registration and
`claude plugin install`. The user never runs `claude plugin install` directly.

Pattern: `biff/src/biff/installer.py`, `dungeon/.claude-plugin/plugin.json`.

### MCP server projects (Claude Code + Claude Desktop)

Must be published to **PyPI** via the automated `release.yml` workflow (tag push triggers build → TestPyPI → install-test → PyPI). Installable via `pip install <name>` or `uv tool install <name>`.

Must have an `install` subcommand that configures the MCP server for Claude Code (`claude mcp add ...`).

Should have a **`.mcpb` bundle** for one-click Claude Desktop installation. Build with `@anthropic-ai/mcpb` via a `scripts/build-mcpb.sh` script. The `.mcpb` must be attached to GitHub releases.

Pattern: `quarry`, `langlearn-tts`.

### Native apps

Distributed through platform-appropriate channels (App Store, TestFlight, Homebrew, or source build). Document build steps in the README.

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

MCP servers and tools have different installation scopes. Choosing the wrong scope leaks credentials, creates confusion, or fails silently.

### Principles

1. **Marketplace plugins install globally (`--scope user`).** Plugin commands, hooks, and MCP servers are team infrastructure that should be available in every project.

2. **Standalone MCP servers install per-project by default.** Use `claude mcp add <name>` (no `--scope` flag) for MCP-only projects. This keeps API keys, relay tokens, and server configurations scoped to the project that needs them.

3. **Per-project activation via `init`.** Projects with per-repo configuration (team rosters, relay URLs, database names, API keys) should have an `init` subcommand that creates the repo-level config file. This is distinct from `install` (which sets up the tool globally).

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

The config file should be committed to git (minus secrets). Secrets belong in environment variables or a `.local` file that is gitignored.

### API keys and secrets

- **Never embed API keys in MCP config files** (`claude_desktop_config.json`, `.mcp.json`). Use environment variables.
- **Never commit secrets to git.** Use `.env` files (gitignored) or system keychain.
- `doctor` should verify that required secrets are available without printing them.

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
