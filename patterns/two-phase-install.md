# Two-Phase Install

## Problem

A PyPI package that provides both a CLI tool and a Claude Code integration (MCP server, plugin, commands, hooks) cannot complete its Claude Code setup during `pip install`. The `claude` CLI may not be on PATH during installation (CI, virtualenvs, Docker), the user may install the package before installing Claude Code, and writing to `~/.claude/` from a pip post-install hook is fragile and non-standard.

## Forces

- `pip install` runs in unpredictable environments where `claude` may not exist.
- Claude Code integration requires writing to `~/.claude.json` (MCP registration), `~/.claude/plugins/` (plugin files), `~/.claude/settings.json` (plugin enablement), and `~/.claude/plugins/installed_plugins.json` (registry).
- The user expects a single clear setup path, not a maze of manual steps.
- The CLI tool itself should work immediately after `pip install`, even without Claude Code.

## Solution

Split installation into two explicit phases:

### Phase 1: `pip install <package>`

Installs the Python package, CLI entry point, and all bundled data (plugin source files, credentials, etc.) into site-packages. The CLI works immediately. No Claude Code dependency.

### Phase 2: `<tool> install`

An explicit CLI subcommand that registers everything with Claude Code:

1. Register MCP server (`claude mcp add`)
2. Copy plugin files to `~/.claude/plugins/<name>/`
3. Copy user commands to `~/.claude/commands/`
4. Register in plugin registry (`installed_plugins.json`)
5. Enable in settings (`settings.json`)

Phase 2 is idempotent — every step checks for existing state and overwrites or skips as appropriate. Running it twice is safe and handles upgrades.

### Bootstrap script

A one-liner chains everything for zero-thought setup:

```bash
pip install <package>
<tool> install
<tool> doctor
```

## Consequences

- The CLI works immediately after Phase 1, even without Claude Code installed.
- Phase 2 runs when the user is ready and Claude Code is present.
- Upgrades rerun Phase 2 to update plugin files and registry entries.
- The `doctor` command validates both phases and external dependencies (GitHub CLI, relay connectivity, etc.) in one shot.
- The separation means Phase 1 is testable in CI without Claude Code.

## Known Uses

- **Biff** — `pip install biff-mcp` (Phase 1) + `biff install` (Phase 2) + `biff doctor` (verification). Status line is a third optional phase (`biff install-statusline`) because it modifies global UI.
