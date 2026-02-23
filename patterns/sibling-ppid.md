# Sibling PPID

## Problem

Two processes spawned by Claude Code — the MCP server (via stdio transport) and the status line command — need to share state through a file. They need a shared identifier to agree on a filename, but Claude Code does not expose a session ID as an environment variable to either child process.

## Forces

- Claude Code spawns the MCP server as a child process (stdio transport manages the lifecycle).
- Claude Code spawns the status line command as a child process.
- The MCP `initialize` handshake provides only `clientInfo.name` and `clientInfo.version`, no session identity.
- Claude Code sends rich session JSON to the status line via stdin (including `session_id`, `cwd`, `session_name`), but this data is not available to the MCP server.
- Multiple concurrent Claude Code sessions must not stomp each other's state files.
- **Claude Code may interpose intermediate child processes** between the main process and MCP servers. The MCP server and status line may have different immediate parents.

## Solution

Walk the process tree upward to find the **topmost `claude` ancestor PID** and use that as the shared file key. Both the MCP server and the status line command converge on the same ancestor regardless of intermediate processes.

### Algorithm

1. Run `ps -eo pid=,ppid=,comm=` to snapshot the full process table.
2. Walk from `os.getpid()` upward through the parent chain.
3. Track the highest PID whose `comm` basename is `claude`.
4. Return that PID. If no `claude` ancestor is found, fall back to `os.getppid()`.

### Why not `os.getppid()`

The original pattern used `os.getppid()` directly, assuming both children had the same immediate parent. This was falsified in February 2026 when Claude Code introduced an intermediate child process for MCP server management:

```text
19147 claude (main)                      ← statusline parent
└─ 57369 claude (child — MCP manager)   ← MCP server parent
     ├─ 57375 biff serve (prod)
     └─ 57377 biff serve (dev)
```

The MCP server's `os.getppid()` returns 57369. The statusline's `os.getppid()` returns 19147. Walking up the tree, both converge on the topmost `claude` process.

### Implementation details

- **Single `ps` call** — One `ps -eo pid=,ppid=,comm=` call per process lifetime. Parsed into a `{pid: (ppid, comm)}` dict, walked in pure Python.
- **Cached** — The ancestor PID is computed once and cached at module level. Process trees don't change during a session.
- **Safety bound** — Walk is bounded to 10 levels (process trees are shallow). Prevents infinite loops on malformed tables.
- **Return code check** — If `ps` exits non-zero, treat as failure and fall back.
- **Backward compatible** — In the original direct-child model (no intermediate process), the walk still converges on the correct ancestor.

### Cleanup

The MCP server deletes its keyed file in the lifespan `finally` block on shutdown. This prevents stale files from accumulating when sessions end.

## Consequences

- Multiple concurrent Claude Code sessions get isolated state files (different ancestor PIDs).
- No configuration or environment variable setup required.
- Robust to Claude Code process model changes — intermediate child processes, nested claude subprocesses, and shell wrappers are all handled.
- Adds a one-time `ps` subprocess call (~10ms on macOS). Negligible cost for the MCP server (cached). The statusline is a fresh process each render, but `ps` is fast enough for interactive use.
- PID reuse is theoretically possible but practically irrelevant — the cleanup on shutdown prevents stale files.

## Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Raw `os.getppid()` | **Falsified.** Claude Code may interpose intermediate child processes, causing MCP server and statusline to have different PPIDs. |
| Environment variable from Claude Code | Claude Code does not expose `session_id` as an env var to MCP server children |
| MCP initialize handshake | `clientInfo` contains only `name` and `version`, no session identity |
| Scan all state files | Status line wouldn't know which file is "mine" — showing all sessions is noisy |
| Session ID from stdin JSON | Available to the status line but not to the MCP server — no way to agree |

## Related Patterns

- [Dynamic Description Notify](dynamic-description-notify.md) — The MCP server writes the state file that Sibling PPID makes addressable. The status line reads it.
- [Stash and Wrap](stash-and-wrap.md) — The status line command that reads the PPID-keyed file is installed via Stash and Wrap.

## Known Uses

- **Biff** — `session_key.py` walks the process tree to find the topmost `claude` ancestor. MCP server writes unread counts and wall text to `~/.biff/unread/{key}.json`. Status line reads the same file. Verified across multiple concurrent sessions, including with intermediate claude child processes (DES-011a).
