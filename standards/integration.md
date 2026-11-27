# Integration Standards

**Updated:** 2026-11-27

How Punt Labs tools discover, communicate with, and coordinate each other
inside a Claude Code session — without hard dependencies. Each obligation is
an `INT-<n>` clause; implementation rules live in
[Python](../lang-rules/python/python-enablement.md) and
[Go](../lang-rules/go/go-enablement.md).

---

## Design Principle

### INT-1: Degrade gracefully when a peer is absent

**Applies to:** python, go

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

### INT-2: Manage hard dependencies in the package manifest

**Applies to:** python, go

**Rule**: If removing the dependency causes an import or build failure (a
Python `ImportError`, a Go build error), it's a hard dependency (manage it in
the package manifest: `pyproject.toml`, `go.mod`). If removing it causes degraded but
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

##### INT-3: Detect a peer from its effective-state markers

**Applies to:** python, go

Detect whether a peer tool is on in the current checkout from its markers at
the git root: the shared `.punt-labs/<tool>/enabled` or the personal
`.punt-labs/local/<tool>/enabled`, and neither `.punt-labs/<tool>/opt-out` nor
`.punt-labs/local/<tool>/disabled`
([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)).
The table lists the shared marker.
The marker supersedes every legacy repo-root sentinel as the presence signal,
whatever shape it took — see [legacy shapes](../docs/repo-layout.md#compatibility-inventory).

| Tool | Presence check |
|------|----------------|
| Biff | `.punt-labs/biff/enabled` |
| Vox | `.punt-labs/vox/enabled` |
| Lux | `.punt-labs/lux/enabled` |
| Ethos | `.punt-labs/ethos/enabled` |
| Quarry | `.punt-labs/quarry/enabled` |

**Rule**: Check presence with a simple path existence test. Never import a
peer's library just to check presence. Never fail if the marker is absent —
skip the integration silently.

```python
# Good — L0 presence check
from pathlib import Path


def has_biff() -> bool:
    p = Path(".punt-labs")
    if (p / "biff/opt-out").exists() or (p / "local/biff/disabled").exists():
        return False
    return (p / "biff/enabled").exists() or (p / "local/biff/enabled").exists()
```

Legacy settings preservation and destinations: [PLD-10](punt-labs-dir.md#pld-10-relocation-preserves-meaning-and-content) and [compatibility reference](../docs/repo-layout.md#compatibility-inventory).

#### L1: Discovery

##### INT-4: Discover peers lazily, once per session

**Applies to:** python, go

Verify that a peer tool's **executable or MCP server** is available at runtime.

| Method | When to use |
|--------|-------------|
| `shutil.which("biff")` (Python), `exec.LookPath("biff")` (Go) | CLI tools on PATH |
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

##### INT-5: React to a peer's operation additively

**Applies to:** python, go

**Rule 1: Additive only — for peer / cross-tool reactions.** When a hook
reacts to *another* tool's operation (the L2 case here: vox reacting to a
PR creation, quarry reacting to a WebFetch), it may enrich output or trigger
a side effect, but must never block or modify that primary operation. If the
peer is absent, the hook is a no-op.

This scopes to peer reactions only. A hook acting on **its own tool's**
operation legitimately blocks or mutates it — a mutation/stamping `PreToolUse`
hook (e.g. the caller-identity stamper that rewrites its own server's
arguments via `updatedInput`, [mcp-caller-identity.md § 3.1](mcp-caller-identity.md#31-the-hook),
or a workflow gate that denies an edit, [HOOK-13](hooks.md#hook-13-use-blocking-hooks-sparingly))
is doing exactly that by design. The "additive only" rule does not reach a
tool governing its own calls.

##### INT-6: Own your reaction to shared events

**Applies to:** python, go

**Rule 2: Each building block owns its reaction to shared events.**
When multiple plugins hook the same Claude Code event (e.g., PostToolUse
on `create_pull_request`), each reacts independently in its own domain:
vox speaks, biff messages, quarry captures. Building blocks do not call
each other for generic lifecycle events — this prevents duplicate
reactions. See [hooks.md § 9](hooks.md#9-cross-tool-hook-coordination)
and [DES-009](../DESIGN.md#des-009-building-block-hook-ownership).

##### INT-7: Put domain-specific reactions in the consumer

**Applies to:** python, go

**Rule 3: Consumers add domain-specific context.** Only the domain
owner has the context for meaningful content. Z-spec narrating model
check results via vox is consumer behavior. Quarry rendering search
results via lux is consumer behavior. The Linear issues for this
work carry the consumer project's repo label, not the building block.

#### L3: State

##### INT-8: Read peer state files and never write them

**Applies to:** python, go

Read peer state through **shared file schemas** with well-known formats.

| Format | Use case | Example |
|--------|----------|---------|
| TOML | Configuration | `pyproject.toml` |
| YAML frontmatter | Document metadata | `.punt-labs/vox/vox.md`, `.punt-labs/quarry/config.md` |
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

##### INT-9: Keep the integration library free of peer code

**Applies to:** python

A shared Python module providing typed access to peer discovery and state.

```python
from punt_kit.integration import discover_peers, read_peer_state

peers = discover_peers()  # Returns available peers with their tiers
state = read_peer_state("vox")  # Typed accessor for vox config
```

**Rule**: The integration library must not import any peer's code. It reads
presence markers (L0), checks binaries (L1), and parses state files (L3) —
nothing more. This keeps the dependency graph flat.

#### L5: Orchestration

##### INT-10: Declare the degradation path of every orchestration

**Applies to:** python, go

Agent-level coordination where tools chain prompts, share context, or
delegate subtasks to each other.

Examples:

- The prfaq researcher agent checks for quarry MCP tools (L1), uses them if
  available, and degrades to web search if not.
- Biff's `Stop` hook reads git state (L2) and vox config (L3) to compose a
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

### INT-11: Couple to extension file formats and write only your own

**Applies to:** python, go

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

### INT-12: Record every peer integration before implementing it

**Applies to:** python, go

Each peer integration is recorded, before implementation, with the layers
it uses and how the consumer degrades when the building block is absent: in
the consumer's DESIGN.md or in the
[integration matrix](../docs/integration-matrix.md). All arrows are
**unidirectional** — building blocks never know about their consumers.

---

## Bundled Integrations

When we integrate with a tool that ships separately — whether external
(git, gh) or internal (ethos, beadle) — the integration code
ships with our package. But structurally, these are still integrations,
not core logic.

### The principle

An integration with git follows the same patterns as a peer integration
with ethos or beadle. The difference is packaging: ethos can meet us
halfway (it provides the extension mechanism, we provide the content),
while git cannot — so we carry both sides. Internal tools that ship in
separate repos face the same constraint at the code boundary. The code
structure should still reflect the integration boundary in all cases.

### INT-13: Separate bundled integration code from core logic

**Applies to:** python, go

1. **Separate the integration code.** Put git-specific logic in a
   module like `git_integration.py` or a `connectors/git.py` directory,
   not scattered across core search/index/query modules. The core
   should not import git concepts directly.

2. **Use the same tiered protocol.** External integrations participate
   at L0–L3 just like peer integrations:
   - **L0**: Sentinel detection (`.git` exists — file or directory, since
     worktrees use a file pointing to the actual gitdir)
   - **L1**: Binary on PATH (`git`, `gh`)
   - **L2**: Output parsing (git log, git status)
   - **L3**: State files (`.git/` internals)

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
- A pattern for adding more integrations (beadle, Linear, etc.)

The integrations a consumer bundles are listed in the
[integration matrix](../docs/integration-matrix.md#candidates-for-bundled-integrations).

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

---

## Cross-repo rename trains

### INT-14: Rename a consumed surface as one coordinated train

**Applies to:** python, go

When a building block renames a public surface (MCP tool, CLI verb,
REST route, library entry point) its consumers depend on, the rename
is a **coordinated train**, not a per-consumer migration.

**No shims, no aliases, no deprecation windows.** Two names for one
operation is exactly the drift that breaks consumers over time — one
consumer moves, one does not, and the surface carries both names
forever. The coordination cost of a train is paid once; the cost of
aliases is paid every time a caller has to decide which name to use
and every time a review has to check both are still working.

**The runbook** (the block author executes):

1. **Enumerate consumers.** Every repo that names the old surface
   (grep the org, ask by biff). Record the migration cost per
   consumer.
2. **Biff every consumer** before the rename PR opens. Include the
   rename table and the ETA. Address by session name from `/who`
   (never `@repo` aliases — they deliver nowhere. Biff is the only
   cross-repo coordination channel; Linear and GitHub issues do not
   reach another repo's agent).
3. **Wait for `ack` from every consumer.** Silence is not consent —
   hold the rename PR until every consumer replies.
4. **Merge the rename atomically.** No two-phase deploy. The old
   names disappear in the same commit the new names appear in.
5. **Follow up on merge** with the release version and the
   `pip install` line. Each consumer updates their end.
6. **Verify end-to-end.** Each consumer's demo gate exercises the new
   surface against the new block version.

**Offline consumers** — repos whose agent is not currently in `/who`
— get a Linear issue labelled with their repo (`save_issue` on team `PL`)
naming the rename and the ETA. That is their inbox until the agent
returns.

This applies at the client-surface boundary of any project realizing
the [projection model](architecture.md#the-projection-model-canonical).
The block author owns the rename; consumers own their adoption
inside their own release cycle.
