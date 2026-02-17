# Two-Channel Display

## Problem

MCP tool output displayed in Claude Code's tool-result panel gets truncated when it exceeds a few lines. The user sees a "Control-O for more" expansion prompt instead of the actual data. This is unacceptable for data commands — users should see their `/who` table or `/read` inbox immediately.

## Forces

- `updatedMCPToolOutput` controls what appears in the tool-result panel, but Claude Code truncates multi-line content behind an expansion prompt.
- The model can emit text to the conversation, but without panel context the user has no compact summary.
- Some commands (confirmations like "Sent to @kai") need only the panel — no model output desired.
- Other commands (data tables, inbox contents) need the model to emit the full output.

## Solution

Split MCP tool output into two channels via the PostToolUse hook:

1. **`updatedMCPToolOutput`** — A compact summary shown in the tool-result panel. One line, never truncated. Examples: "3 online", "Sent to @kai", "2 unread messages".

2. **`additionalContext`** — The full output passed to the model as context. The skill prompt instructs the model to emit this verbatim into the conversation.

### Silent commands (confirmations)

Set `updatedMCPToolOutput` to the full result. Do not set `additionalContext`. The skill prompt says "Do not send any text after the tool call."

### Data commands (tables, lists)

Set `updatedMCPToolOutput` to a one-line summary. Set `additionalContext` to the full data. The skill prompt says "Emit the tool output exactly as returned."

```
PostToolUse Hook
├── Silent (/write, /plan, /mesg)
│   updatedMCPToolOutput = full result     → panel shows all
│   additionalContext    = (none)          → model stays silent
│
└── Data (/who, /finger, /read)
    updatedMCPToolOutput = summary         → panel: "3 online"
    additionalContext    = full table      → model emits it
```

## Consequences

- Data commands display immediately without user interaction.
- Silent commands produce no conversation noise.
- The hook must classify each tool as silent or data — this is a per-tool decision.
- The skill prompt for each command must match the hook's channel decision (tell the model to be silent or to emit).

## Known Uses

- **Biff** — `/who`, `/finger`, `/read` use the data channel; `/write`, `/plan`, `/mesg` use the silent channel.
- **Dungeon** — PostToolUse hook suppresses all MCP output; the skill prompt drives all narration.
