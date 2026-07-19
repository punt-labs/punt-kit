# Design: CLAUDE.md `@`-Include Architecture and the `enable` / `disable` Convention

**Introduced:** 2026-07-19
**Status:** DESIGN (round 2 — rop/adt review and all operator rulings, including
the four settled §8 decisions, folded in) — ready for step-2 dispatch
**Worker:** mdm · **Evaluators:** rop, adt · **Ticket:** pkit-lu1q

This document proposes one new Punt Labs standard and one meta-convention, then
resolves every open question the mission named, records rejected alternatives,
and lists the exact step-2 change per affected file.

The proposed standard supersedes **two** marker-based mechanisms, not one:

1. `punt auto claude` — the BEGIN/END managed sections merged into a repo
   `CLAUDE.md` (`CLAUDE_SECTIONS` in `src/punt_kit/auto.py`).
2. The `<!-- punt:mandatory-reading -->` managed Tool Guidance block and its
   shared reconcile, described today in
   [distribution.md § CLAUDE.md `@`-import Includes](../standards/distribution.md).

Both carry markers and run a byte-owning reconcile inside the user's file. The
new model keeps neither: the only mutation any tool makes to a `CLAUDE.md` is one
bare `@`-import line.

---

## 1. Summary

A user's `CLAUDE.md` is user-owned prose. Punt Labs tooling never merges, marks,
or manages sections inside it. The single permitted mutation is one import line
per enabled tool:

```text
@.punt-labs/<tool>/CLAUDE.md        # repo scope, in <repo>/CLAUDE.md
@~/.punt-labs/<tool>/CLAUDE.md      # user scope, in ~/.claude/CLAUDE.md
```

Each tool owns `<repo>/.punt-labs/<tool>/` (and `~/.punt-labs/<tool>/` for global
tools) entirely, writing the whole subtree on enable/upgrade and overwriting it
wholesale — no read-modify-merge anywhere. Composition happens at read time when
Claude Code resolves the `@`-import, never at write time. Every tool CLI exposes
`enable` / `disable`, run inside a repo, to deposit or withdraw that subtree, the
import line, and any hooks or config.

---

## 2. Proposed standard (drop-in for `standards/tool-enable-disable.md`)

The content of sections 2.1–2.13 is the full, drop-in text for a new standard
file at `standards/tool-enable-disable.md` (operator-chosen path), title **Tool
Enable/Disable Standard**. Like every standard, the file carries its own
`**Introduced:**` date (per the separate convention in section 3); the convention
text itself does **not** live in this standard.

### 2.1 Core Principle

**The user's `CLAUDE.md` is user-owned prose. Tooling never merges, marks, or
manages sections inside it.** The only mutation any tool may make to a
`CLAUDE.md` is to add or remove a single `@`-import line pointing at a file the
tool owns entirely. Composition happens at read time, when Claude Code resolves
the import — never at write time. There is no marker block, no managed section,
no merge algorithm, and no reconcile that owns bytes inside the host file.

This standard governs only the **contract**: the import line, the tool-owned
`.punt-labs/<tool>/` directory, the required user-guide doc, and the `enable` /
`disable` verbs. It does not describe, require, or permit managed sections,
markers, or content templates for any user-owned `CLAUDE.md`, and it does not
author user-guide content.

**Two separate things, never conflated.** Punt Labs *dev-process standards*
(this `standards/` tree — how we build our own tools) are entirely separate from
*tool user guides* (what `enable` installs for a tool's users — how an agent
drives the tool). A deposited `.punt-labs/<tool>/CLAUDE.md` is a user guide, not
dev standards and not the tool repo's own developer `CLAUDE.md`.

### 2.2 Ownership

| Path | Owner | Lifecycle |
|------|-------|-----------|
| `<repo>/CLAUDE.md`, `~/.claude/CLAUDE.md` | The user | Tool adds or removes one import line; every other byte is untouched |
| `<repo>/.punt-labs/<tool>/` | The tool | Deposited on `enable`, overwritten wholesale on upgrade, left dormant on `disable` |
| `~/.punt-labs/<tool>/` | The tool | Deposited on `install` (global tools), overwritten wholesale on upgrade |

Each tool owns its `.punt-labs/<tool>/` subtree completely. It writes the whole
subtree on enable/upgrade and never reads-modifies-merges it: same tool version,
same repo config, identical output.

### 2.3 The `enable` / `disable` Convention

