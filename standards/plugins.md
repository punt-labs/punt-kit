# Plugin Standards

Standards for Claude Code plugins across all Punt Labs projects.

---

## plugin.json

Every Claude Code plugin must have a `plugin.json` with at minimum:

```json
{
  "name": "<project-name>",
  "description": "<one-line description>",
  "version": "<semver>",
  "author": {
    "name": "<author>",
    "email": "<email>",
    "organization": "Punt Labs"
  }
}
```

The `version` field is required. Omitting it is a defect.

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

## Output Suppression

Any project that uses MCP tools inside Claude Code must have a **PostToolUse hook** that suppresses raw MCP tool output. Without this, JSON payloads from tool calls pollute the conversation.

Pattern: `biff/hooks/suppress-output.sh`, `claude-dungeon/hooks/hooks.json`.

The hook should match the project's MCP tool name pattern (e.g., `mcp__biff__*`, `mcp__plugin_dungeon_game__*`).

---

## Command Tool Restrictions

Commands that invoke external tools (compilers, linters, test runners) should declare `allowed-tools` in their frontmatter to restrict what Claude can execute. This prevents unintended side effects.

Pattern: Z Spec commands restrict Bash to `fuzz:*` and `probcli:*` calls only.
