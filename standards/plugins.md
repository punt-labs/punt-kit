# Plugin Standards

Standards for Claude Code plugins across all Punt Labs projects.

---

## Dev/Prod Namespace Isolation

Plugin authors working inside their plugin's source repo need to test local
changes without waiting for a marketplace publish cycle. The `--plugin-dir`
flag loads a plugin directly from a local directory for the current session,
alongside any marketplace-installed plugins.

### How it works

The working tree's `plugin.json` uses `name: "<project>-dev"` (e.g.
`punt-dev`). The marketplace uses `name: "<project>"` (e.g. `punt`). Because
the names differ, both load simultaneously — developers see production commands
and dev commands side by side.

```bash
# Developer launch (from the plugin's repo root)
claude --plugin-dir .
```

This gives you:

| Source | Commands | What they run |
|--------|----------|---------------|
| Marketplace `punt` | `/punt init`, `/punt audit` | Installed CLI |
| Local `punt-dev` | `/punt-dev init-dev`, `/punt-dev audit-dev` | `uv run` against working tree |

The `-dev` commands use `uv run --directory ${CLAUDE_PLUGIN_ROOT}` to execute
the working tree code directly, bypassing the installed CLI. For editable-install
projects (tts, biff), the installed binary already points to the working tree, so
dev commands can use the binary name directly. The key invariant is that dev
commands always execute the working tree.

### Namespace scope

The plugin name prefixes **everything**: commands, MCP server tools, skills,
agents, hooks. Using a `-dev` suffix at the plugin name level isolates all
extension points automatically.

| Layer | Production | Development |
|-------|-----------|-------------|
| Commands | `/punt init` | `/punt-dev init-dev` |
| MCP tools | `mcp__plugin_punt_*` | `mcp__plugin_punt_dev_*` |
| Skills | `punt:reconcile` | `punt-dev:reconcile-dev` |

### Release flow

At release time, `scripts/release-plugin.sh` swaps `plugin.json` to
`name: "punt"` and removes `-dev` command files from the tagged commit.
The marketplace entry's `source.ref` must be pinned to the release tag (see
DES-003 in DESIGN.md) — without it, `claude plugin install` clones HEAD, not
the tag. Then `scripts/restore-dev-plugin.sh` restores dev state on main.

### Release flow for pure plugins

Pure plugins (dungeon, prfaq, z-spec) have no PyPI artifact and may lack
`scripts/release-plugin.sh`. They still need properly tagged releases for the
marketplace to install them.

The release sequence is: swap name to prod → commit → tag → restore dev name →
commit → push. See DES-007 in DESIGN.md for the full rationale.

**Critical**: the marketplace `source.ref` must point to an existing tag where
`plugin.json` has the prod name. If the tag doesn't exist or has the dev name,
`claude plugin install` fails silently.

### Audit enforcement

`punt audit` checks that every prod command (`*.md` excluding `*-dev.md`) has a
corresponding `-dev` variant.

---

## plugin.json

Every Claude Code plugin must have `.claude-plugin/plugin.json` at the repo
root with at minimum:

```json
{
  "name": "<project-name>",
  "description": "<one-line description>",
  "version": "<semver>",
  "author": {
    "name": "Punt Labs",
    "email": "hello@punt-labs.com"
  }
}
```

The `version` field is required. Omitting it is a defect.

Use the **org name** (`"Punt Labs"`) as the author, not a personal name. This
establishes consistent org identity in the marketplace catalog.

---

## MCP Server Declaration

Plugins that expose MCP tools must declare them in `plugin.json` using the
`mcpServers` field:

