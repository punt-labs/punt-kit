# Doctor Checks

## Problem

After installation, the user needs a single command to answer "is everything working?" The installer reports what it did, but it cannot verify external dependencies (GitHub CLI authentication, relay connectivity, runtime config files) that it does not control.

## Forces

- Installation touches multiple systems: PyPI package, Claude Code MCP registration, plugin files, plugin registry, settings, optional status line.
- External dependencies (GitHub CLI, NATS relay, per-repo config) are outside the installer's control.
- Some checks are hard requirements (must pass for the tool to function). Others are informational (nice to have, not critical).
- The doctor command runs post-install and on-demand when debugging issues.

## Solution

Implement a `doctor` subcommand that runs a checklist of diagnostic checks, each classified as **required** or **informational**:

### Required checks (must pass, exit code 1 on failure)

- External CLI dependencies installed and authenticated (e.g., `gh auth status`)
- MCP server registered in Claude Code (`claude mcp list`)
- Plugin files deployed and present
- Network connectivity to external services (e.g., relay server)

### Informational checks (report status, do not fail)

- Per-repo config file exists (`.biff`, `.env`, etc.)
- Optional features installed (status line, shell completion)
- Version compatibility warnings
- Ethos extension: `session_context` present in identity ext file (see
  [Ethos Extension Setup](ethos-ext-setup.md))
- CLAUDE.md: tool's `@`-import registered in the managed section (see
  [CLAUDE.md `@`-import Includes](claude-md-injection.md))
- Daemon health: process running, port responding (see
  [Daemon + Proxy MCP](daemon-proxy-mcp.md))

### Output format

Each check prints a status indicator and description:

```text
✓ GitHub CLI authenticated
✓ MCP server registered
✓ Plugin commands installed
✓ NATS relay reachable
○ .biff file (not found — run biff init in a repo)
○ Status line (not installed — run biff install-statusline)
```

Exit code 0 if all required checks pass. Exit code 1 if any required check fails.

## Consequences

- Users have a single command to diagnose problems after installation or when something breaks.
- The required/informational split prevents false alarms from optional features while ensuring critical failures are caught.
- Doctor checks must be maintained alongside the installer — a new install step needs a corresponding doctor check.
- Network checks need timeouts (e.g., 3 seconds) to avoid hanging on unreachable services.
- The doctor command should resolve configuration the same way the runtime does (same config loading, same fallback chain) to catch config mismatches.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — Doctor validates the results of both install phases plus external dependencies that neither phase controls.
- [Dual Command Path](dual-command-path.md) — Doctor checks user commands as informational, since namespaced plugin commands are the fallback.
- [Stash and Wrap](stash-and-wrap.md) — Doctor checks status line installation as informational (optional feature).

## Known Uses

- **Biff** — `biff doctor` runs six checks: `gh` CLI (required), MCP server (required), plugin commands (required), NATS relay (required), `.biff` file (informational), status line (informational). NATS connectivity uses a 3-second timeout with `asyncio.run()`.
- **Quarry** — `quarry doctor` runs nine checks: Python version, data directory, local OCR, embedding model, core imports, mcp-proxy, Claude Code MCP, Claude Desktop MCP, storage. `quarry install` adds ethos ext session_context and CLAUDE.md checks during the install flow.
