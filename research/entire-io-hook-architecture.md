# Entire.io Hook Architecture — Research Notes

**Date:** 2026-02-24
**Source:** langlearn-tts project installation, entireio/cli GitHub README, web research
**Purpose:** Understand how Entire.io hooks into Claude Code and git to inform biff's hook integration architecture

## What Entire.io Does

Entire.io captures the *reasoning* behind AI-generated code. Git tracks the "what" (final code). Entire tracks the "why" (the prompts, decisions, and context that produced it). Founded by former GitHub CEO Thomas Dohmke, launched February 2026 with $60M.

Key concepts:
- **Checkpoints** — save points within a session, stored on a separate git branch
- **Sessions** — one AI coding session, tied to commits
- **Rewind** — restore project state to any checkpoint, keeping good progress

## Installation Footprint

`entire enable` installs hooks in two systems simultaneously:

### 1. Claude Code Hooks (`.claude/settings.json`)

Seven hooks across six events:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{ "type": "command", "command": "entire hooks claude-code session-start" }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{ "type": "command", "command": "entire hooks claude-code session-end" }]
    }],
    "UserPromptSubmit": [{
      "matcher": "",
      "hooks": [{ "type": "command", "command": "entire hooks claude-code user-prompt-submit" }]
    }],
    "Stop": [{
      "matcher": "",
      "hooks": [{ "type": "command", "command": "entire hooks claude-code stop" }]
    }],
    "PreToolUse": [{
      "matcher": "Task",
      "hooks": [{ "type": "command", "command": "entire hooks claude-code pre-task" }]
    }],
    "PostToolUse": [
      {
        "matcher": "Task",
        "hooks": [{ "type": "command", "command": "entire hooks claude-code post-task" }]
      },
      {
        "matcher": "TodoWrite",
        "hooks": [{ "type": "command", "command": "entire hooks claude-code post-todo" }]
      }
    ]
  },
  "permissions": {
    "deny": ["Read(./.entire/metadata/**)"]
  }
}
```

### 2. Git Hooks (`.git/hooks/`)

Four hooks on the git lifecycle:

| Hook | Command | Purpose |
|------|---------|---------|
| `prepare-commit-msg` | `entire hooks git prepare-commit-msg "$1" "$2"` | Adds `Entire-Checkpoint` trailer to commit messages |
| `commit-msg` | `entire hooks git commit-msg "$1"` | Strips trailer if no user content (allows aborting empty commits). **Fail-closed** (`\|\| exit 1`) |
| `post-commit` | `entire hooks git post-commit` | Condenses session data when commit has checkpoint trailer. **Fail-open** (`\|\| true`) |
| `pre-push` | `entire hooks git pre-push "$1"` | Pushes session logs to `entire/checkpoints/v1` alongside user's push. **Fail-open** (`\|\| true`) |

### 3. Local Data (`.entire/`)

```
.entire/
  .gitignore          # Excludes tmp/, settings.local.json, metadata/, logs/
  logs/               # Debug logs
  metadata/           # Per-session data (gitignored)
    <uuid>/
      context.md      # Structured session summary
      full.jsonl      # Every event streamed
      prompt.txt      # User's last prompt
      summary.txt     # AI-generated summary
  tmp/                # Working storage