```json
{
  "mcpServers": {
    "<server-name>": {
      "type": "stdio",
      "command": "<cli-binary>",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

The `"command"` field must reference the installed CLI binary name (e.g.
`"biff"`, `"tts"`), not `uv run`. Plugin consumers install via the marketplace
and do not have a uv project directory — `uv run` would fail.

**Do not use `.mcp.json` for plugin MCP servers.** The marketplace cache is a
full git clone — any `.mcp.json` committed to the repo will be loaded as a
plugin MCP server, even if it was meant for local development.

`.mcp.json` must be in `.gitignore` for every plugin repo. It is for
project-local MCP servers only, not plugin distribution.

### MCP tool naming

Tool names are deterministic based on registration method:

| Method | Pattern | Example |
|--------|---------|---------|
| Plugin `mcpServers` | `mcp__plugin_{plugin}_{server}__{tool}` | `mcp__plugin_biff_tty__who` |
| `claude mcp add` | `mcp__{server}__{tool}` | `mcp__quarry__search` |

Choose a **server key that adds meaning** rather than repeating the plugin name.
For example, biff uses `tty` (the MCP server is the terminal interface), and
dungeon uses `grimoire` (the game state engine). All command files, hook
matchers, and permission entries must use the full prefix.

---

## Extension Point Selection

Choose the right extension point for each capability:

| Extension Point | When to Use |
|----------------|-------------|
| **Skill** | Complex multi-phase workflows with branching logic. The skill defines *how Claude should behave* for the duration of a task. Use sparingly — most projects need zero or one. |
| **Command** | A discrete, user-invocable operation mapped to a slash command. One command per slash command. Self-contained. |
| **Agent** | A specialized sub-task that a skill or command delegates to. Has a distinct role, model preference, and tool restrictions. Use when the sub-task benefits from isolation or a different model. |
| **Hook** | Event-driven automation triggered by tool calls or lifecycle events. Use for output suppression, validation, or side effects. |
| **MCP Server** | Exposes tools that Claude (or any MCP client) can call. Use when the project has deterministic operations (I/O, computation, state management) that should not be prompt-driven. |

---

## Required Hooks

### SessionStart hook

Every marketplace plugin must have a SessionStart hook that handles first-run
setup idempotently. This is needed because the marketplace only caches the repo;
it does not run post-install scripts.

The SessionStart hook should:

1. **Deploy top-level commands** — Copy from `${CLAUDE_PLUGIN_ROOT}/commands/`
   to `~/.claude/commands/`. **Update files that have changed** — compare with
   `diff -q` and overwrite when content differs. Never skip-if-exists; stale
   deployed commands persist across releases and silently break the plugin.
   Marketplace plugins only provide namespaced commands (`biff:who`); top-level
   commands (`/who`) require deployment to the user's command directory.

   ```bash
   # CORRECT: always update changed commands
   mkdir -p "$COMMANDS_DIR"
   if [[ ! -f "$dest" ]] || ! diff -q "$cmd_file" "$dest" >/dev/null 2>&1; then
     cp "$cmd_file" "$dest"
   fi

   # WRONG: skip-if-exists leaves stale commands forever
   if [[ ! -f "$dest" ]]; then
     cp "$cmd_file" "$dest"
   fi
   ```

2. **Auto-allow MCP tool permissions** — Add the plugin's tool pattern (e.g.,
   `mcp__plugin_biff_tty__*`) to `permissions.allow` in
   `~/.claude/settings.json` via jq. Without this, users get permission prompts
   on every tool call.

3. **Run any first-time setup** — npm install for Node.js MCP servers, statusline
   installation, dependency verification.

4. **Notify Claude** — Output JSON with `hookSpecificOutput` describing what was
   set up. Silent on subsequent sessions when everything is already configured.

Pattern: `biff/hooks/session-start.sh`, `dungeon/hooks/session-start.sh`,
`vox/hooks/session-start.sh`.

**Restart penalty**: SessionStart runs when Claude Code starts, but on first
install the hook hasn't run yet. Deployed commands activate on the next restart.
Users need two restarts: install → restart 1 (hook runs) → restart 2 (commands
active). No workaround exists in the current plugin system.

### PostToolUse hook (output suppression)

Any project that uses MCP tools inside Claude Code must have a **PostToolUse
hook** that suppresses raw MCP tool output. Without this, JSON payloads from
tool calls pollute the conversation.

The hook matcher must use the full plugin tool prefix and cover both dev and
prod names:

```json
{
  "matcher": "mcp__plugin_biff(_dev)?_tty__.*",
  "hooks": [{
    "type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/suppress-output.sh"
  }]
}
```

Pattern: `biff/hooks/suppress-output.sh`, `dungeon/hooks/suppress-output.sh`,
`vox/hooks/suppress-output.sh`.

**Handler completeness:** When adding a new MCP tool, add a corresponding
handler to `suppress-output.sh`. Missing handlers cause raw JSON to leak into
the conversation panel. Every MCP tool must have a panel format — no exceptions.
See `vox` v1.1.1 for the bug and fix.

---

## Command Deployment

Marketplace plugins provide namespaced commands automatically (`biff:who`), but
top-level commands (`/who`) must be deployed to `~/.claude/commands/` by the
SessionStart hook. This section defines how that deployment works.

### Lifecycle

1. **First install**: SessionStart hook copies command files from
   `${CLAUDE_PLUGIN_ROOT}/commands/` to `~/.claude/commands/`.
2. **Plugin update**: SessionStart hook detects content differences and
   overwrites stale files. Commands are always current after one restart.
3. **Plugin uninstall**: No automatic cleanup — stale files remain. The
   uninstaller (if present) should remove deployed commands.

### Deployment logic

The canonical pattern for command deployment in a SessionStart hook:

```bash
COMMANDS_DIR="$HOME/.claude/commands"
DEPLOYED=()
for cmd_file in "$PLUGIN_ROOT/commands/"*.md; do
  name="$(basename "$cmd_file")"
  [[ "$name" == *-dev.md ]] && continue
  dest="$COMMANDS_DIR/$name"
  mkdir -p "$COMMANDS_DIR"
  if [[ ! -f "$dest" ]] || ! diff -q "$cmd_file" "$dest" >/dev/null 2>&1; then
    cp "$cmd_file" "$dest"
    DEPLOYED+=("/${name%.md}")
  fi
