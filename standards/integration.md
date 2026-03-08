# Integration Standards (DRAFT)

> **Status: DRAFT** — This standard is under development. Conventions described
> here are directional but not yet enforced by quality gates or audits.

How Punt Labs tools discover, communicate with, and coordinate each other
inside a Claude Code session — without hard dependencies.

---

## Design Principle

**No tool requires another tool.** Every integration degrades gracefully. A
tool that finds a peer enriches its behavior; a tool that doesn't find a peer
works fine alone. This is achieved through a tiered protocol where each layer
adds capability without creating coupling.

---

## Scope: Peer Integrations vs. Hard Dependencies

This standard covers **peer integrations** — optional relationships where a
tool enriches its behavior when a peer is present but works fine alone. It does
**not** cover hard library dependencies managed by pip/uv.

| Relationship | Example | Managed by |
|-------------|---------|------------|
| Hard dependency | langlearn-tts imports vox | `pyproject.toml` — pip enforces it, tool cannot function without it |
| Peer integration | langlearn discovers langlearn-tts via MCP | This standard — tool degrades gracefully without it |
| Dev tool | z-spec used during koch-trainer development | Neither — a methodology choice, not a runtime relationship |

**Rule**: If removing the dependency causes a Python `ImportError`, it's a hard
dependency (manage with pyproject.toml). If removing it causes degraded but
functional behavior, it's a peer integration (document in this standard). If
removing it only affects development process, it's a dev tool and doesn't
belong here.

---

## Tiered Protocol

Integration is organized into six layers across two tiers.

### Universal Tier (L0–L3)

Any tool — ours or external — can participate at these layers using only file
conventions, shell commands, and Claude Code hooks. No shared library required.

#### L0: Presence

Detect whether a peer tool is configured in the current project by checking for
**sentinel files** at the git root.

| Tool | Sentinel |
|------|----------|
| Biff | `.biff` |
| Vox | `.vox/config.md` |
| Lux | (TBD) |
| Beads | `.beads/` |
| Quarry | `.quarry.toml` (proposed) |

**Rule**: Check sentinels with a simple path existence test. Never import a
peer's library just to check presence. Never fail if a sentinel is absent —
skip the integration silently.

```python
# Good — L0 presence check
from pathlib import Path

def has_biff() -> bool:
    return Path(".biff").exists()
```

#### L1: Discovery

Verify that a peer tool's **executable or MCP server** is available at runtime.

| Method | When to use |
|--------|-------------|
| `shutil.which("biff")` | CLI tools on PATH |
| MCP tool list inspection | MCP servers in the current session |

**Rule**: L1 checks must be lazy (run at first use, not at import time) and
cached for the session. A missing binary at L1 means the integration is
unavailable — do not prompt the user to install anything.

#### L2: Events

React to peer activity through **Claude Code hooks** — specifically
`PostToolUse` regex matchers and `Stop` hook blocking.

Examples:

- Vox listens for PR-related `Bash` calls via `PostToolUse` to announce merges.
- Biff's `Stop` hook triggers a spoken recap via vox if voice mode is active.

**Rule**: Event integrations must be **additive only**. A hook may enrich
output or trigger a side effect, but must never block or modify the primary
tool's operation. If the peer is absent, the hook is a no-op.

#### L3: State

Read peer state through **shared file schemas** with well-known formats.

| Format | Use case | Example |
|--------|----------|---------|
| TOML | Configuration | `.quarry.toml` |
| YAML frontmatter | Document metadata | `.vox/config.md` |
| JSONL | Append-only logs | `.beads/issues.jsonl` |

**Rule**: State files are **read-only across tool boundaries**. A tool may read
another tool's state file but must never write to it. The owning tool is the
sole writer. Schema changes to state files are breaking changes and must be
versioned.

### Enhanced Tier (L4–L5)

These layers are available only to Punt Labs tools that share the
`punt_kit.integration` library.

#### L4: Library

A shared Python module providing typed access to peer discovery and state.

```python
from punt_kit.integration import discover_peers, read_peer_state

peers = discover_peers()       # Returns available peers with their tiers
state = read_peer_state("vox") # Typed accessor for vox config
```

