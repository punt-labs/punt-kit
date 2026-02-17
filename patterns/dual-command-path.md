# Dual Command Path

## Problem

Claude Code plugins namespace their commands under the plugin name (`/biff:who`, `/biff:finger`). Users expect short, memorable commands (`/who`, `/finger`). The namespaced form is correct for disambiguation but hostile to daily use.

## Forces

- Plugin commands live in `~/.claude/plugins/<name>/commands/` and are namespaced as `/<name>:<command>`.
- User commands live in `~/.claude/commands/` and are top-level (`/<command>`).
- Both locations load the same `.md` file format.
- Some users may disable the plugin but still want the MCP server and top-level commands.
- Command filenames must not collide with other plugins' commands in the global namespace.

## Solution

Deploy the same command `.md` files to both locations during installation:

1. **Plugin commands** — `~/.claude/plugins/<name>/commands/*.md` — namespaced as `/<name>:<command>`.
2. **User commands** — `~/.claude/commands/*.md` — top-level as `/<command>`.

Both are `shutil.copy2()` from the same bundled source. The installer owns both targets.

```
~/.claude/
├── plugins/biff/commands/who.md    → /biff:who
├── plugins/biff/commands/finger.md → /biff:finger
├── commands/who.md                 → /who
└── commands/finger.md              → /finger
```

### Uninstall

Only remove files whose names match the bundled command filenames. Do not touch non-owned files that may exist in `~/.claude/commands/`.

## Consequences

- Users get both `/<command>` and `/<name>:<command>` — short form for daily use, namespaced form when disambiguation is needed.
- The plugin can be disabled without losing top-level commands (MCP server + user commands still work).
- If another plugin deploys a command with the same filename to `~/.claude/commands/`, the last installer wins. Choose distinctive filenames.
- The doctor command should check user commands as informational (not required) since the namespaced plugin commands are the fallback.

## Known Uses

- **Biff** — Deploys `who.md`, `finger.md`, `write.md`, `read.md`, `plan.md`, `mesg.md`, `tty.md` to both plugin and user command directories. Users type `/who` daily; `/biff:who` exists for disambiguation.