done
```

**Key rules:**

- **Always diff before skipping.** `diff -q` compares content; copy when
  different. Never use bare `[[ ! -f "$dest" ]]` — this leaves stale commands
  forever across plugin upgrades.
- **Skip `-dev.md` files.** Dev commands use plugin namespace
  (`vox-dev:say-dev`); they are never deployed to the global commands directory.
- **Skip deployment in dev mode.** When `plugin.json` has a `-dev` name, the
  prod plugin handles top-level commands.
- **Report what changed.** Collect deployed command names and include them in
  the `hookSpecificOutput` message so the user knows what was updated.

### Why not skip-if-exists

The skip-if-exists pattern (`if [[ ! -f "$dest" ]]`) was the original
implementation. It broke silently: commands deployed on first install persisted
unchanged across every subsequent release. Users accumulated stale files with
old `allowed-tools`, old MCP tool names, and old implementation logic. The bug
was invisible to developers because dev mode skips deployment entirely.

See `vox/DESIGN.md` DES-016 for the full incident record.

---

## Plugin Repo Gitignore Checklist

The marketplace cache is a full git clone. Everything committed to the repo
becomes part of the plugin. Add these to `.gitignore`:

```gitignore
# MCP (project-local, not part of plugin distribution)
.mcp.json

# Node.js dependencies (SessionStart hook installs these)
node_modules/

# Python artifacts
__pycache__/
*.egg-info/
.venv/
```

---

## Plugin Installer Permissions

The SessionStart hook handles MCP tool wildcards (section above). Plugins that
use Bash commands, file writes/edits, or web access in their commands and
skills need additional permissions injected by the **installer** (not the
SessionStart hook — the installer runs once with user attention, making it the
right place for explicit permission setup).

### Requirements

1. **Every installer must include a permission injection step.** Define the
   plugin's permission rules as a JSON array and merge them into
   `~/.claude/settings.json` using the order-preserving `jq` pattern from
   [permissions.md § 6](permissions.md#6-plugin-distributed-permissions).

2. **Every uninstaller must remove injected permissions.** Use the same JSON
   array to selectively remove only the plugin's rules.

3. **Rules must be pattern-specific.** Include the plugin name or a
   domain-specific identifier in every Write/Edit pattern. See
   [permissions.md § 6](permissions.md#6-plugin-distributed-permissions) for
   examples.

4. **Dangerous operations stay at the prompt tier.** Never auto-allow `curl`,
   `rm`, broad file patterns, or commands with side effects.

Pattern: `prfaq/install.sh` (Step 5: Configure permissions).

---

## Command and Skill Frontmatter

### allowed-tools

Every command and skill that invokes tools must declare `allowed-tools` in its
YAML frontmatter. This restricts what Claude can execute when running the
command and serves as documentation of the command's tool requirements.

```yaml
---
description: Run a simulated review meeting
allowed-tools: Bash(mkdir -p meetings), Read, Write, Glob, Grep
---
```

List only the tools the command actually uses. Do not include tools the command
does not need.

**MCP-first commands:** Commands that set config, query state, or trigger
operations should list MCP tools in `allowed-tools` — not `Bash`, `Read`, or
`Write`. The model calling an MCP tool is faster than calling Bash → CLI
(see [CLI standards § Call path performance](cli.md#call-path-performance))
and eliminates file-format coupling.

```yaml
# CORRECT: MCP-first (vox /vox command)
allowed-tools: ["mcp__plugin_vox_mic__notify", "mcp__plugin_vox_mic__who"]

# WRONG: Bash for operations that have MCP equivalents
allowed-tools: ["Bash"]
```

Pattern: `vox/commands/*.md` (MCP-first), `prfaq/commands/*.md`,
`z-spec/commands/*.md`.
