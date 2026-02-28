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
| MCP server | AI agent (same machine) | `claude mcp add` (standalone) or plugin `mcpServers` (hybrid) |
| Plugin shell | AI agent (enhanced UX) | Marketplace (`claude plugin install`) |
| Desktop bundle | Claude Desktop user | `.mcpb` one-click install |
| Native app | End user | App Store, TestFlight, Homebrew |

Not every project needs every projection. Only build the projections that have
callers.

---

## Install Principle

**One command per use case.** A user should be able to install exactly what they
need with a single command. Every Python project that requires multiple steps
(install binary, register MCP server, configure plugin) must ship an
`install.sh` that collapses them into a single `curl | sh`:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/<repo>/<SHA>/install.sh | sh
```

The URL is **pinned to a commit SHA**, not `main`. This ensures the script
content is immutable — even if the repo is compromised later, the pinned URL
returns the original trusted version. READMEs and the org profile advertise the
pinned URL; users who want the latest can substitute `main` at their own risk.

The `install.sh` is the user-facing entry point. The CLI `install` subcommand
is still useful — it's what the script calls, and it's what users run if they
already have the binary on PATH.

| Use case | What the user runs |
|----------|--------------------|
| CLI + MCP server | `curl -fsSL .../quarry/<SHA>/install.sh \| sh` |
| CLI + plugin (hybrid) | `curl -fsSL .../biff/<SHA>/install.sh \| sh` |
| Pure plugin | `claude plugin install dungeon@punt-labs` |
| Python library | `uv add punt-quarry` |
| Claude Desktop | Double-click `.mcpb` bundle |

### Trust tiers

Every project README must present three install tiers so users choose their
own trust level:

| Tier | What the user does | Trust model |
|------|--------------------|-------------|
| **Convenience** | `curl -fsSL .../<SHA>/install.sh \| sh` | Trusts the pinned SHA + HTTPS + GitHub |
| **Inspect** | Download, `cat install.sh`, then `sh install.sh` | Reads the script before executing |
| **Verify** | Download, `shasum -a 256`, compare hash, then run | Cryptographic verification against published hash |

The README should use the convenience tier as the primary code block, with
the other two tiers in expandable `<details>` sections:

```markdown
## Quick Start

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/<repo>/<SHA>/install.sh | sh
\`\`\`

<details>
<summary>Manual install (if you already have uv)</summary>

\`\`\`bash
uv tool install punt-<name>
<name> install
<name> doctor
\`\`\`

</details>

<details>
<summary>Verify before running</summary>

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/<repo>/<SHA>/install.sh -o install.sh
shasum -a 256 install.sh
cat install.sh
sh install.sh
\`\`\`

</details>
```

### install.sh requirements

Every `install.sh` must follow the [shell standards](shell.md) for install
scripts:

- **POSIX sh** (`#!/bin/sh`) — not bash. Shellcheck with `--shell=sh`.
- **Pre-flight checks** — verify Python 3.13+, install uv if missing, verify
  `claude` CLI for projects that need it.
- **Idempotent** — safe to re-run. Upgrades if already installed.
- **Transparent** — print each step before executing it.
- **SSH fallback** — `claude plugin install` clones via SSH. Detect missing
  SSH keys and temporarily rewrite git URLs to HTTPS. Clean up the rewrite
  after both success and failure paths.
- **Marketplace refresh** — run `claude plugin marketplace update` before
  `claude plugin install` so existing users pick up `source.ref` pins (DES-003).
- **Ends with `doctor`** — run the project's health check to verify the install.

Pattern: `biff/install.sh`, `quarry/install.sh`.

### Updating the pinned SHA

When `install.sh` changes, update the SHA in all places that reference it:

1. Commit the `install.sh` change and push
2. Copy the commit SHA: `git log -1 --format='%H' -- install.sh`
3. Update the project README, the org profile README, and the marketplace README
   (if applicable) with the new SHA
4. Commit the README updates separately

### Marketplace registration

The punt-labs marketplace must be registered before plugin installs work. For
hybrid projects, the `install` subcommand handles this automatically. For users
who only want pure plugins, a one-time setup:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/claude-plugins/<SHA>/install.sh | sh
```

Or manually: `claude plugin marketplace add punt-labs/claude-plugins`.

Every marketplace entry must have `source.ref` pinned to the release tag. Without
it, `claude plugin install` clones HEAD of the default branch, which may include
dev artifacts. See DES-003 in DESIGN.md for the full root cause analysis. The
release workflow must update both `version` and `source.ref` in the marketplace
entry.

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

Examples: langlearn-tts.

The library and CLI are the primary artifacts (PyPI). The `install` subcommand
registers the MCP server with Claude Code. No plugin shell — no hooks, no slash
commands, no marketplace involvement.

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/langlearn-tts/<SHA>/install.sh | sh
```

The script installs the CLI via uv, runs `<tool> install` (registers MCP
server), and runs `<tool> doctor`. Should also have a **`.mcpb` bundle** for
one-click Claude Desktop installation. Build with `@anthropic-ai/mcpb` via
`scripts/build-mcpb.sh`. Attach to GitHub releases.

### CLI + plugin hybrids

Examples: biff, quarry, tts, punt-kit.

Two artifacts: a CLI tool (PyPI) and a plugin shell (marketplace). The plugin's
MCP server declaration references the CLI binary, so the CLI must be installed
first. The `install.sh` sequences everything:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/biff/<SHA>/install.sh | sh
# Restart Claude Code twice (SessionStart hook, then commands active)
```

The `install.sh` is the user-facing entry point. It chains: uv install →
marketplace register → marketplace refresh → plugin install → doctor.

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
| MCP tool permissions in `~/.claude/settings.json` | SessionStart hook | Project `uninstall` |
| Non-MCP permissions in `~/.claude/settings.json` | Installer (permission step) | Project `uninstall` |
| Status line wrapping | `install-statusline` | Project `uninstall` |
| Marketplace registration | `install` | `uninstall` (keep if other punt-labs plugins installed) |
| Orphaned local plugin dirs | Previous install method | `uninstall` (migration cleanup) |