**Rule**: The integration library must not import any peer's code. It reads
sentinel files (L0), checks binaries (L1), and parses state files (L3) —
nothing more. This keeps the dependency graph flat.

#### L5: Orchestration

Agent-level coordination where tools chain prompts, share context, or
delegate subtasks to each other.

Examples:

- The prfaq researcher agent checks for quarry MCP tools (L1), uses them if
  available, and degrades to web search if not.
- Biff's `Stop` hook reads beads state (L3) and vox config (L3) to compose a
  session recap that is both spoken and messaged.

**Rule**: Orchestration must declare its degradation path. Document what
happens when each peer is absent. Never assume a peer is available at L5 —
always fall through the tiers.

---

## Integration Matrix

Each peer integration should be documented with the layers it uses and how the
consumer degrades when the building block is absent. All arrows are
**unidirectional** — building blocks never know about their consumers.

### Building Blocks

Pure building blocks with no upstream awareness:

| Block | Role | Consumers |
|-------|------|-----------|
| **vox** | TTS engine — audio output | biff (peer), langlearn-tts (hard), dungeon (peer) |
| **lux** | Visual output surface — tables, charts, UI | prfaq (peer), quarry (peer), langlearn (peer), dungeon (peer) |
| **beads** | Issue tracking (external) | biff (peer) |
| **langlearn-types** | Shared interfaces for langlearn family | langlearn (hard), langlearn-tts (hard), langlearn-anki (hard), langlearn-imagegen (hard) |

### Peer Integrations

| Integration | Layers | Degradation |
|-------------|--------|-------------|
| biff → vox | L0, L2, L3 | Without vox: messages are text-only. Hook-triggered vocalizations (L2) are the primary path; 1–2 use cases may also use MCP tools (L1). |
| biff → beads | L0, L1, L2, L3 | Without beads: no issue context in messages. |
| prfaq → quarry | L1, L5 | Without quarry: researcher agent falls back to web search. |
| prfaq → lux | L1 | Without lux: text-only output in terminal. With lux: visual PR/FAQ dashboard, meeting displays. |
| quarry → lux | L1 | Without lux: CLI text output. With lux: interactive data explorer, search result tables. Could replace quarry-menubar. |
| quarry-menubar → quarry | L1 | Without quarry: menubar app has no backend. REST API discovery over HTTP. Lux may replace this surface. |
| langlearn → langlearn-tts | L1 | Without langlearn-tts: no audio output. Flashcards, spaced repetition, and other non-audio functions still work. Langlearn is an LLM outer loop — it discovers langlearn-tts MCP tools at runtime. |
| langlearn → lux | L1 | Without lux: no visual flashcard display. Audio and SRS still work. |
| dungeon → lux | L1 | Without lux: text adventure in terminal. With lux: visual game UI, maps, inventory. |
| dungeon → vox | L1 | Without vox: silent gameplay. With vox: narration, sound effects, ambient audio. |

**Rule**: New cross-tool integrations must add a row to this matrix (in the
relevant project's DESIGN.md or this standard) before implementation.

---

## Guidelines for External Tools

External tools (beads, gh, future third-party tools) can participate at
L0–L3 without any coordination with us:

1. **L0**: Drop a sentinel file that our hooks can detect.
2. **L1**: Be on PATH or register as an MCP server.
3. **L2**: Emit recognizable patterns in tool output that hooks can match.
4. **L3**: Use a documented file format (TOML, YAML, JSONL) for state.

We should not gate our L0–L3 integrations on approval from external tool
authors. If the file format is stable and documented, we can read it.

---

## Anti-Patterns

- **Import coupling**: Importing a peer's Python package to check if it exists.
  Use L0/L1 instead.
- **Write-across**: Writing to another tool's state file. The owning tool is
  the sole writer.
- **Hard failure**: Crashing or erroring when a peer is absent. Degrade
  silently.
- **Install prompting**: Telling the user to install a missing peer at runtime.
  The tool works alone; the peer is a bonus.
- **Eager detection**: Running discovery at import time. Use lazy, cached
  checks at first use.
- **Reverse awareness**: A building block importing or checking for its
  consumers. Arrows are unidirectional — consumers discover blocks, never the
  reverse.
