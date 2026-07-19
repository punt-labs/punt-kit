# Distribution Standards

How each of a tool's surfaces is shipped and installed. For what the surfaces
are — the engine-and-clients model — see
[architecture.md](architecture.md#the-projection-model-canonical).

---

## Surfaces versus channels

A surface is how a caller reaches the engine; a channel is how a surface is
shipped (see
[architecture.md](architecture.md#surfaces-versus-channels) for the surface
definitions and the principle). One surface can ship through several channels:

| Surface | Distribution channel |
|---------|----------------------|
| Library | PyPI (`uv add punt-<name>`) |
| CLI | PyPI (`uv tool install punt-<name>`) |
| MCP server | `claude mcp add` (standalone), plugin `mcpServers` (hybrid), or `.mcpb` one-click bundle (Claude Desktop) |
| REST API | `<tool> serve` (HTTP) |

The plugin shell and the `.mcpb` desktop bundle are channels for the MCP
surface, not separate surfaces; a native app is a channel for a platform-native
front end (App Store, TestFlight, Homebrew), outside the four client surfaces.

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
- **Uninstall before install** — call
  `claude plugin uninstall <name>@<marketplace> < /dev/null 2>/dev/null || true`
  immediately before `claude plugin install`. The observed behavior on a
  stuck dev machine (beadle-4qk, 2026-04-07) is that re-running `install.sh`
  does **not** upgrade an existing installation: the cache stayed pinned to
  the originally-installed version even though the marketplace clone had
  been refreshed to a newer ref. The simplest explanation is that
  `claude plugin install` short-circuits when the plugin is already present
  in the target scope, regardless of version. This was not directly verified
  by running `claude plugin install` standalone — the evidence is the failure
  mode itself: without an explicit uninstall, re-runs of `install.sh` did
  not flip the active version; with an uninstall, they do. Note that Claude
  Code keeps a versioned cache directory per installed version
  (`~/.claude/plugins/cache/<org>/<name>/<version>/`) — multiple versions
  cohabit by design, and `installed_plugins.json` records which one is
  active per scope. Pattern: `biff/install.sh:138`, `quarry/install.sh:175`,
  `vox/install.sh:169`, `beadle/install.sh:149`. The full ordering is
  **marketplace refresh → uninstall → install**. Use `claude plugin uninstall +
  install`, **not** `claude plugin update` — Punt Labs learned `update` has
  issues this pattern avoids (institutional knowledge from another project,
  not re-derived here).
- **Detect uninstall failure** — the simple
  `< /dev/null 2>/dev/null || true` shape silences both expected failures
  (plugin not installed on a fresh machine) and unexpected ones (transient
  network error, removed subcommand, permission issue). When uninstall
  silently fails on an installed user, the subsequent `claude plugin install`
  is likely to short-circuit (per the previous bullet) and leave the user
  pinned to the old version with no signal that the upgrade failed. The
  hardened pattern must distinguish the two cases: detect installed state
  first (via `claude plugin list` or by reading
  `~/.claude/plugins/installed_plugins.json`), skip uninstall on a fresh
  machine, and propagate real uninstall failures with an actionable error
  message instead of swallowing them. If the install itself fails after a
  successful uninstall, surface a clear error — the exact recovery story
  (whether the previous cache directory persists and can be reactivated, or
  whether `claude plugin uninstall` deletes the cache directory entirely) is
  not yet characterised; this bullet should be updated when the first
  implementation lands and the behavior is empirically verified. Cross-
  cutting work tracked in: `biff-8hg1`, `quarry-9ipx`, `vox-2fj`,
  `beadle-2nk`. The first repo to land the hardened implementation becomes
  the canonical reference; the others backport to keep the four scripts in
  lockstep, and this bullet is updated with the concrete shell snippet once
  one is validated.
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
| Project README | `raw.githubusercontent.com/<org>/<repo>/<SHA>/install.sh` | `punt release` Phase 9 (post-release PR) |
| `install-all.sh` | `$GH/<project>/<SHA>/install.sh` for each child project | `punt release` Phase 10a (sibling PR) |
| Org profile README | `raw.githubusercontent.com/punt-labs/punt-kit/<SHA>/install-all.sh` | `punt release` Phase 10c (sibling PR, punt-kit only) |
| `public-website` `projects.json` | `installCommand` field per project | `punt release` Phase 10d (sibling PR) |

**Manual fallback** (when automation fails or for ad-hoc changes):

1. Commit the `install.sh` change and push
2. Copy the commit SHA: `git rev-parse --short HEAD`
3. Update the project README, `install-all.sh`, the org profile README, and
   `public-website/src/data/projects.json` with the new SHA
4. Commit and push each update separately

### README install SHA auto-update (Phase 9)

During `punt release`, the project README's `install.sh` URL is automatically updated
in the post-release phase:

1. Phase 4 merges the release PR to main (via squash-merge)
2. Phase 5 tags main HEAD
3. Phase 9 creates a `post-release/vX.Y.Z` branch, resolves the install.sh
   commit SHA, replaces both SHA-pinned (`/<hex>/install.sh`) and version-tagged
   (`/v1.2.3/install.sh`) URLs with the new SHA, and merges via PR

This solves the chicken-and-egg problem: the SHA is only known after the commit that
contains the version bump, so README URLs can't be updated in the same commit as the
version bump. Phase 9 runs after the tag exists.

### Cross-repo propagation (Phase 10)

`punt release` Phase 10 handles all cross-repo SHA and version propagation
locally. All sibling repos must be checked out as siblings in the same parent
directory (`../punt-kit`, `../claude-plugins`, `../.github`,
`../public-website`). Each propagation step creates a branch, commits the
change, pushes, creates a PR, waits for CI, and squash-merges.

```text
Child release (e.g. vox v1.3.0)
  Phase 10a → punt-kit: install-all.sh SHA updated via PR
  Phase 10b → claude-plugins: marketplace.json version + ref via PR
  Phase 10d → public-website: projects.json version via PR

punt-kit release (adds one more step)
  Phase 10c → .github: profile README install-all.sh SHA via PR
```

No GitHub Actions workflows, secrets, or PATs are needed for propagation.
The developer's local git credentials provide push access to all siblings.
See DES-013 and DES-016 in DESIGN.md for the full design history.

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

#### When to use a daemon

Tools with heavy initialization (embedding models, inference runtimes, large
indexes) or shared hardware resources (speakers, microphones) should use a
resident daemon instead of cold-starting on every MCP call. Decision criteria:

| Init time | Shared resource? | Architecture |
|-----------|-----------------|--------------|
| < 2s | No | Direct stdio (`<tool> mcp`) |
| < 2s | Yes (file-based) | Direct stdio + file-based state |
| > 2s or shared hardware | Any | Daemon (`<tool>d`) + lightweight stdio MCP client |

Architecture: the daemon binary (`<tool>d`) starts once, listens on a port
(WebSocket or HTTP), and owns the shared resource. The MCP server
(`<tool> mcp`) is a lightweight stdio process that holds session state in
memory and delegates to the daemon over WebSocket. This separates the MCP
session lifecycle (per Claude Code session) from the daemon lifecycle
(per machine).

```text
Claude Code ◄── stdio ──► <tool> mcp ── WebSocket ──► <tool>d :port
```

**Daemon restart does not break MCP sessions.** The MCP session is stdio
(unaffected). The `<tool> mcp` process must implement WebSocket reconnection
with backoff so it re-establishes the connection to the daemon after a restart.

**Service registration:** system-level, requires `sudo`:

- macOS: `/Library/LaunchDaemons/` with `UserName` = installing user
- Linux: `/etc/systemd/system/` with `User` = installing user

The daemon runs as the installing user (not root) because it needs access
to audio devices, display servers, or other user-session resources.

**Daemon data:** daemon runtime state (config, logs, port/token files) lives
in system directories. This is an exception to the `~/.punt-labs/<tool>/`
convention in [filesystem.md](filesystem.md), which applies to client-side
CLI tools. Daemons are system services and follow platform conventions:

- macOS: `$(brew --prefix)/etc/<tool>/`, `$(brew --prefix)/var/log/<tool>/`,
  `$(brew --prefix)/var/run/<tool>/`
- Linux: `/etc/<tool>/`, `/var/log/<tool>/`, `/var/run/<tool>/`

Client-side state (caches, per-project config) may still use
`~/.punt-labs/<tool>/` per the filesystem standard.

**Install must bounce the daemon.** Every `install.sh` that installs a
package with a daemon must: (1) stop the existing daemon, (2) install the
new code, (3) restart the daemon. The installer exits only after the daemon
is running the new code. Use `sudo env "PATH=$PATH" <tool> daemon install`
to preserve the user's PATH through sudo (required because `~/.local/bin/`
is not in root's secure_path and some sudoers configs restrict env vars).

**Daemon-based tools:** vox (`voxd`), quarry, cryptd, lux (planned).
Reference implementation:
[vox DESIGN.md DES-028](https://github.com/punt-labs/vox/blob/main/DESIGN.md#des-028-vox-v3--audio-server-architecture).

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

## Ethos Extension Setup

Tools that need to inject instructions into the agent's context at session
start and after context compaction use the ethos extension mechanism. Ethos
emits the `session_context` key from any extension YAML verbatim — no
tool-specific code in ethos.

### Extension file

```text
~/.punt-labs/ethos/identities/<handle>.ext/<tool>.yaml
```

The file contains tool-specific config keys and a `session_context` YAML
literal block scalar with markdown instructions.

### Install behavior

During `<tool> install`, scan all identity extension directories and append
`session_context` to any `<tool>.yaml` that has config keys but no
`session_context`. Rules:

- **Raw-append, not YAML round-trip.** `yaml.safe_load` to parse, raw file
  append to write. `yaml.dump` destroys comments and formatting.
- **Idempotent.** Skip if `session_context` already present.
- **Per-identity exception handling.** One malformed file must not abort the
  rest.
- **Surface missing config.** Identities with `<tool>.yaml` but no expected
  config key should be reported, not silently skipped.

### Ownership boundary

The tool owns its instructions. Ethos delivers them. Adding a new tool's
session context requires zero ethos code changes.

Pattern: [ethos-ext-setup](../patterns/ethos-ext-setup.md). Reference
implementation: quarry v1.8.1 DES-019.

---

## CLAUDE.md `@`-import Includes

Tools that provide slash commands, auto-behaviors, or agents make their usage
instructions available to every session by **owning a doc file that `CLAUDE.md`
`@`-imports** — not by injecting content blocks into the user's `CLAUDE.md`.
Claude Code loads `@`-imported files into context (verified against Claude Code:
it resolves `~` and loads the import from any working directory), so the tool's
doc is always present and always current.

### Why import, not inject

The older approach wrote a marker-wrapped block directly into
`~/.claude/CLAUDE.md`. It had two flaws: **no update path** — a block once
written was never refreshed, so stale content persisted across versions — and
the user's `CLAUDE.md` grew with every tool. An `@`-import reference is one
line; the tool owns the imported file, so updates flow automatically and the
`CLAUDE.md` stays clean.

### Scope follows the tool — global by default

A tool's doc lives where the tool applies:

```text
~/.punt-labs/<product>/CLAUDE.md       # GLOBAL tool (default) — imported from ~/.claude/CLAUDE.md
<repo>/.punt-labs/<product>/CLAUDE.md  # PROJECT tool — vendored in the repo, imported from <repo>/CLAUDE.md
```

Most tools that use this mechanism (quarry, biff, vox) are **global** — they
work in every project, including ones with no repo `CLAUDE.md` and no `punt`
scaffolding. A global tool writes `~/.punt-labs/<product>/CLAUDE.md` and
registers `@~/.punt-labs/<product>/CLAUDE.md` in `~/.claude/CLAUDE.md` **at
install time** (runs once, covers every project deterministically). Reserve
project-scope for a doc that genuinely belongs to one repo and is committed with
it; its import is reconciled by `/punt:init` as part of repo setup. Do NOT make
project-scope the default: install runs once (not per-project), and a
repo-committed managed section regenerated from one developer's local installs
bakes their toolset into everyone's checkout. The tool owns and rewrites its
doc on install, and registers its own `@`-import line **through the shared
reconcile** (below) — it never makes ad hoc edits to the consuming `CLAUDE.md` or touches
anything outside its own managed line.

### The managed Tool Guidance section

The consuming `CLAUDE.md` (`~/.claude/CLAUDE.md` for global tools,
`<repo>/CLAUDE.md` for project tools) carries ONE managed section listing the
imports:

```markdown
<!-- punt:mandatory-reading -->
## Tool Guidance (auto-loaded)

These docs load into context via `@`-import — nothing to open.

@~/.punt-labs/quarry/CLAUDE.md
@~/.punt-labs/vox/CLAUDE.md
<!-- /punt:mandatory-reading -->
```

One shared reconcile — keyed on the `punt:mandatory-reading` markers — owns the
section's bytes; no tool hand-edits `CLAUDE.md` outside it. A tool registers or
prunes only its **own** `@`-import line through that reconcile, which regenerates
the section so lines stay sorted and de-duplicated. As a first step a tool may
self-register via the shared reconcile; the end state is a `punt`-owned
multi-tool reconcile that regenerates the whole list from the installed
`.punt-labs/*/CLAUDE.md` docs — adding a line when a doc appears, pruning it when
the tool is removed — superseding per-tool self-registration.

### Rules

- **Tool owns the doc; the shared reconcile owns the section.** A tool writes
  its own `~/.punt-labs/<product>/CLAUDE.md` and registers only its own
  `@`-import line through the shared reconcile; it never makes ad hoc edits to
  the consuming `CLAUDE.md`, touches other tools' lines, or alters content
  outside the managed markers.
- **The consuming `CLAUDE.md` is sacred — reconcile is a pure no-op on every
  byte outside the managed markers.** It is hand-authored and may be symlinked
  by a dotfile manager. The reconcile MUST:
  - **Write atomically** — temp file in the target's directory, `fsync`,
    `os.replace` (atomic on POSIX); never truncate-in-place. State a
    single-writer assumption (installs are rare and manual).
  - **Resolve symlinks** — if the target is a symlink, write its real target and
    preserve the link (dotfile managers depend on this).
  - **Preserve bytes and mode** — content outside the markers stays
    byte-identical across LF / CRLF / lone-CR endings (read *and* write with
    `newline=""`; universal-newline translation silently rewrites the user's
    endings). A new file gets a predictable `0644`; an existing file keeps its
    mode.
  - **Be deterministic and no-op-when-unchanged** — sort the import lines; write
    only when the bytes actually change.
  - **Be corruption-safe** — a lone or duplicated marker collapses to one
    canonical section; never append a second.
  - **Match markers at column 0, outside code fences** — markers and `@`-lines
    must be top-level (Claude Code does not resolve `@`-imports inside code
    spans/fences), and a marker string appearing inside a fenced or indented
    code block must not be consumed.
  - **Validate the import line** — a single top-level `@…` line, no embedded
    newline, no stray whitespace.
- **The doc is the tool's agent-facing manual.** Slash commands, auto-behaviors,
  tips, gotchas. It may exceed the old 10-15 line cap — but `@`-imported content
  loads fully into every session's context, so keep it usage guidance, not a
  full reference (the host file shrinks; per-session context does not).
- **Keep imports shallow.** Claude Code resolves `@`-imports recursively to a
  bounded depth; don't chain deep import trees from the tool doc.

Migration (forward integration, no compat shim): a tool currently injecting a
`<!-- <tool>:capabilities -->` block moves that content into its
`~/.punt-labs/<product>/CLAUDE.md`, registers the `@`-import, and MUST delete its
own legacy injected block from `~/.claude/CLAUDE.md` in the same release — an
orphaned block is a defect.

Pattern: [CLAUDE.md `@`-import includes](../patterns/claude-md-injection.md).
Reference implementation: **vox** — `src/punt_vox/claude_md.py` (`GlobalClaudeImports`
reconcile) + `guidance.py`; the `@`-import load is empirically verified against
Claude Code and the reconcile invariants (atomic, symlink-safe, byte-preserving
across line endings, deterministic, corruption-safe) are covered by a
`prune(register(x)) == x` property test. quarry's `_inject_claude_md()` block is
the migration target.

---

## Local Development Depot

During cross-project development, changes to a dependency (e.g., biff depends
on lux) need to be tested before publishing to PyPI. The **depot** is a shared
local directory (`.depot/` at the workspace root) where `make depot` copies
built wheels. Consumers use `uv.toml` with `find-links` to resolve from the
depot before falling back to PyPI.

### Producer side

Every project with a `build` target also has a `depot` target:

```bash
make depot   # builds wheel, copies to ../.depot/
```

The Makefile variable:

```makefile
DEPOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../.depot

depot: build ## Build and copy wheel to local depot
	@mkdir -p $(DEPOT)
	@cp dist/*.whl $(DEPOT)/
	@echo "depot: $$(ls dist/*.whl | xargs -n1 basename) -> $(DEPOT)/"
```

### Consumer side

Add a `uv.toml` in the consumer project (gitignored) to prefer depot wheels:

```toml
[pip]
find-links = ["../.depot"]
```

Then `uv sync` and `uv run` will resolve depot wheels first. Remove the
`uv.toml` when done testing to return to PyPI-only resolution.

### Rules

1. **`.depot/` lives at the workspace root** (parent of all project repos),
   not inside any single project.
2. **`uv.toml` is gitignored** in every project. It is a local override, never
   committed.
3. **Depot wheels are development-only.** Never publish a depot wheel to PyPI.
   The depot is for local cross-project testing before a release.
4. **`make depot` implies `make build`.** The depot target depends on the build
   target, so artifacts are always fresh.

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
