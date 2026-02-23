# Dynamic Description Notify

## Problem

MCP has no push notification mechanism that renders in Claude Code. `notifications/message` is silently dropped (Claude Code issue #3174, closed not-planned). There is no way to push a visible alert to the user or the model from a background event — such as an incoming message, a completed build, or a state change.

## Forces

- MCP servers can mutate their own tool list and descriptions at any time.
- Claude Code refreshes its tool list when it receives a `notifications/tools/list_changed` notification.
- The model reads tool descriptions during tool discovery — changed descriptions become visible context.
- The human cannot see tool descriptions without expanding them in the UI.
- The human can see the Claude Code status line.

## Solution

Three complementary mechanisms:

### 1. Dynamic tool description

Mutate the tool's `description` field in-place to include the current state:

```text
"Check messages (2 unread: @kai about auth, @eric about lunch). Marks all as read."
```

When the description changes, fire `notifications/tools/list_changed` so Claude Code re-reads the tool list. The model then sees the updated description and can proactively act on it.

### 2. notifications/tools/list_changed

The notification must be sent through two code paths because MCP tool handlers and background tasks have different access to the session:

- **Inside a tool handler** — Use `get_context()` to access the FastMCP Context. Call `ctx._queue_tool_list_changed()` to piggyback the notification on the tool response. Also capture `ctx.session` for the background path.
- **Background task** — No request context exists. Use the stored `ServerSession` reference captured from the last tool call. Call `session.send_tool_list_changed()` directly. Best-effort — failures are logged, never raised.

### 3. Status line file

A background poller writes state to a JSON file (e.g., `~/.biff/unread/{key}.json`, where `key` is the topmost `claude` ancestor PID — see [Sibling PPID](sibling-ppid.md)). The status line script reads and displays it. This is the **human-visible** channel — the model cannot read the status line, and the human cannot easily read tool descriptions.

## Consequences

- The model sees state changes within 0-2 seconds (polling interval).
- The human sees state changes in the status line within 0-2 seconds.
- Neither channel alone is sufficient — both are needed for full coverage.
- A background poller task must run for the lifetime of the MCP server.
- The session reference must be captured from the first tool call and reused by the background poller.

## Related Patterns

- [Two-Channel Display](two-channel-display.md) — Handles the pull path (user requests data); Dynamic Description Notify handles the push path (data arrives while idle).
- [Sibling PPID](sibling-ppid.md) — The status line file (mechanism 3) uses the topmost `claude` ancestor PID as the shared key between the MCP server that writes it and the status line command that reads it.
- [Stash and Wrap](stash-and-wrap.md) — The status line command that reads the unread file is installed via the Stash and Wrap pattern.

## Known Uses

- **Biff (inbox)** — Background poller (`poll_inbox`) runs every 2 seconds. On unread count change, mutates `read_messages` tool description and fires `notifications/tools/list_changed`. Status line shows `biff(2)` for 2 unread messages.
- **Biff (wall)** — Same poller monitors team wall broadcasts. On wall change, mutates `wall` tool description to show the banner text, remaining duration, and author. Wall text content is sanitized (control chars and ANSI escapes stripped); the status line renderer then applies bold red formatting to the clean text, showing `WALL: release freeze`.
