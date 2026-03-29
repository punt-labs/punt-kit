# Daemon + Proxy MCP

When and how to use a resident daemon with an MCP proxy for tools with
heavy initialization costs.

---

## Problem

An MCP server that loads a large model, database, or resource on startup
imposes that cost on every session. With direct stdio, each `claude mcp`
invocation cold-starts the tool — loading an embedding model (2-5s),
opening a database (1-2s), or initializing an inference runtime (5-30s).
Users experience this as a hang on first tool call.

## Forces

- **Cold-start latency.** The heavier the initialization, the worse the
  user experience. Embedding models, LLMs, and large indexes are the
  primary offenders.
- **Cross-session state.** Some tools benefit from shared state across
  sessions (cached embeddings, open database connections, loaded models).
  Direct stdio creates isolated processes per session.
- **Platform support.** macOS and Linux have different service managers
  (launchd vs systemd). The daemon must support both.
- **Graceful degradation.** If the daemon isn't running, the tool should
  still work via direct stdio — slower, but functional.
- **Minimal binary.** The proxy that bridges MCP stdio to the daemon
  should be small and fast-starting. It exists only to translate
  protocols.

## Solution

### Architecture

```text
Claude Code ──stdio──→ mcp-proxy ──WebSocket──→ <tool> serve
                        (~5 MB Go)               (daemon, port N)
                        <10ms startup             model loaded once
```

Three components:

1. **Daemon** (`<tool> serve --port N`): Loads heavy resources once,
   stays resident. Serves HTTP API + WebSocket MCP endpoint at
   `ws://localhost:N/mcp`.

2. **mcp-proxy**: A small Go binary (~5 MB) that reads MCP JSON-RPC
   from stdin and forwards to the daemon over WebSocket. Downloads are
   SHA256-verified and platform-specific (darwin/linux × arm64/amd64).

3. **Fallback**: If mcp-proxy is unavailable, `<tool> mcp` serves MCP
   directly via stdio (cold-starting the tool each time).

### Decision matrix

| Init time | Shared state? | Architecture |
|-----------|--------------|--------------|
| < 2s | No | Direct stdio (`<tool> mcp`) |
| < 2s | Yes | Direct stdio + file-based state |
| > 2s | Any | Daemon + proxy |

### MCP client configuration

The install step configures MCP clients with a fallback script:

```bash
sh -c 'if command -v mcp-proxy >/dev/null 2>&1; \
  then exec mcp-proxy ws://localhost:<port>/mcp; \
  else exec <tool> mcp; fi'
```

(quarry uses port 8420; each tool chooses its own port.)

This prefers the proxy (fast, connects to resident daemon) but falls
back to direct stdio if the proxy isn't installed.

### Service registration

The install step registers the daemon as a system service:

- **macOS**: LaunchAgent plist in `~/Library/LaunchAgents/`
  (`launchctl load -w`)
- **Linux**: systemd user unit in `~/.config/systemd/user/`
  (`systemctl --user enable --now`)

Both are user-scoped — no root required.

### mcp-proxy installation

The proxy binary is downloaded during `<tool> install`:

1. Detect platform (`darwin`/`linux`) and architecture (`arm64`/`amd64`).
2. Download from GitHub releases with SHA256 verification.
3. Install to `~/.local/bin/mcp-proxy`.
4. The proxy is shared across tools — one binary serves any daemon.

### Per-session isolation

Each WebSocket connection to the daemon gets its own async task with
a `ContextVar` for database/state selection. `use("work")` in one
session does not affect others. This preserves the isolation semantics
of direct stdio while sharing the loaded resources.

## Consequences

- **Fast MCP calls.** First tool call in a session takes <100ms instead
  of 2-30s.
- **Shared resources.** The embedding model, database connections, and
  indexes load once across all sessions.
- **Extra moving parts.** Three components (daemon, proxy, service
  manager) instead of one. More to install, monitor, and debug.
- **Port allocation.** Each daemon needs a port. Convention: quarry
  uses 8420. Tools must not collide.
- **Graceful degradation.** If the daemon crashes, the fallback ensures
  tools still work (just slower).

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — daemon and proxy
  installation happen in Phase 1
- [Doctor Checks](doctor-checks.md) — daemon health is an informational
  check

## Known Uses

- **quarry v1.0.0+** — Embedding model (snowflake-arctic-embed-m-v1.5,
  ~120 MB INT8 ONNX) loads in 2-5s. Daemon on port 8420 serves MCP
  via WebSocket. See quarry architecture.tex § Daemon Model.
