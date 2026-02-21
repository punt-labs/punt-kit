# Plugin Standards

Standards for Claude Code plugins across all Punt Labs projects.

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

The hook matcher must use the full plugin tool prefix:

```json
{
  "matcher": "mcp__plugin_biff_tty__.*",
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
