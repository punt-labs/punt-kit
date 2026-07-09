# CLAUDE.md `@`-import Includes

How tools make their usage instructions available to every session by owning a
doc file that `CLAUDE.md` `@`-imports — rather than injecting content blocks
into the user's `CLAUDE.md`.

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
- **No host-file churn.** The consuming `CLAUDE.md` should not accumulate a
  growing pile of tool content. It should hold references, not manuals.
- **Clear ownership.** The tool owns its own instructions; the host `CLAUDE.md`
  owns only the list of what to load.
- **Idempotent.** Registering the same tool twice must not duplicate anything.
- **Complementary.** `@`-import includes are for always-on, updatable tool
  usage. Ethos `session_context` is for identity-scoped instructions. Plugin
  skills are for per-invocation behavior. Each mechanism has its role.

## Why the older inject-a-block approach was retired

Tools used to append a marker-wrapped section (`<!-- <tool>:capabilities -->`)
directly into `~/.claude/CLAUDE.md`. Two flaws forced the change:

- **No update path.** A block, once written, was never refreshed — the standard
  told tools to "use stable content that doesn't need updates," which is a
  workaround, not a fix.
- **Host-file growth.** Every tool added 10–15 lines to one shared file.

## Solution

### Tool-owned doc

The tool writes its agent-facing usage doc to its product namespace — **scope
follows the tool, global by default**:

```text
~/.punt-labs/<product>/CLAUDE.md       # GLOBAL tool (default) — from ~/.claude/CLAUDE.md
<repo>/.punt-labs/<product>/CLAUDE.md  # PROJECT tool — vendored, from <repo>/CLAUDE.md
```

The tools that use this (quarry, biff, vox) are global — they work in every
project, so they write the home doc and register at install time (once, covers
all projects). Reserve project-scope for a doc committed with one repo. The tool
rewrites this file on every install/upgrade — it is the single source of truth,
so updates are automatic. It registers its own `@`-import line through the
shared reconcile (below); it never makes ad hoc edits to the host `CLAUDE.md`
outside the managed section.

### Managed Tool Guidance section

The host `CLAUDE.md` carries one `punt`-owned section listing the imports:

```markdown
<!-- punt:mandatory-reading -->
## Tool Guidance (auto-loaded)

These docs load into context via `@`-import — nothing to open.

@~/.punt-labs/vox/CLAUDE.md
@~/.punt-labs/quarry/CLAUDE.md
<!-- /punt:mandatory-reading -->
```

`punt` scaffolding (`/punt:init` or a session-start hook) reconciles the list
against the installed `.punt-labs/*/CLAUDE.md` files: add a line when a doc
appears, prune it when the tool is removed.

### Reconcile algorithm and invariants

The reconcile **regenerates the whole managed section** (never appends): read
the host file, find the `<!-- punt:mandatory-reading -->` … `<!-- /… -->` block,
and replace it (inserting one if absent) with a section rendered from the
**sorted** set of installed docs. Regenerating — not appending — is what makes
it both idempotent AND self-updating: a doc added, moved, or uninstalled is
reflected on the next run.

Because it edits the user's hand-authored (possibly dotfile-symlinked)
`~/.claude/CLAUDE.md`, the implementation has hard invariants the vox reference
learned under review. **Do NOT implement it with `Path.read_text`/`write_text`
or `rstrip()`** — those apply universal-newline translation and trim user
content. The reconcile MUST: write **atomically** (temp + `fsync` + `os.replace`,
never truncate-in-place); **resolve symlinks** and write the real target,
preserving the link; **preserve bytes and mode** — read *and* write with
`newline=""` (the default translation silently rewrites the user's CRLF/CR
endings, corrupting content outside the managed section) and keep an existing
file's mode; be **deterministic** (sort imports) and **no-op-when-unchanged**;
be **corruption-safe** (a lone/duplicate marker collapses to one section, never
appends a second); match markers **at column 0, outside code fences**; and
**validate** each import line. See the standard's Rules and vox's
`GlobalClaudeImports` for the full, tested contract.

## Consequences

- **Agents discover tools, and stay current.** New slash commands or gotchas in
  a tool's doc reach the agent on the next session with no re-injection.
- **Host file stays small.** `CLAUDE.md` holds N one-line imports, not N blocks.
- **Two owners, cleanly split.** The tool owns `.punt-labs/<product>/CLAUDE.md`;
  `punt` owns the import list. Neither reaches into the other.
- **Import depth is bounded.** Keep tool docs flat; Claude Code resolves
  `@`-imports recursively only to a bounded depth.

## Related Patterns

- [Two-Phase Install](two-phase-install.md)
- [Ethos Extension Setup](ethos-ext-setup.md) — complementary identity-scoped
  session context
- [Prior-Context Priming](prior-context-priming.md) — why prior-context
  guidance is more effective than same-turn instructions

## Known Uses

- **vox** — reference implementation (merged, `punt-labs/vox#306`). Writes
  `~/.punt-labs/vox/CLAUDE.md` and self-registers the `@`-import at install;
  `GlobalClaudeImports` (`src/punt_vox/claude_md.py`) is the atomic, symlink-safe,
  byte-preserving reconcile. The `@`-import load is empirically verified against
  Claude Code and the invariants are under a `prune(register(x)) == x` property
  test.
- **quarry** (migration target) — currently injects a
  `<!-- quarry:capabilities -->` block via `_inject_claude_md()`; to move to a
  tool-owned `.punt-labs/quarry/CLAUDE.md` + managed import.
