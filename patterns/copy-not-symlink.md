# Copy, Not Symlink

## Problem

Claude Code marketplace plugins provide namespaced commands (`/biff:who`) but
users want top-level shortcuts (`/who`). The marketplace cache is read-only and
managed by `claude plugin install` — plugins cannot write to it. Top-level
commands must be deployed to `~/.claude/commands/`, which is outside the plugin's
directory.

## Forces

- The marketplace cache (`~/.claude/plugins/cache/...`) is a git clone managed
  by Claude Code. Plugins should not modify it.
- User commands in `~/.claude/commands/` are top-level (`/<command>`).
- Symlinks from `~/.claude/commands/` into the cache would break if the cache is
  updated, moved, or cleaned.
- The deployment must be idempotent — safe to re-run on every session start.

## Solution

The SessionStart hook copies command `.md` files from the plugin's commands
directory (`${CLAUDE_PLUGIN_ROOT}/commands/`) to `~/.claude/commands/`. Files
that already exist are skipped (the user may have customized them).

```bash
# In hooks/session-start.sh
COMMANDS_DIR="$HOME/.claude/commands"
mkdir -p "$COMMANDS_DIR"

for cmd in "${CLAUDE_PLUGIN_ROOT}/commands/"*.md; do
  name="$(basename "$cmd")"
  # Skip dev commands — only deploy prod commands
  case "$name" in *-dev.md) continue ;; esac
  target="$COMMANDS_DIR/$name"
  [ -f "$target" ] || cp "$cmd" "$target"
done
```

Copies are self-contained and survive cache updates, reinstalls, and plugin
removal. The plugin is the source of truth — hand-edits to deployed commands
are preserved until the user deletes them and restarts (triggering re-copy).

## Consequences

- Top-level commands survive marketplace cache operations.
- No symlink management, no filesystem coupling between cache and user dir.
- SessionStart is the deployment mechanism — commands activate on restart.
- First install requires two restarts: install → restart 1 (hook runs, copies
  commands) → restart 2 (commands active).
- The `uninstall` subcommand must clean up deployed commands by matching
  filenames against the plugin's bundled command list.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — Copy, Not Symlink is the
  deployment mechanism that runs after Phase 2 (plugin install), triggered by
  the SessionStart hook.
- [Dual Command Path](dual-command-path.md) — Explains why commands exist in
  two locations (namespaced in plugin, top-level in user dir).

## Known Uses

- **Biff** — `hooks/session-start.sh` copies `who.md`, `finger.md`, `write.md`,
  etc. to `~/.claude/commands/`. Skips `*-dev.md` files.
- **TTS** — Same pattern for `notify.md`, `say.md`, `recap.md`, etc.
- **punt-kit** — Same pattern for `audit.md`, `init.md`, etc.
