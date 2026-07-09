# Two-Phase Install

## Problem

A PyPI package that provides both a CLI tool and a Claude Code integration (MCP
server, plugin, commands, hooks) cannot complete its Claude Code setup during
`uv tool install`. The `claude` CLI may not be on PATH during installation (CI,
containers), the user may install the package before installing Claude Code, and
modifying `~/.claude/` from a package installer is fragile and non-standard.

## Forces

- `uv tool install` runs in unpredictable environments where `claude` may not
  exist.
- Claude Code integration requires marketplace registration, plugin installation,
  and permission configuration — all via the `claude` CLI.
- The user expects a single clear setup path, not a maze of manual steps.
- The CLI tool itself should work immediately after `uv tool install`, even
  without Claude Code.

## Solution

Split installation into two explicit phases:

### Phase 1: `uv tool install punt-<name>`

Installs the Python package and CLI entry point. The CLI works immediately. No
Claude Code dependency.

### Phase 2: `claude plugin install <name>@punt-labs`

The marketplace handles plugin distribution. Claude Code clones the plugin from
the marketplace repository, which includes hooks, commands, skills, and MCP
server declarations. The plugin's `mcpServers` field references the CLI binary
installed in Phase 1.

Phase 2 is idempotent — `claude plugin install` fails gracefully if the plugin
is already installed.

### Bootstrap script

A single `install.sh` chains everything for zero-thought setup:

1. Verify prerequisites (Python 3.13+, uv, claude CLI)
2. `uv tool install punt-<name>` (Phase 1)
3. Register marketplace (`claude plugin marketplace add`)
4. Refresh marketplace (`claude plugin marketplace update`) — ensures existing
   users pick up `source.ref` pins (DES-003)
5. `claude plugin install <name>@punt-labs` (Phase 2)
6. `<tool> doctor` (verification)

Users run:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/<repo>/<SHA>/install.sh | sh
```

### Optional phases

Tools with richer integration needs extend the two-phase model with
additional steps. These run during `<tool> install` (called by the
bootstrap script after Phase 1):

- **Phase 2a: CLAUDE.md `@`-import registration.** Write the tool's usage doc
  to `~/.punt-labs/<product>/CLAUDE.md` and register its `@`-import in
  `~/.claude/CLAUDE.md` so agents know what slash commands and auto-behaviors
  are available. See
  [CLAUDE.md `@`-import Includes](claude-md-injection.md).
- **Phase 2b: Ethos extension setup.** Write `session_context` into
  ethos identity extension files so agents receive tool-specific
  instructions at every session start and after compaction. See
  [Ethos Extension Setup](ethos-ext-setup.md).
- **Phase 3: Status line.** See [Stash and Wrap](stash-and-wrap.md).

Not every tool needs every phase. Only add phases that have callers.

## Consequences

- The CLI works immediately after Phase 1, even without Claude Code installed.
- Phase 2 runs when the user is ready and Claude Code is present.
- Upgrades reinstall the CLI (`--force`) and the plugin picks up changes on next
  marketplace refresh.
- The `doctor` command validates both phases and external dependencies (API keys,
  relay connectivity, etc.) in one shot.
- The separation means Phase 1 is testable in CI without Claude Code.

## Related Patterns

- [Dual Command Path](dual-command-path.md) — The SessionStart hook deploys
  top-level commands after the plugin is installed.
- [Doctor Checks](doctor-checks.md) — Validates the results of both phases plus
  external dependencies that neither phase controls.
- [CLAUDE.md `@`-import Includes](claude-md-injection.md) — Phase 2a: register
  the tool's `@`-import into global agent context.
- [Ethos Extension Setup](ethos-ext-setup.md) — Phase 2b: write session context
  into ethos identity extensions.
- [Stash and Wrap](stash-and-wrap.md) — Phase 3: status line integration,
  separated because it modifies global UI.
- [Daemon + Proxy MCP](daemon-proxy-mcp.md) — Daemon and proxy installation
  happen during Phase 1 for tools with heavy initialization.

## Known Uses

- **Biff** — `uv tool install punt-biff` (Phase 1) + `claude plugin install
  biff@punt-labs` (Phase 2) + `biff doctor` (verification). All sequenced by
  `install.sh`.
- **Quarry** — Same pattern. `install.sh` handles marketplace registration,
  refresh, plugin install, and doctor.
- **TTS** — Same pattern. `install.sh` also prints post-install hints for
  `/notify` and `/recap` commands.
- **punt-kit** — Same pattern. The `punt` CLI provides `audit` and `init`; the
  plugin provides slash commands and dev commands.
