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
| Lux | `.lux/config.md` |
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

- Vox speaks a summary on Stop (vox's own behavior, not triggered by a consumer).
- Biff suggests `/wall` on PR creation (biff's own messaging reaction).
- Quarry ingests URLs on WebFetch completion (quarry's own capture behavior).

**Rule 1: Additive only.** A hook may enrich output or trigger a side
effect, but must never block or modify the primary tool's operation. If
the peer is absent, the hook is a no-op.

**Rule 2: Each building block owns its reaction to shared events.**
When multiple plugins hook the same Claude Code event (e.g., PostToolUse
on `create_pull_request`), each reacts independently in its own domain:
vox speaks, biff messages, quarry captures. Building blocks do not call
each other for generic lifecycle events — this prevents duplicate
reactions. See [hooks.md § 9](hooks.md#9-cross-tool-hook-coordination)
and [DES-009](../DESIGN.md#des-009-building-block-hook-ownership).

**Rule 3: Consumers add domain-specific context.** Only the domain
owner has the context for meaningful content. Z-spec narrating model
check results via vox is consumer behavior. Quarry rendering search
results via lux is consumer behavior. These beads belong in the
consumer project, not the building block.

#### L3: State

Read peer state through **shared file schemas** with well-known formats.

| Format | Use case | Example |
|--------|----------|---------|
| TOML | Configuration | `.quarry.toml` |
| YAML frontmatter | Document metadata | `.vox/config.md` |
| JSONL | Append-only logs | `.beads/issues.jsonl` |
| Wheel/sdist | Build artifacts | `dist/punt_biff-1.4.2-py3-none-any.whl` |

**Build artifacts as L3 state.** A project's `dist/` directory contains wheels
that sibling projects can install for pre-merge testing. The producing project
runs `make build`; the consuming project installs with
`uv pip install ../<project>/dist/<wheel>.whl`. This is read-only integration —
consumers never write to a producer's `dist/`.

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

## Ethos-Mediated Integration

Ethos extensions provide L2-level integration without import
dependencies. Any tool can store configuration and session context in an
identity's extension directory:

```text
~/.punt-labs/ethos/identities/<handle>.ext/<tool>.yaml
```

### How it works

1. **Tool A writes its extension** during install — config keys plus a
   `session_context` block with markdown instructions.
2. **Ethos emits `session_context`** verbatim at session start and before
   context compaction. No parsing, no tool-specific code in ethos.
3. **Tools read their own or peer extensions** via the filesystem (sidecar
   contract) — e.g., quarry reads `memory_collection` from its own ext
   file; a future tool could read a peer's ext file for discovery.

### Key properties

- **One-way dependency.** The consumer depends on ethos for identity. Ethos
  has zero knowledge of consumer internals.
- **No import coupling.** Tools read each other's ext files via the
  filesystem, not by importing each other's code.
- **Generic mechanism.** Adding a new tool's session context requires zero
  ethos code changes. Any extension can provide session context.

### Anti-patterns

- **Hardcoding another tool's extension schema** in your source code.
  Couple to the file format (YAML keys), not to the tool's Python/Go
  modules.
- **Writing to another tool's extension file.** Each tool owns its own
  `<tool>.yaml`. Cross-tool coordination happens via ethos identity, not
  by modifying each other's files.

See [distribution.md § Ethos Extension Setup](distribution.md#ethos-extension-setup)
for install requirements. Pattern:
[ethos-ext-setup](../patterns/ethos-ext-setup.md).

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
| **ethos** | Identity + session context delivery | quarry (peer), biff (peer), vox (peer) |

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
| quarry → ethos | L2 | Without ethos: no agent-scoped memory, no session context injection. Quarry still works for project-scoped search. |
| biff → ethos | L2 | Without ethos: no identity-aware messaging. Biff still works with anonymous sessions. |
| vox → ethos | L2 | Without ethos: no voice personality persistence. Vox still works with default voice. |

**Rule**: New cross-tool integrations must add a row to this matrix (in the
relevant project's DESIGN.md or this standard) before implementation.

---

## Bundled Integrations

When we integrate with a tool that ships separately — whether external
(git, gh) or internal (ethos, beadle, beads) — the integration code
ships with our package. But structurally, these are still integrations,
not core logic.

### The principle

An integration with git follows the same patterns as a peer integration
with ethos or beadle. The difference is packaging: ethos can meet us
halfway (it provides the extension mechanism, we provide the content),
while git cannot — so we carry both sides. Internal tools that ship in
separate repos face the same constraint at the code boundary. The code
structure should still reflect the integration boundary in all cases.

### How to model it

1. **Separate the integration code.** Put git-specific logic in a
   module like `git_integration.py` or a `connectors/git.py` directory,
   not scattered across core search/index/query modules. The core
   should not import git concepts directly.

2. **Use the same tiered protocol.** External integrations participate
   at L0–L3 just like peer integrations:
   - **L0**: Sentinel detection (`.git` exists — file or directory, since
     worktrees use a file pointing to the actual gitdir)
   - **L1**: Binary on PATH (`git`, `gh`, `bd`)
   - **L2**: Output parsing (git log, git status, beads JSONL)
   - **L3**: State files (`.git/` internals, `.beads/issues.jsonl`)

3. **Degrade when absent.** Quarry works without git (indexes files,
   serves search). Git integration adds commit-aware sync, branch
   detection, and `.gitignore` filtering. These are peer features,
   not requirements.

4. **Don't gate on approval.** We should not wait for external tool
   authors to add integration support. If the file format is stable
   and documented, we can read it.

### Why this matters

When integration code is mixed into core logic, you get:

- Core modules importing subprocess to shell out to `git`
- Business logic branching on `if git_repo:` in search paths
- Test suites that need git repos for unrelated features
- Difficulty adding a second VCS (or removing git awareness)

When it's separated, you get:

- Core modules that know nothing about version control
- An integration layer that translates between git concepts and
  quarry concepts
- Tests that can exercise core logic without a git repo
- A pattern for adding more integrations (beads, beadle, Jira, etc.)

### Candidates for bundled integrations

| Tool | What we read | What it enables |
|------|-------------|----------------|
| **git** | `.git/`, status, log, `.gitignore` | Commit-aware sync, branch detection, ignore filtering |
| **beads** | `.beads/issues.jsonl` | Work context in agent sessions, bead-linked memories |
| **beadle** | Email via MCP | Email memory, auto-ingest correspondence |
| **gh** | GitHub API via CLI | PR context, issue linking, review integration |

Each of these follows the same pattern: the integration ships with
quarry (or whichever consumer), is structurally separated from core
logic, and degrades gracefully when the external tool is absent.

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
