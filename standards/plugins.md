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
   to `~/.claude/commands/`. Skip files that already exist. Marketplace plugins
   only provide namespaced commands (`biff:who`); top-level commands (`/who`)
   require deployment to the user's command directory.

2. **Auto-allow MCP tool permissions** — Add the plugin's tool pattern (e.g.,
   `mcp__plugin_biff_tty__*`) to `permissions.allow` in
   `~/.claude/settings.json` via jq. Without this, users get permission prompts
   on every tool call.

3. **Run any first-time setup** — npm install for Node.js MCP servers, statusline
   installation, dependency verification.

4. **Notify Claude** — Output JSON with `hookSpecificOutput` describing what was
   set up. Silent on subsequent sessions when everything is already configured.

Pattern: `biff/hooks/session-start.sh`, `dungeon/hooks/session-start.sh`.

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

Pattern: `biff/hooks/suppress-output.sh`, `dungeon/hooks/suppress-output.sh`.

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

## Command Tool Restrictions

Commands that invoke external tools (compilers, linters, test runners) should declare `allowed-tools` in their frontmatter to restrict what Claude can execute. This prevents unintended side effects.

Pattern: Z Spec commands restrict Bash to `fuzz:*` and `probcli:*` calls only.
