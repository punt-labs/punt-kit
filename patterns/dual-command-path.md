# Dual Command Path

## Problem

Claude Code plugins namespace their commands under the plugin name (`/biff:who`,
`/biff:finger`). Users expect short, memorable commands (`/who`, `/finger`). The
namespaced form is correct for disambiguation but hostile to daily use.

## Forces

- Marketplace plugins provide namespaced commands (`/<name>:<command>`)
  automatically from the plugin's `commands/` directory.
- User commands in `~/.claude/commands/` are top-level (`/<command>`).
- Both locations load the same `.md` file format.
- Some users may disable the plugin but still want the MCP server and top-level
  commands.
- Command filenames must not collide with other plugins' commands in the global
  namespace.

## Solution

Deploy the same command `.md` files to both locations:

1. **Plugin commands** — `${CLAUDE_PLUGIN_ROOT}/commands/*.md` — namespaced as
   `/<name>:<command>`. Provided automatically by the marketplace.
2. **User commands** — `~/.claude/commands/*.md` — top-level as `/<command>`.
   Deployed by the SessionStart hook.

The SessionStart hook copies prod command files (excluding `*-dev.md`) from the
plugin's commands directory to the user's commands directory.

```text
~/.claude/plugins/cache/<marketplace>/<repo>/
└── commands/who.md                          → /biff:who (namespaced)

~/.claude/
└── commands/who.md                          → /who (top-level)
```

### Uninstall

Only remove files whose names match the bundled command filenames. Do not touch
non-owned files that may exist in `~/.claude/commands/`.

## Consequences

- Users get both `/<command>` and `/<name>:<command>` — short form for daily
  use, namespaced form when disambiguation is needed.
- The plugin can be disabled without losing top-level commands (MCP server +
  user commands still work).
- If another plugin deploys a command with the same filename to
  `~/.claude/commands/`, the last installer wins. Choose distinctive filenames.
- The doctor command should check user commands as informational (not required)
  since the namespaced plugin commands are the fallback.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — Dual Command Path deployment
  happens after Phase 2, triggered by the SessionStart hook on next restart.
- [Copy, Not Symlink](copy-not-symlink.md) — The mechanism used to deploy
  files from the plugin cache to the user command directory.
- [Doctor Checks](doctor-checks.md) — User commands are checked as
  informational (not required) since namespaced plugin commands are the fallback.

## Known Uses

- **Biff** — SessionStart hook (`hooks/session-start.sh`) deploys `who.md`,
  `finger.md`, `write.md`, `read.md`, `plan.md`, `mesg.md`, `tty.md` to
  `~/.claude/commands/`. Users type `/who` daily; `/biff:who` exists for
  disambiguation.
- **TTS** — Same pattern for `notify.md`, `say.md`, `recap.md`, `speak.md`,
  `voice.md`.
