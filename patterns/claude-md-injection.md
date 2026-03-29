# CLAUDE.md Injection

How tools inject capabilities sections into `~/.claude/CLAUDE.md` during
install so agents know what tools are available.

---

## Problem

An agent starts a session with no knowledge of which tools are installed
beyond what MCP servers expose. Plugin skill descriptions are per-invocation
and only surface when a skill is triggered. The agent needs persistent,
always-present guidance about available slash commands, auto-behaviors, and
usage tips — especially for tools that work across all projects.

## Forces

- **Global scope.** `~/.claude/CLAUDE.md` is loaded into every session,
  every project. Tool guidance placed here is always available.
- **Idempotent.** Running install twice must not duplicate the section.
- **Collision-free.** Multiple tools inject into the same file. Sections
  must not interfere with each other.
- **Survives reinstall.** The section must persist across tool upgrades
  and reinstalls. Marker comments enable detection and update.
- **Concise.** The file grows with each tool. Each section should be
  10-15 lines — enough for discoverability, not a full manual.
- **Complementary.** CLAUDE.md injection is for always-on awareness.
  Ethos `session_context` is for identity-scoped instructions. Plugin
  skills are for per-invocation behavior. Each mechanism has its role.

## Solution

### Marker comments

Each tool's section is wrapped in HTML comments that serve as idempotency
markers:

```markdown
<!-- tool:capabilities -->
# Tool Name

Content here...
<!-- /tool:capabilities -->
```

The opening marker (`<!-- tool:capabilities -->`) is checked before
injection. If present, the section is skipped. If absent, the section
is appended.

### Append-or-skip logic

```python
_MARKER = "<!-- quarry:capabilities -->"

def _inject_claude_md() -> str:
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if _MARKER in content:
            return f"{claude_md} already has section"
        with claude_md.open("a", encoding="utf-8") as f:
            f.write(SECTION_CONTENT)
    else:
        claude_md.write_text(SECTION_CONTENT.lstrip(), encoding="utf-8")

    return f"Appended section to {claude_md}"
```

### Section content

Keep to 10-15 lines. Include:

1. **Tool name** as a heading
2. **One-line description** of what the tool does
3. **Slash commands** available (bulleted list)
4. **Auto-behaviors** the user should know about (e.g., "auto-indexes
   your project on session start")
5. **Key tip** for effective use (e.g., "natural language queries work
   best")

Do not include: full API reference, configuration instructions, or
troubleshooting. Those belong in the tool's own docs.

### Where it runs

CLAUDE.md injection runs during `<tool> install` as a numbered step,
typically after MCP client configuration and before verification:

```text
[6/7] Injecting quarry context into CLAUDE.md...
  ✓ Appended quarry section to /Users/alice/.claude/CLAUDE.md
```

## Consequences

- **Agents discover tools.** The agent knows about `/find`, `/ingest`,
  `/remember` without the user having to explain.
- **Single file grows.** Each tool adds 10-15 lines. With 5 tools,
  the file grows by ~75 lines. This is manageable.
- **No update mechanism.** If the section content changes between
  versions, the old section persists. Tools should use stable content
  that doesn't need frequent updates. A future improvement could
  detect and replace outdated sections using the closing marker.
- **Global, not per-project.** This is appropriate for tools that
  work everywhere (quarry, biff). Project-specific tools should use
  per-project `CLAUDE.md` files instead.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — CLAUDE.md injection is
  Phase 2a
- [Ethos Extension Setup](ethos-ext-setup.md) — complementary mechanism
  for identity-scoped session context
- [Prior-Context Priming](prior-context-priming.md) — explains why
  prior-context guidance (like CLAUDE.md) is more effective than
  same-turn instructions

## Known Uses

- **quarry v1.8.0** — `quarry install` step 6/7 appends a capabilities
  section with slash commands, research agent, and auto-behaviors.