Every tool CLI with per-repo presence exposes two commands, run from inside a
repo. This extends the `enable` / `disable` entry in
[cli.md § Required Subcommands](../standards/cli.md#enable--disable).

**`enable`** — idempotent; re-running is also the upgrade path:

1. Deposit `<repo>/.punt-labs/<tool>/CLAUDE.md` (and any other files the tool
   ships), overwriting wholesale.
2. Write the enabled marker `<repo>/.punt-labs/<tool>/enabled` (see 2.7).
3. Add `@.punt-labs/<tool>/CLAUDE.md` to `<repo>/CLAUDE.md` if absent. Never add
   it twice.
4. Optionally register repo-scoped hooks and config as additive entries in
   `<repo>/.claude/settings.json` (see 2.8).

**`disable`**:

1. Remove `@.punt-labs/<tool>/CLAUDE.md` from `<repo>/CLAUDE.md`.
2. Delete the enabled marker `<repo>/.punt-labs/<tool>/enabled`.
3. Deregister the hook and config entries it added.
4. Leave the rest of `<repo>/.punt-labs/<tool>/` in place, dormant (see 2.9).

### 2.4 Import Line Rules

- **Canonical import string.** The line is exactly `@.punt-labs/<tool>/CLAUDE.md`
  (repo) or `@~/.punt-labs/<tool>/CLAUDE.md` (user), with `<tool>` the CLI binary
  name. Forward slashes; no `./` prefix; no trailing slash; no leading or trailing
  whitespace; one physical line, no embedded newline. This exact string is what
  `enable` writes, what `disable` matches, and what `punt audit` greps — all 15
  CLIs must produce byte-identical lines.
- **One bare line, appended at end of file.** No heading, no marker, no comment.
- **Ensured separation.** If the host file does not end in a newline, add one
  before appending, so the import is never glued to the user's last line.
- **Idempotent by exact match.** Presence is decided by exact-string match on the
  canonical line. `enable` appends only if absent; `disable` removes every exact
  match (collapsing an accidental duplicate to zero).
- **Top-level only; skip code blocks.** Claude Code resolves `@`-imports only at
  the top level, never inside a code block. Both the presence scan (`enable`) and
  the removal (`disable`) must ignore any matching line that is inside a fenced
  code block or an indented code block. Precise definition, so 15 implementations
  agree: a line is **inside a fenced block** if the count of preceding fence
  delimiter lines — a line whose first non-whitespace run is three or more
  backticks or three or more tildes — is odd; it is an **indented code block**
  line if it begins with a tab or four or more spaces. A line matching neither is
  top-level. `@`-imports and
  the canonical string are always written at column 0, so they are top-level by
  construction.
- **Serialized, atomic, byte-preserving write.** The read-append-replace on the
  host file must be:
  - **Mutually exclusive.** Hold an exclusive lock (`flock` on the target or a
    sibling lock file, or the platform equivalent) for the whole
    read-modify-write. Atomic rename prevents a torn file; it does **not** prevent
    a lost update — two parallel `enable` runs each read the old bytes, append
    their line, and rename, and the second silently clobbers the first's line.
    The lock serializes them. (The old model relied on a stated single-writer
    assumption; the per-tool model drops it exactly where independent invocations
    become more likely, so the lock is mandatory, not optional.)
  - **Atomic.** Write a temp file in the target's own directory, then rename it
    over the target (atomic on POSIX; use the platform atomic-replace primitive).
    Never truncate-in-place.
  - **Byte-preserving.** Every byte outside the single import line is identical
    before and after, across LF, CRLF, and lone-CR endings. Read and write
    without newline translation (the language's universal-newline mode silently
    rewrites the user's endings).
  - **Symlink-resolving.** If the target is a symlink (dotfile managers do this),
    write the real target and preserve the link.
  - **Mode-preserving.** Keep an existing file's mode; a new file gets `0644`.
- **Canonical reference implementation.** vox's `GlobalClaudeImports`
  (`src/punt_vox/claude_md.py`) already satisfies the atomic / symlink /
  byte-preserving / deterministic contract for the global case. Port its
  correctness per tool (copy-not-symlink of the logic, each CLI in its own
  language) — this is distinct from the rejected shared-runtime writer (section
  6): shared *correctness*, not a shared *process*. The one addition beyond vox
  today is the exclusive lock above.

### 2.5 Every tool ships a user-guide doc

**Every tool MUST ship a user-guide `CLAUDE.md`, installed into
`.punt-labs/<tool>/CLAUDE.md` by `enable` (repo scope) or `install` (user
scope).** It is the tool's agent-facing manual — how an agent or user *drives*
the tool: slash commands, auto-behaviors, tips, gotchas. It is not the tool
repo's developer `CLAUDE.md` and not a reference dump. Precedent: vox's installed
`~/.punt-labs/vox/CLAUDE.md`, whose opening line is "how an *agent* drives vox —
not how to develop vox itself," and the beads `AGENTS.md` concept.

The doc is **static content shipped with the tool**. It needs no per-repo
localization or rendering — the same guide is deposited everywhere. How the tool
produces or stores that content is an implementation detail this standard stays
silent on.

The doc loads fully into every session that imports it, so keep it usage
guidance, not an exhaustive reference. Keep imports shallow: Claude Code resolves
`@`-imports recursively only to a bounded depth, so do not chain deep import
trees from the tool doc.

### 2.6 Scope: repo versus user

Two layers, composed additively:

| Layer | Host file | Written by | Import line |
|-------|-----------|-----------|-------------|
| Repo | `<repo>/CLAUDE.md` | `<tool> enable` (run in the repo) | `@.punt-labs/<tool>/CLAUDE.md` |
| User | `~/.claude/CLAUDE.md` | `<tool> install` (once per machine) | `@~/.punt-labs/<tool>/CLAUDE.md` |

A tool targets the layer its guidance belongs to:

- **Global tools** (vox, quarry, biff) work in every project. Their guidance is
  universal, so they register the user-scope import once at `install` and do not
  need per-repo `enable` for guidance.
- **Repo-scoped tools** carry a guide meant to travel with a repo that has opted
  in, so contributors who clone get it via the repo's `CLAUDE.md` import without
  installing the tool globally. They use `enable` / `disable`.
- A tool may do both. The two host files are independent; Claude Code loads both,
  so a repo import and a user import never collide.

### 2.7 The enabled marker

The tool is **enabled** in a repo when the marker file
`<repo>/.punt-labs/<tool>/enabled` exists. `enable` writes it; `disable` deletes
it. This is a distinct signal from directory presence: the directory can persist
(dormant vendored content) after `disable`, so directory-presence cannot mean
"enabled." The marker lives inside the tool's own subtree, so `disable` removes
it without touching anything the tool did not just create.

Hook shell gates test the marker, not the directory:

```bash
[ -f "$REPO_ROOT/.punt-labs/<tool>/enabled" ] || exit 0
```

Three states are now distinguishable, and the invariants in 2.9 and 2.11 depend
on the distinction:

| State | Directory | `enabled` marker | Import line |
|-------|-----------|------------------|-------------|
| Enabled | present | present | present |
| Dormant (disabled) | present | absent | absent |
| Absent | absent | absent | absent |

This marker replaces the legacy repo-root sentinel dotfile (`.biff`,
`.quarry.toml`): one file, inside the tool's directory, that both hook gates and
`punt audit` read.

### 2.8 Hooks and config

`enable` may register repo-scoped hooks or permissions. It may touch exactly one
file outside its own subtree — `<repo>/.claude/settings.json` — and only
additively:

- The tool computes a **deterministic set of entries** (the same inputs always
  produce the same rules — the wholesale-overwrite determinism of 2.2 guarantees
  this).
- `enable` merges that set with the order-preserving, idempotent `jq` pattern
  from [permissions.md § 6](../standards/permissions.md#6-plugin-distributed-permissions),
  adding only entries not already present.
- `disable` recomputes the identical set and removes those entries by **exact
  value-match** — the removal pattern permissions.md § 6 actually provides
  (`select(. as $r | $remove | index($r) | not)`). No tag schema is needed or
  implied; the deterministic entry set *is* the identity.
- Neither touches unrelated entries.

Most tools ship hooks through their marketplace plugin (global). Repo-scoped hook
deposit via `enable` is only for genuinely repo-scoped hook behavior.

### 2.9 `disable` is non-destructive

`disable` stops composition; it does not erase vendored data. It removes the
import line, deletes the `enabled` marker (2.7), and deregisters hooks, but leaves
the rest of `<repo>/.punt-labs/<tool>/` in place — the **dormant** state.
Rationale:

- The subtree may hold repo-committed or user-modified content; deleting it on a
  toggle is surprising and lossy.
- Re-enable is then a cheap, non-destructive refresh.
- This matches the org rule to prefer `mv` over `rm` and never to delete what a
  tool did not just create.

A user who wants the tool fully gone deletes `<repo>/.punt-labs/<tool>/` manually,
or the tool offers `disable --purge`. Removal is deliberate, never a side effect
of a toggle.

### 2.10 `punt` follows the convention

`punt` is a tool like any other. `punt enable`, run in a repo, deposits
`<repo>/.punt-labs/punt/CLAUDE.md` — punt's own static user guide (how to drive
the `punt` CLI: `init`, `audit`, `reconcile`, and so on) — and adds
`@.punt-labs/punt/CLAUDE.md` to the repo `CLAUDE.md`. It is the same kind of
static user-guide doc every tool ships (2.5), not a per-repo rendered file.

`punt`'s deposited guide is **not** the new home for the four per-repo sections
the retired `punt auto claude` target rendered (quality gates, beads, standards
references, available tooling). Those were repo-specific dev-process content, not
a tool user guide; their disposition is out of scope for this standard (see the
open issue in section 8).

The checks key on the `enabled` marker (2.7), not on directory presence, so a
dormant tool is not flagged.

- **Import present iff enabled.** For every `<repo>/.punt-labs/<tool>/` whose
  `enabled` marker is present, the repo `CLAUDE.md` contains exactly one
  `@.punt-labs/<tool>/CLAUDE.md` line. For every tool whose marker is absent
  (dormant or gone), the import line is absent. This is the load-bearing
  biconditional: enabled ⟺ import line.
- **No orphan imports.** No `@.punt-labs/<tool>/CLAUDE.md` line without a
  corresponding `.punt-labs/<tool>/CLAUDE.md` file (hard fail — the import will
  break at read time).
- **No stale enabled tools.** For every enabled tool, cross-check that the tool
  is actually installed (on `PATH`, or listed in an installed-tools manifest). A
  directory + marker + import line for an uninstalled or renamed tool means stale
  guidance loads into every session forever; flag it. (This is the
  uninstall-without-disable and rename-without-disable gap that directory checks
  alone cannot catch.)
- **No duplicates.** No import line appears more than once.
- **No legacy markers.** No `<!-- punt:begin … -->` / `<!-- punt:end … -->`
  managed sections and no `<!-- punt:mandatory-reading -->` block remain in any
  user-owned `CLAUDE.md`.
- **Well-formed lines.** Every import line is the exact canonical string (2.4),
  top-level (not in a code block), with no trailing whitespace.

### 2.12 Migration

Forward integration, no compatibility shim
([PL-PP-1](../lang-rules/python/python-prohibited-patterns.md)):

- A tool currently injecting a marker block into `~/.claude/CLAUDE.md` moves that
  content to `~/.punt-labs/<tool>/CLAUDE.md`, registers the bare import line, and
  deletes its legacy block in the same release.
- The `punt auto claude` target and the `CLAUDE_SECTIONS` registry are
  **removed, not deprecated**. The four managed sections stop being rendered into
  any user-owned `CLAUDE.md`. `punt`'s deposited file is punt's user guide (2.10),
  not a replacement home for that content. The `punt auto makefile` target is
  **out of scope** and stays as-is — this removal is CLAUDE.md-only.
- `/punt:init` (or a one-time migration) strips any residual `punt:begin` /
  `punt:end` CLAUDE.md marker sections from a repo `CLAUDE.md`, leaving the user's
  prose plus bare import lines. It does not touch Makefile marker sections.

### 2.13 `enable` versus `init`

[distribution.md § Installation Scope](../standards/distribution.md) already defines `init` as
the per-repo verb that writes a tool's repo config file (`.biff`, `.quarry.toml`)
and prompts for project-specific settings (team roster, relay URL, database
name). `enable` and `init` are **distinct roles**, not duplicates:

| Verb | Job | Writes |
|------|-----|--------|
| `enable` / `disable` | Turn CLAUDE.md guidance composition and hooks on/off in this repo | `.punt-labs/<tool>/` (guide + `enabled` marker), the import line, additive `.claude/settings.json` entries |
| `init` | Create and populate the tool's repo config/state | The tool's repo config file (`.biff`, `.quarry.toml`, `.beads/`) |

The repo config file is **no longer the enabled signal** — the `enabled`
marker (2.7) is. A tool with both verbs runs `init` to configure and `enable` to
turn on; `enable` may call `init` when enabling requires config, but the two
concerns stay separate. Tools that used `init` *only* to drop an enabled
sentinel fold that into `enable` and retire the bare repo-root sentinel.

---

## 3. The introduced-date convention (separate meta-convention)

**This is independent of the Tool Enable/Disable Standard.** It is a general
convention for the whole punt-kit standards corpus — every `standards/*.md` doc,
regardless of subject — and has nothing to do with CLAUDE.md files or the
enable/disable flows. It is presented here only because the same step-2 batch
introduces it. Its text and rules live in the standards index (`AGENTS.md`, per
"Home" below), **not** inside `tool-enable-disable.md`; that new standard simply
carries its own `**Introduced:**` date like any other standard.

Every standard in `standards/` records when it was introduced, so a consumer repo
can tell at a glance whether a rule predates its last sync.

**Field name.** `**Introduced:**` for the origin date; `**Updated:**` for the
most recent normative amendment.

**Forward-only — no backfill.** The field starts on docs created, or normatively
amended, *after* this convention lands. Existing standards are **not** given
retroactive `**Introduced:**` dates — no git archaeology, no uniform stamp. An
older doc gains the field the first time it is normatively amended (which also
sets `**Updated:**`); until then it simply has no date, and that is correct.

**Placement.** A single bold line immediately under the H1 title, before the
intro prose. Not YAML frontmatter — these are prose docs, and an inline bold line
matches the existing DESIGN.md ADR style (`**Date:** …`) and needs no parser.

**Format.** ISO 8601 `YYYY-MM-DD`. One line, mid-dot separator when both fields
are present:

```markdown
# CLI Standards

**Introduced:** 2026-07-19 · **Updated:** 2026-08-01

Standards for command-line interfaces…
```

A doc never amended carries only `**Introduced:** YYYY-MM-DD`.

**Amended dates.** Record a single most-recent `**Updated:**`, bumped only when a
*normative* rule changes — not for typo or formatting fixes. The field is an
at-a-glance signal, not a changelog; git history is the full record.

**Home of the convention text.** Document this convention in the standards index
(`AGENTS.md`), since it governs the whole corpus — not inside any one standard.

**Enforcement is format-only, not presence.** Because the rule is forward-only,
`punt audit` must **not** require every `standards/*.md` to carry the field
(legacy docs correctly lack it). It validates only that any doc which *does*
carry an `**Introduced:**` line has it well-formed:

```bash
# Fails only a doc whose Introduced line exists but is malformed.
grep -HE '^\*\*Introduced:\*\*' standards/*.md \
  | grep -vE '^[^:]+:\*\*Introduced:\*\* [0-9]{4}-[0-9]{2}-[0-9]{2}'
```

---

## 4. Rationale

**Why import, not inject.** A marker block, once written, has no update path;
tools worked around this by freezing content. The user's file also grew with
every tool. A bare `@`-import is one line the tool never rewrites — the imported
file is the single source of truth, so updates flow automatically and the host
file stays clean.

**Why drop the marker block too, not just the BEGIN/END sections.** The
`<!-- punt:mandatory-reading -->` reconcile still owns bytes inside the user's
file and still needs the full atomic / symlink-safe / byte-preserving /
corruption-safe machinery to avoid corrupting prose around it. A per-tool bare
line needs none of that block logic: each tool touches only its own one-line
string, matched exactly. Less code, less shared state, no cross-tool coupling
through one contended section.

**Why wholesale overwrite of `.punt-labs/<tool>/`.** Read-modify-merge is where
staleness and corruption live. A tool that owns its subtree and rewrites it
whole is deterministic and trivially idempotent — the same property that makes
the import model work at the host-file layer.

**Why `enable` / `disable` per tool.** The CLI is the complete product
([cli.md](../standards/cli.md)). Turning a tool on in a repo is an engine capability; it
belongs on the terminal as a first-class verb, reachable without Claude Code,
scriptable in CI, and mirrored by MCP/slash surfaces.

---

## 5. Resolved questions

Each carries an explicit recommendation and rationale.

### 5.1 `disable` semantics — does `.punt-labs/<tool>/` stay or go?

**Recommendation: stays (dormant).** `disable` removes the import line, deletes
the `enabled` marker (2.7), and deregisters hooks; it leaves the rest of the
subtree. The subtree may hold repo-committed or user-modified content, so deleting
it on a toggle is lossy and surprising. Re-enable becomes a cheap refresh. This
matches the org preference for `mv` over `rm` and the rule never to delete what a
tool did not just create. A deliberate `disable --purge` or a manual `rm -rf` is
the escape hatch.

### 5.1a Active-state signal — how `disable` is detectable (H1)

**Recommendation: an `enabled` marker file inside the tool's directory (2.7).**
The active signal cannot be directory-presence, because `disable` keeps the
directory (5.1). If it were, hook gates would keep firing after `disable` and the
audit biconditional would fail on every dormant tool. The marker
`<repo>/.punt-labs/<tool>/enabled` lives inside the tool's own subtree — so
`disable` deletes only what the tool created — and gives three clean states
(enabled / dormant / absent). Hook gates and `punt audit` both key on the marker.
An alternative bare-repo-root sentinel (`.biff`) was rejected: it splits the
tool's state across two locations and drifts.

### 5.2 Import-line placement — bare EOF line versus a conventional heading

**Recommendation: bare line at EOF.** A heading implies tooling owns a section —
exactly the managed-section model being retired. A bare line is the minimal
mutation: one uniquely identifiable string, appended at EOF, removed by exact
match, order-independent across tools. Claude Code resolves `@`-imports at column
0 regardless of surrounding headings, so a heading adds nothing functional. The
only care needed is a preceding newline so the line is not glued to the user's
last line.

### 5.3 Hooks / config deposit mechanics

**Recommendation:** `enable` may touch exactly one file outside its own subtree —
`<repo>/.claude/settings.json` — and only additively, via the order-preserving
`jq` merge from [permissions.md § 6](../standards/permissions.md). Removal is by **exact
value-match**, not tags: the tool computes a deterministic entry set (its
wholesale-overwrite determinism guarantees the same set every time), `enable`
adds the missing members, and `disable` recomputes the identical set and removes
those exact values — the `select(… index($r) | not)` pattern permissions.md § 6
actually ships. No tag schema is introduced. Hooks are normally shipped by the
tool's marketplace plugin (global); repo-scoped hook deposit is only for genuinely
repo-scoped behavior.

### 5.4 Repo-level versus user-global enable

**Recommendation:** two independent layers (2.6). `enable` / `disable` operate at
**repo** scope (`<repo>/CLAUDE.md`, `<repo>/.punt-labs/<tool>/`). `install`
operates at **user** scope for global tools (`~/.claude/CLAUDE.md`,
`~/.punt-labs/<tool>/`), once per machine. They compose additively because Claude
Code loads both host files. A tool picks the layer its guidance belongs to;
universal tools (vox) use the user layer, repo-specific tools use `enable`, and a
tool may use both.

### 5.5 Removal path for `punt auto claude` managed sections

**Settled by operator ruling: removed, not deprecated.** The `punt auto claude`
target and the `CLAUDE_SECTIONS` registry are deleted; the four managed sections
(quality-gates, beads, standards-references, available-tooling) stop being
rendered into any user-owned `CLAUDE.md`. `punt` becomes a tool following the
convention (2.10) — but its deposited `.punt-labs/punt/CLAUDE.md` is punt's
static user guide, **not** the new home for that per-repo dev-process content.

In `src/punt_kit/auto.py`, remove `CLAUDE_SECTIONS`, the `claude` entry in
`TARGETS`, and the `claude` templates. Keep `parse_segments`, `merge_file`,
`_MARKERS`, and `render_section` — the `punt auto makefile` target still uses
them, and Makefile managed sections are explicitly out of scope for this ruling.

**Where the four sections' per-repo content goes is out of scope.** That content
is dev-process guidance, not a tool user guide, so this standard does not
relocate it. If dropping it leaves a real gap, that is an open issue for the
leader (section 8), not something this design resolves.

### 5.6 What `punt audit` checks

**Recommendation:** the checks in 2.11. The load-bearing invariant is the
biconditional keyed on the `enabled` marker: **enabled ⟺ import line**. A dormant
tool (directory present, marker absent, no import line) passes; an orphan import
(line with no doc) hard-fails; a stale enabled tool (marker + line but the tool is
not installed) is flagged by cross-referencing `PATH` or an installed-tools
manifest. Keying on the marker rather than directory presence is what makes the
biconditional consistent with the non-destructive `disable` of 5.1.

### 5.7 DRY analysis

Covered in full in section 7 (step-2 change list). Overlaps and conflicts across
the corpus: distribution.md's `@`-import section and its Installation-Scope
`init` verb, cli.md's enable/disable entry, filesystem.md's per-project
activation, hooks.md's config gate, permissions.md's merge pattern, and — newly
surfaced by rop — integration.md's L0 Presence sentinels
(`.biff`, `.quarry.toml`) and doctor-checks.md's managed-section reference.

---

## 6. Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Keep the `<!-- punt:mandatory-reading -->` managed block, drop only the `punt auto` BEGIN/END sections | Still owns bytes inside the user's file; still needs the full atomic / symlink / byte-preserving / corruption-safe reconcile. A per-tool bare line needs none of that block logic and no cross-tool coupling through one contended section. |
| Import line under a conventional heading (e.g. `## Tool Guidance`) | A heading implies a tool-owned section — the managed-section model being retired. Adds no function (Claude Code resolves `@`-imports at column 0 regardless) and reintroduces "who owns this heading" ambiguity. |
| `disable` deletes `.punt-labs/<tool>/` | Lossy on repo-committed or user-modified content; a toggle should not destroy data. Prefer `mv` over `rm`; offer explicit `--purge`. |
| Read-modify-merge the tool's own `.punt-labs/<tool>/` on upgrade | Reintroduces the staleness/corruption class the whole design removes. Wholesale overwrite is deterministic and trivially idempotent. |
| One shared `punt`-owned reconcile regenerates the whole import list from installed docs | Couples every tool's enable/disable to one contended writer and one algorithm; a per-tool bare line is independently added/removed with no shared state. (This was the documented end-state of the old model; the new model makes it unnecessary.) |
| Directory presence as the enabled signal | Cannot coexist with a non-destructive `disable`: the directory stays as dormant vendored content, so its presence would keep hook gates firing and fail the audit biconditional on every dormant tool. Use an `enabled` marker file inside the directory (2.7). |
| Bare repo-root sentinel dotfile (`.biff`) for the enabled signal | Splits the tool's state across two locations (root dotfile + `.punt-labs/<tool>/` subtree) that drift. Put the marker inside the tool's own directory. |
| YAML frontmatter for the introduced-date field | Heavier than the fact warrants; changes the opening of every standards doc; needs a parser. A bold line under the H1 matches existing ADR style and greps cleanly. |
| Record a full amendment history in the date field | The field is an at-a-glance signal; git history is the full record. One most-recent `Updated:` suffices. |

---

## 7. Step-2 change list (DRY / integration)

Each entry names the file and the precise change. The design mission does not
touch any of them.

**Step 2 is docs + code, dispatched as two missions with disjoint write sets**
(leader ruling), coordinated so docs and code land together:

- **Docs mission** — write set: `standards/*.md`, `AGENTS.md`, `patterns/*.md`.
- **Code mission** — write set: `src/punt_kit/auto.py`,
  `src/punt_kit/templates/auto/claude/*`, the `punt audit` implementation, and
  the `punt enable` / `disable` implementation.

The audit checks (2.11) and the standards prose that describes them must land in
the same release, or the corpus documents a rule the tooling does not enforce.

### `standards/tool-enable-disable.md` (new)

Create from section 2 above, title **Tool Enable/Disable Standard**. As a
new doc it carries its own `**Introduced:** <landing-date>` line (the forward-only
convention, section 3). Include the required user-guide clause (2.5) and the
dev-standards vs tool-user-guide separation (2.1). Do **not** embed the
introduced-date convention text in this file — that lives in `AGENTS.md`.
**Rebase the relative links when copying §2 into `standards/`:** this design doc
lives in `docs/`, so its cross-references point up-and-over (`../standards/cli.md`,
`../standards/permissions.md`, etc.); inside `standards/tool-enable-disable.md`
those same-directory links become bare filenames again (`cli.md`,
`permissions.md`), and the PL-PP-1 link becomes
`../lang-rules/python/python-prohibited-patterns.md`.

### Scrub managed-CLAUDE.md references across `standards/`

Sweep the whole `standards/` tree and remove every reference that describes,
requires, or permits managed sections, markers, or content templates for a
user-owned `CLAUDE.md`. The standard must describe only the contract (import
line, tool-owned directory, `enable` / `disable`, required user guide). This is
CLAUDE.md-only — do **not** scrub Makefile managed-section references
(`punt auto makefile` stays). Known hits are enumerated in the per-file entries
below; the sweep must also catch any others (e.g. `readme.md`, `workflow.md`,
`agent-engineering.md`) added since.

### `standards/cli.md`

- § Command Layers → Layer 2 table and § Required Subcommands → `enable` /
  `disable`: the current text says enable "Creates/removes a config file at the
  repo root (e.g., `.biff`, `.quarry`)." Replace with the new deposit contract
  (deposit `.punt-labs/<tool>/`, write/delete the `enabled` marker, add/remove the
  canonical `@`-import line, additive `.claude/settings.json` entries) and a
  cross-reference to `tool-enable-disable.md`. State the enabled signal is the in-directory
  marker, not a repo-root dotfile.

### `standards/distribution.md`

- § "CLAUDE.md `@`-import Includes" (the managed-section + shared-reconcile
  block): the largest edit. Replace the `<!-- punt:mandatory-reading -->` managed
  section, the shared reconcile, and its invariant list with a pointer to
  `tool-enable-disable.md`. Retain only the still-true global-install specifics — a global
  tool writes `~/.punt-labs/<tool>/CLAUDE.md` and registers one bare
  `@~/.punt-labs/<tool>/CLAUDE.md` line at install — restated as a bare line, no
  marker block. Move the serialized/atomic/symlink/byte-preserving write contract
  into `tool-enable-disable.md` § 2.4 and cross-reference it.
- § "Optional phases" (via two-phase-install reference) Phase 2a wording:
  update "register its `@`-import" to the bare-line model.
- § Installation Scope (`init` verb, lines 429–437): reconcile `init` with
  `enable` per `tool-enable-disable.md` § 2.13 — `enable` owns activation (directory,
  marker, import line, hooks); `init` keeps only its distinct role of creating and
  populating the tool's repo config file. State they are distinct verbs, not
  duplicates, so the corpus does not ship two overlapping repo-setup commands.
- § Installation Scope → Per-repo config files table (`.biff`, `.quarry.toml`,
  `.beads/`): note the enabled signal is the `.punt-labs/<tool>/enabled` marker,
  not the config file; reconcile with filesystem.md and integration.md.

### `standards/filesystem.md`

- § Per-Project Activation (currently "sentinel file at the repo root, e.g.
  `.biff` … not under `~/.punt-labs/`"): replace with the
  `.punt-labs/<tool>/enabled` marker as the canonical per-repo enabled signal, and
  the `.punt-labs/<tool>/` directory as the tool's committed vendored subtree,
  superseding the bare repo-root sentinel dotfile. Keep the point that these live
  in the project, not under `~/.punt-labs/`.

### `standards/integration.md`

- § L0 Presence (lines 49–72) normatively defines the per-tool presence sentinels
  (`.biff`, `.vox/config.md`, `.lux/config.md`, `.quarry.toml`). Rewrite the L0
  presence check and its table to the new marker: presence/enablement is
  `.punt-labs/<tool>/enabled` (the `.beads/` directory row is the closest existing
  template for a directory-based marker). Update the `has_biff()` example to test
  the marker path, and cross-reference `tool-enable-disable.md`. Keep the L0 rule that
  presence checks are pure path-existence tests that fail silent when absent.

### `standards/hooks.md`

- § 3 Shell Script Pattern (config gate `[[ -f "$REPO_ROOT/.<tool>" ]]`) and the
  example in § 3 Rules: change the gate to
  `[ -f "$REPO_ROOT/.punt-labs/<tool>/enabled" ] || exit 0`.
- § 5 Required Hooks / § 8 Hook Registration: add a cross-reference to
  `tool-enable-disable.md` § 2.8 for repo-scoped hook deposit/removal via `enable` /
  `disable` and the deterministic value-match reversal.

### `standards/permissions.md`

- § 6 Plugin-Distributed Permissions: add a note that the same order-preserving
  `jq` merge and **exact value-match** removal (the `select(… index($r) | not)`
  pattern already at lines 366–378) is the mechanism `enable` / `disable` use for
  repo-scoped hook/config/permission entries, and that repo-scoped `enable` writes
  to `<repo>/.claude/settings.json` (not `~/.claude/settings.json`).
  Cross-reference `tool-enable-disable.md`. Do not introduce a tag schema — value-match is
  the contract.

### `standards/plugins.md`

- § Required Hooks / SessionStart: add one cross-reference clarifying that
  repo-scoped guidance and config are deposited by `<tool> enable`, not by the
  plugin SessionStart hook (which stays responsible for command deployment and
  MCP permission wildcards). No structural change; plugins.md does not itself
  describe CLAUDE.md injection.

### `standards/architecture.md`

- No change. The projection model is orthogonal; `enable` / `disable` is a
  CLI-surface behavior that fits under it unchanged.

### `AGENTS.md` (standards index)

- Add the `tool-enable-disable.md` entry.
- The index currently lists 13 of the 25 standards docs. Per the no-existing-issue
  rule, complete it: add every missing standard so the index matches
  `standards/*.md` one-for-one.
- Document the introduced-date convention (section 3) once, here, as the home of
  the meta-rule — including the forward-only, no-backfill rule.

### Introduced-date field — forward-only, no backfill

- **No mass edit of existing docs.** Do **not** add `**Introduced:**` to the 25
  existing standards. The field starts on docs created or normatively amended
  after the convention lands (section 3).
- The only doc that gets a date in this batch is the new
  `tool-enable-disable.md`, which carries its own `**Introduced:**` line as any
  new standard does.

### Docs-mission follow-ups (`patterns/`)

- `patterns/claude-md-injection.md`: rewrite to the bare-import model, or retire;
  it documents the retired marker/reconcile approach.
- `patterns/two-phase-install.md` Phase 2a bullet: update to the bare-line model.
- `patterns/doctor-checks.md` (line 32): the informational check currently reads
  "tool's `@`-import registered in the managed section." Reword to "import line
  present iff enabled" per the amended audit semantics (2.11); drop the
  managed-section reference and the `claude-md-injection.md` link.

### Code-mission follow-ups

- `src/punt_kit/auto.py`: delete `CLAUDE_SECTIONS` and the `claude` entry in
  `TARGETS`. Keep `parse_segments` / `merge_file` / `_MARKERS` / `render_section`
  — the `punt auto makefile` target still uses them (out of scope for this
  removal).
- `src/punt_kit/templates/auto/claude/*.j2`: delete. They rendered the retired
  managed sections; the `punt auto makefile` templates under
  `templates/auto/makefile/` stay.
- `punt` CLI: implement `punt enable` / `disable` per the standard, and the four
  audit checks (2.11). `punt enable` deposits punt's static user guide as
  `.punt-labs/punt/CLAUDE.md`; authoring that guide's content is a separate task,
  not a standards change.

---

## 8. Operator decisions — all four settled

All four §8 questions were ruled on by the operator; recorded here as settled and
folded into the design above.

1. **Filename and title — settled.** `standards/tool-enable-disable.md`, title
   **Tool Enable/Disable Standard** (operator's choice). All cross-references
   renamed; enable/disable vocabulary preferred over "activation" throughout.
2. **Enabled signal — settled.** Retire the repo-root sentinel dotfile; the single
   enabled signal is the in-directory marker `.punt-labs/<tool>/enabled` (the H1
   fix, § 2.7), which `disable` removes. Reconciled across cli.md, filesystem.md,
   hooks.md, integration.md.
3. **Introduced-date convention — settled and de-conflated.** It is a general
   standards-corpus convention, independent of this standard; its text lives in
   `AGENTS.md`, not in `tool-enable-disable.md` (which merely carries its own
   date). Section 3 states the independence explicitly.
4. **Backfill — settled: none.** Forward-only. Existing standards get no
   retroactive `**Introduced:**` date; the field starts on docs created or
   normatively amended after the convention lands. The git-archaeology and
   uniform-date options are dropped; the "every existing doc gets a date"
   change-list entry is replaced by the forward-only rule (§ 3, § 7).

## Open issue for the leader (not a design decision)

Removing `punt auto claude` drops the four per-repo rendered sections
(quality-gates, beads, standards-references, available-tooling) from repo
`CLAUDE.md` files. Per the operator ruling, their new home is out of scope for
this standard, and punt's user guide is not it. If that content is still wanted
per-repo, it needs a separate decision and vehicle — e.g. `/punt:init`
scaffolding a plain (unmanaged) section the user then owns, or leaving it to each
repo's hand-authored `CLAUDE.md`. Flagging as a gap for the leader to route;
this design does not solve it.
