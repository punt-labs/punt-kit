# CLAUDE.md `@`-import Includes

How tools make their usage instructions available to every session by owning a
doc file that `CLAUDE.md` `@`-imports — one bare line in the host file, zero
managed content. The normative contract is the
[Tool Enable/Disable Standard](../standards/tool-enable-disable.md); this
pattern records the problem and the shape of the solution.

---

## Problem

An agent starts a session with no knowledge of which tools are installed beyond
what MCP servers expose. Plugin skill descriptions are per-invocation and only
surface when a skill triggers. The agent needs persistent, always-present
guidance about available slash commands, auto-behaviors, and usage tips — and
that guidance must stay current as the tool evolves.

## Forces

- **Always in context.** Guidance must load into every relevant session, not
  wait for a skill to trigger. `@`-imported files load into context.
- **Current, not stale.** When the tool's instructions change between versions,
  the agent must see the new ones — not a block frozen at first install.
- **User-owned host file.** The consuming `CLAUDE.md` is hand-authored prose.
  Tooling must not own bytes inside it — no marker blocks, no managed sections,
  no merge algorithm.
- **Clear ownership.** The tool owns its own instructions and its own single
  import line; nothing else in the host file belongs to any tool.
- **Idempotent.** Registering the same tool twice must not duplicate anything.

## Why injected blocks and managed sections were retired

Two marker-based mechanisms preceded this pattern. Per-tool injected blocks
(`<!-- <tool>:capabilities -->`) had no update path and grew the host file with
every tool. The successor — one `<!-- punt:mandatory-reading -->` managed
section maintained by a shared reconcile — still owned bytes inside the user's
file and needed the full atomic / symlink-safe / byte-preserving /
corruption-safe machinery to avoid corrupting the prose around it. A per-tool
bare line needs none of that block logic: each tool touches only its own
one-line string, matched exactly.

## Solution

The tool writes its agent-facing user guide to its own directory and adds one
bare `@`-import line to the host `CLAUDE.md`:

```text
~/.punt-labs/<tool>/CLAUDE.md       # GLOBAL tool — @~/.punt-labs/<tool>/CLAUDE.md in ~/.claude/CLAUDE.md
<repo>/.punt-labs/<tool>/CLAUDE.md  # REPO tool — @.punt-labs/<tool>/CLAUDE.md in <repo>/CLAUDE.md
```

- A **global** tool (vox, quarry, biff) deposits its guide and appends the
  user-scope line at `install`, once per machine; `uninstall` removes the line.
- A **repo-scoped** tool deposits its guide, the `enabled` marker, and the
  repo-scope line via `<tool> enable`; `disable` reverses them.
- The line is bare — no heading, no comment, no marker — appended at end of
  file, matched exactly, removed exactly. The write is locked, atomic,
  symlink-resolving, and byte-preserving
  ([tool-enable-disable.md § 2.4](../standards/tool-enable-disable.md#24-import-line-rules)).
- The tool overwrites its own `.punt-labs/<tool>/` subtree wholesale on every
  install/upgrade — the guide is the single source of truth, so updates flow
  automatically.

## Consequences

- **Agents discover tools, and stay current.** New slash commands or gotchas in
  a tool's doc reach the agent on the next session with no re-injection.
- **Host file stays small and user-owned.** `CLAUDE.md` holds N one-line
  imports, not N blocks — and no tool-owned section at all.
- **No cross-tool coupling.** Each tool adds and removes its own line
  independently; there is no shared list, shared writer, or contended section.
- **Import depth is bounded.** Keep tool docs flat; Claude Code resolves
  `@`-imports recursively only to a bounded depth.

## Related Patterns

- [Two-Phase Install](two-phase-install.md)
- [Ethos Extension Setup](ethos-ext-setup.md) — complementary identity-scoped
  session context
- [Prior-Context Priming](prior-context-priming.md) — why prior-context
  guidance is more effective than same-turn instructions

## Known Uses

- **vox** — reference implementation. Writes `~/.punt-labs/vox/CLAUDE.md` and
  registers the `@`-import at install; `GlobalClaudeImports`
  (`src/punt_vox/claude_md.py`) is the atomic, symlink-safe, byte-preserving
  writer whose correctness each tool ports. The `@`-import load is empirically
  verified against Claude Code.
- **quarry** (migration target) — currently injects a
  `<!-- quarry:capabilities -->` block via `_inject_claude_md()`; to move to a
  tool-owned `.punt-labs/quarry/CLAUDE.md` + bare import line.
