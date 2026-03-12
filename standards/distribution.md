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
| REST API | Native apps, external clients | `<tool> serve` (HTTP) |
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
uv tool install punt-<name>        # or 'punt-<name>[display]' if project has heavy extras
<name> install
<name> doctor
\`\`\`

</details>

<details>
<summary>Lightweight install (library use only)</summary>

If you only need the client library from Python (no display server / no CLI):

\`\`\`bash
uv add punt-<name>
\`\`\`

This pulls only the lightweight base deps. Heavy extras (GPU rendering, image
processing) are available via `punt-<name>[display]`.

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

The lightweight install tier only applies to projects with
[dependency layering](python.md#dependency-layering). Projects where all deps
are lightweight (e.g., biff, quarry) don't need it — `uv add punt-<name>`
already installs everything.

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
- **Stdin protection** — every `claude` command must have `< /dev/null` and
  every `ssh` command must use `-n`. Without this, `curl | sh` execution
  silently stops when a child process consumes pipe bytes (DES-006).
- **VERSION pin (mandatory)** — every `install.sh` MUST declare `VERSION="X.Y.Z"`
  near the top and use `uv tool install --force "$PACKAGE==$VERSION"`. The `punt release`
  CLI bumps this pin automatically during Phase 2. Without a VERSION pin, install is
  non-deterministic: `uv tool install` fetches latest from PyPI, which may not match the
  SHA pinned in `install-all.sh` or the project README. This has caused real version
  downgrade bugs in production.
- **EXTRAS pin (when applicable)** — projects with heavy optional deps (see
  [dependency layering](python.md#dependency-layering)) must declare `EXTRAS="display"`
  near the top and install with `"$PACKAGE[$EXTRAS]==$VERSION"`. The extras name must
  match the `[project.optional-dependencies]` section in `pyproject.toml`. Include the
  extras in failure messages so users see the exact command that failed.
- **Ends with `doctor`** — run the project's health check to verify the install.

Pattern: `biff/install.sh`, `vox/install.sh`.

### Updating the pinned SHA

SHA pins appear in four places. The release workflow automates most of these; manual
updates follow the same sequence.

| Location | What's pinned | Updated by |
|----------|--------------|------------|
| Project README | `raw.githubusercontent.com/<org>/<repo>/<SHA>/install.sh` | `punt release` Phase 4e (automatic after tagging) |
| `install-all.sh` | `$GH/<project>/<SHA>/install.sh` for each child project | `propagate.yml` GitHub Action (automatic on child release) |
| Org profile README | `raw.githubusercontent.com/punt-labs/punt-kit/<SHA>/install-all.sh` | `propagate-profile.yml` → `.github/propagate.yml` (automatic on `install-all.sh` change) |
| `public-website` `projects.json` | `installCommand` field per project | Manual during release Step 3 |

**Manual fallback** (when automation fails or for ad-hoc changes):

1. Commit the `install.sh` change and push
2. Copy the commit SHA: `git rev-parse --short HEAD`
3. Update the project README, `install-all.sh`, the org profile README, and
   `public-website/src/data/projects.json` with the new SHA
4. Commit and push each update separately

### README install SHA auto-update (Phase 4e)

During `punt release`, the project README's `install.sh` URL is automatically updated
after tagging:

1. Phase 4 creates the tag (`v{version}`)
2. Phase 4e resolves the tag's commit SHA via `git rev-parse --short v{version}`
3. Replaces both SHA-pinned (`/<hex>/install.sh`) and version-tagged
   (`/v1.2.3/install.sh`) URLs with the new SHA
4. Commits and pushes the change

This solves the chicken-and-egg problem: the SHA is only known after the commit that
contains the version bump, so README URLs can't be updated in the same commit as the
version bump. Phase 4e runs after the tag exists.

### Cross-repo propagation chain

A child project release triggers a multi-hop SHA propagation:

```text
Child release (e.g. vox v1.3.0)
  → punt-kit: propagate.yml bumps install-all.sh SHA, creates PR
    → punt-kit: PR merges to main
      → punt-kit: propagate-profile.yml fires (install-all.sh changed)
        → .github: propagate.yml updates profile README SHA, creates PR
          → .github: PR auto-merges
            → Public install URL serves current install-all.sh
```

A punt-kit release adds one more hop:

```text
punt-kit release
  → punt-kit: propagate.yml bumps its own install-all.sh SHA
  → claude-plugins: propagate.yml bumps marketplace version + ref
  → .github: propagate.yml updates profile README SHA
```

**`PROPAGATE_TOKEN` requirement.** Cross-repo workflow dispatch and cascade triggering
both require a fine-grained PAT stored as `secrets.PROPAGATE_TOKEN`:

- **Cross-repo dispatch**: `github.token` is scoped to the current repo only.
  Dispatching workflows in other repos requires a PAT with `actions:write` on the
  target repo.
- **Cascade triggering**: GitHub suppresses workflow triggers from events created by
  `GITHUB_TOKEN`. When a propagation PR auto-merges, the merge push must come from a
  PAT (not `github.token`) for downstream workflows to fire.
- **Auto-merge**: The PAT needs `pull-requests:write` on repos where propagation PRs
  use `gh pr merge --auto`.

See DES-012 in DESIGN.md for the full root cause analysis.

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
