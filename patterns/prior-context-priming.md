# Prior-Context Priming

## Problem

Skill prompts that arrive at the same turn as a tool call are understood by the model but not reliably followed. The model can repeat the formatting instructions verbatim when asked, yet still reformats output (adds markdown tables, code fence boxes, strips unicode characters). Iterating on prompt wording does not fix this.

## Forces

- Claude Code delivers skill prompts and tool results in the same conversation turn.
- The model processes same-turn instructions but treats them as suggestions rather than constraints for formatting behavior.
- Formatting guidance delivered in a **prior** conversation turn (before the tool call) is followed reliably.
- There is no API to inject context into a prior turn after the session has started.

## Solution

Use the MCP server's `instructions` field to deliver formatting and behavioral guidance. The `instructions` field is set during `FastMCP(instructions=...)` (Python) or `new McpServer({...}, { instructions: "..." })` (Node.js). Claude Code reads it during the MCP `initialize` handshake at session start and injects it into the system context — prior to any tool calls.

```python
# Python (FastMCP)
app = FastMCP(
    "my-server",
    instructions="Output formatting: emit tables with unicode characters. "
    "Do not wrap output in code fences or markdown tables.",
)
```

```javascript
// Node.js (@modelcontextprotocol/sdk)
const server = new McpServer(
    { name: "my-server", version: "1.0.0" },
    { instructions: "Output formatting: ..." }
);
```

The skill prompt reinforces the same guidance on the same turn. The `instructions` field primes on session start. Both are needed — the `instructions` field ensures the first tool call works correctly; the skill prompt reinforces on subsequent calls.

## Consequences

- Formatting guidance works on the first command in a fresh session.
- The `instructions` field is limited in size — keep it concise (formatting rules, not full documentation).
- The skill prompt and `instructions` field must agree — contradictions cause unpredictable behavior.
- This pattern applies to any behavioral guidance the model must follow when handling tool output, not just formatting.

## Related Patterns

- [Two-Channel Display](two-channel-display.md) — The pattern that creates the need for Prior-Context Priming. Data commands route full output through `additionalContext` and instruct the model to emit it verbatim — formatting guidance must be primed in prior context for this to work.

## Known Uses

- **Biff** — MCP `instructions` field contains output formatting rules (unicode preservation, no code fences, verbatim emission). Discovered after 5 iterations of prompt-only approaches failed. Validated in fresh sessions.

## Discovery

| Attempt | Mechanism | Outcome |
|---------|-----------|---------|
| v1-v4 | Skill prompt wording variations | Model reformats output despite understanding instructions |
| **v5** | **MCP `instructions` field** | **Works — verbatim output in fresh sessions** |

The delivery mechanism (same-turn vs prior-context) was the problem, not the prompt wording.
