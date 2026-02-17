# Stash and Wrap

## Problem

Claude Code's `statusLine` setting accepts a single command. There is no composition API — no "add to status line" mechanism. A tool that wants to display status information must own the entire `statusLine` value, but the user may already have a status line configured (their own script, another tool's output).

## Forces

- `statusLine` in `~/.claude/settings.json` is a single `{"type": "command", "command": "..."}` entry.
- Multiple tools may want to contribute segments to the status line.
- Overwriting the existing value silently destroys the user's configuration.
- There is no registry or plugin system for status line segments.

## Solution

Use a stash-and-wrap pattern:

1. **Stash** — Before replacing `statusLine`, read its current value and save it to a known file (e.g., `~/.biff/statusline-original.json`). This is the proof of installation — its presence means the tool owns the status line.

2. **Replace** — Set `statusLine` to the tool's own command (e.g., `biff statusline`).

3. **Wrap at runtime** — When the status line command runs, it reads the stash, executes the original command as a subprocess, captures its output, and appends the tool's own segment:

```
original-output | biff(2) myapp(1)
```

4. **Uninstall** — Read the stash, restore the original `statusLine` value, delete the stash file. The user's original configuration is preserved exactly.

## Consequences

- The user's existing status line is preserved through install/uninstall cycles.
- The stash file doubles as installation state — no separate flag needed.
- Only one tool can use this pattern at a time. If two tools both stash-and-wrap, the second tool stashes the first tool's wrapper, creating a chain. This works but is fragile — uninstalling the inner tool breaks the outer tool's delegation.
- The runtime cost is one subprocess invocation per status line refresh to execute the stashed command.
- The install command should be separate and optional (not bundled with the main install) because it modifies global UI visible in every session.

## Related Patterns

- [Sibling PPID](sibling-ppid.md) — The wrapped status line command uses PPID to find the correct state file written by its sibling MCP server process.
- [Two-Phase Install](two-phase-install.md) — Status line installation is a separate optional phase beyond the main Two-Phase Install, because it modifies global UI.
- [Dynamic Description Notify](dynamic-description-notify.md) — The status line is the human-visible channel of the push notification system. Stash and Wrap is how that channel gets installed.

## Known Uses

- **Biff** — `biff install-statusline` stashes the original to `~/.biff/statusline-original.json`, replaces with `biff statusline`. At runtime, executes the stashed command and appends unread counts. `biff uninstall` restores the original.
