# Distribution Standards

How users install and activate Punt Labs tools.

---

## Install Paths by Project Type

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

Must be published to **PyPI** via the automated `release.yml` workflow (tag push triggers build → TestPyPI → install-test → PyPI). Installable via `pip install <name>` or `uv tool install <name>`.

Must have an `install` subcommand that configures the MCP server for Claude Code (`claude mcp add ...`).

Should have a **`.mcpb` bundle** for one-click Claude Desktop installation. Build with `@anthropic-ai/mcpb` via a `scripts/build-mcpb.sh` script. The `.mcpb` must be attached to GitHub releases.

Should have a `curl | bash` installer for the CLI path.

Pattern: `quarry`, `langlearn-tts`.

### Native apps

Distributed through platform-appropriate channels (App Store, TestFlight, Homebrew, or source build). Document build steps in the README.

---

## Installation Scope

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
