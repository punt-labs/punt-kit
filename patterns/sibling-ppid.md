# Sibling PPID

## Problem

Two processes spawned by Claude Code — the MCP server (via stdio transport) and the status line command — need to share state through a file. They need a shared identifier to agree on a filename, but Claude Code does not expose a session ID as an environment variable to either child process.

## Forces

- Claude Code spawns the MCP server as a direct child process (stdio transport manages the lifecycle).
- Claude Code spawns the status line command as a direct child process.
- Both children have the same parent PID — the Claude Code process for that session.
- The MCP `initialize` handshake provides only `clientInfo.name` and `clientInfo.version`, no session identity.
- Claude Code sends rich session JSON to the status line via stdin (including `session_id`, `cwd`, `session_name`), but this data is not available to the MCP server.
- Multiple concurrent Claude Code sessions must not stomp each other's state files.

## Solution

Use `os.getppid()` as the shared file key. Both the MCP server and the status line command call `os.getppid()` to get the PID of their parent (the Claude Code process). They use this as a filename component:

```text
Claude Code (PID 30757)
├── biff serve --transport stdio   (MCP server, ppid=30757, writes file)
├── biff statusline                (status line, ppid=30757, reads file)
```

The MCP server writes state to `~/.biff/unread/{ppid}.json`. The status line reads `~/.biff/unread/{ppid}.json`. The PPID is the only identifier they share.

### Cleanup

The MCP server deletes its PPID-keyed file in the lifespan `finally` block on shutdown. This prevents stale files from accumulating when sessions end.

## Consequences

- Multiple concurrent Claude Code sessions get isolated state files (different PIDs).
- No configuration or environment variable setup required.
- The pattern depends on stdio transport — the MCP server must be a direct child of Claude Code, not a user-managed background process (which would have a different parent).
- If Claude Code's process model changes (e.g., spawning children through an intermediary shell), the PPID assumption breaks. Verified empirically: Claude Code spawns both children directly, no shell intermediary.
- PID reuse is theoretically possible but practically irrelevant — the cleanup on shutdown prevents stale files.

## Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Environment variable from Claude Code | Claude Code does not expose `session_id` as an env var to MCP server children |
| MCP initialize handshake | `clientInfo` contains only `name` and `version`, no session identity |
| Scan all state files | Status line wouldn't know which file is "mine" — showing all sessions is noisy |
| Session ID from stdin JSON | Available to the status line but not to the MCP server — no way to agree |

## Related Patterns

- [Dynamic Description Notify](dynamic-description-notify.md) — The MCP server writes the state file that Sibling PPID makes addressable. The status line reads it.
- [Stash and Wrap](stash-and-wrap.md) — The status line command that reads the PPID-keyed file is installed via Stash and Wrap.

## Known Uses

- **Biff** — MCP server writes unread counts to `~/.biff/unread/{ppid}.json`. Status line reads the same file. Verified across multiple concurrent Claude Code sessions with matching PPIDs.