```

### 4. Shadow Branch

`entire/checkpoints/v1` — stores all session metadata separate from code. Pushed to remote alongside user pushes via the pre-push git hook.

## Design Patterns Worth Learning From

### Pattern 1: Dual-Layer Capture

Entire hooks into **both** Claude Code lifecycle and git lifecycle. This gives complete coverage:
- Claude Code hooks capture *agent behavior* (what the AI did and why)
- Git hooks capture *code lifecycle* (when commits happen, when pushes happen)

Neither layer alone is sufficient. Claude Code hooks miss manual git operations. Git hooks miss agent reasoning.

### Pattern 2: Event Selection Strategy

Entire is selective about which events it hooks:

**Broad matchers (all occurrences):**
- SessionStart, SessionEnd — session boundaries
- UserPromptSubmit — every human message
- Stop — every agent turn completion

**Narrow matchers (specific tools):**
- PreToolUse/PostToolUse on `Task` — subagent lifecycle only
- PostToolUse on `TodoWrite` — work planning changes only

**Deliberately unhoooked:**
- Edit, Write, Bash, Read — too noisy for session recording; file changes are captured by git diff instead
- Notification, SubagentStart, PreCompact — low-value for provenance

### Pattern 3: Fail-Open on Observation, Fail-Closed on Mutation

Git hooks that *observe* (post-commit, pre-push) use `|| true` — if Entire crashes, git still works. The commit-msg hook, which *mutates* the commit message, uses `|| exit 1` — if Entire can't process the message, the commit aborts rather than producing a malformed commit.

### Pattern 4: Deny Self-Reference

```json
"permissions": { "deny": ["Read(./.entire/metadata/**)"]}
```

Prevents the AI from reading its own session recordings. Avoids recursive self-reference and context pollution.

### Pattern 5: CLI as Hook Dispatcher

All hooks call `entire hooks <agent> <event>` — the CLI binary is the single entry point. This means:
- Hook scripts don't contain logic — they're one-liners
- All logic lives in the compiled CLI, versioned and testable
- Updating the CLI updates all hook behavior without reinstalling hooks
- The hook dispatcher pattern works across agents (claude-code, gemini, opencode)

### Pattern 6: Settings Files — Shared vs. Local

```
.entire/settings.json        # Committed — team-shared strategy
.entire/settings.local.json  # Gitignored — personal overrides
```

Mirrors Claude Code's own `settings.json` / `settings.local.json` split.

## Complete Claude Code Hook Events (for reference)

As of Claude Code 2.1.50, 16 hook events exist:

| Event | When | Matcher | Can Block? |
|-------|------|---------|-----------|
| SessionStart | Session begins or resumes | How started: `startup`, `resume`, `clear`, `compact` | No |
| UserPromptSubmit | User submits prompt | No matcher | Yes (exit 2 erases prompt) |
| PreToolUse | Before tool executes | Tool name | Yes (blocks tool call) |
| PermissionRequest | Permission dialog appears | Tool name | Yes (denies permission) |
| PostToolUse | After tool succeeds | Tool name | No (tool already ran) |
| PostToolUseFailure | After tool fails | Tool name | No |
| Notification | Notification sent | Type: `permission_prompt`, `idle_prompt`, etc. | No |
| SubagentStart | Subagent spawned | Agent type | No |
| SubagentStop | Subagent finishes | Agent type | Yes (prevents stop) |
| Stop | Claude finishes responding | No matcher | Yes (prevents stop, continues) |
| TeammateIdle | Agent team mate about to idle | No matcher | Yes (keeps working) |
| TaskCompleted | Task marked complete | No matcher | Yes (prevents completion) |
| ConfigChange | Config file changes | Config source | Yes |
| WorktreeCreate | Worktree being created | No matcher | Yes |
| WorktreeRemove | Worktree being removed | No matcher | No |
| PreCompact | Before context compaction | `manual`, `auto` | No |
| SessionEnd | Session terminates | Why: `clear`, `logout`, `prompt_input_exit`, etc. | No |

### Output Capabilities

All hooks can output:
- `additionalContext` — text injected as context for Claude
- `updatedMCPToolOutput` — replaces tool result panel text (PostToolUse only)
- `permissionDecision` — allow/deny/ask (PreToolUse, PermissionRequest)
- `continue: false` — stops Claude entirely
- `systemMessage` — warning shown to user

SessionStart and UserPromptSubmit stdout is automatically added as context for Claude.

## Implications for Other Tools

Any tool that wants deep integration with Claude Code sessions should consider:

1. **Hook into session lifecycle** (SessionStart/SessionEnd) for setup/teardown
2. **Hook into UserPromptSubmit** if you need to know what the user is working on
3. **Hook into Stop** if you need to know when the agent completes a turn
4. **Use git hooks for reliable, agent-independent triggers** (post-commit, post-checkout, pre-push)
5. **Keep hook scripts as thin dispatchers** — one-liner calls to your CLI
6. **Fail-open for observation, fail-closed for mutation**
7. **Deny self-reference** if you store data the agent could read

## Sources

- [Entire.io CLI — GitHub](https://github.com/entireio/cli)
- [Entire.io launches with $60M — SiliconANGLE](https://siliconangle.com/2026/02/10/entire-launches-60m-build-ai-focused-code-management-platform/)
- [AI-Native Version Control — blog.ni18.in](https://blog.ni18.in/ai-native-version-control-entire-io/)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Automate workflows with hooks — Guide](https://code.claude.com/docs/en/hooks-guide)
- Observed installation: `/Users/jfreeman/Coding/punt-labs/langlearn-tts/.claude/settings.json`
