# Tool Enable/Disable Standard

**Introduced:** 2026-07-19

How a tool turns its CLAUDE.md guidance composition on and off in a repo (and,
for global tools, on a machine): one bare `@`-import line in a user-owned host
file, one tool-owned `.punt-labs/<tool>/` directory, and the `enable` /
`disable` verbs. Section numbering follows the design this standard was
extracted from (`docs/claude-md-include-standard-design.md` § 2); external
cross-references cite these section numbers.

---

## 2.1 Core Principle

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

## 2.2 Ownership

| Path | Owner | Lifecycle |
|------|-------|-----------|
| `<repo>/CLAUDE.md`, `~/.claude/CLAUDE.md` | The user | Tool adds or removes one import line; every other byte is untouched |
| `<repo>/.punt-labs/<tool>/` | The tool | Deposited on `enable`, vendored zone overwritten wholesale on upgrade (config and local-convention zones untouched — § 7), left dormant on `disable` |
| `~/.punt-labs/<tool>/` | The tool | Deposited on `install` (global tools), vendored zone overwritten wholesale on upgrade (§ 7) |

Each tool owns its `.punt-labs/<tool>/` subtree completely. It rewrites the
subtree's **vendored zone** on enable/upgrade and never reads-modifies-merges
it: same tool version, identical output. Repo config is **not** an input to that
write and is never rewritten by it — enable/upgrade steps around the config and
local-convention zones (below).

This wholesale-overwrite/determinism contract is scoped to the subtree's
**vendored zone**; repo config, local-convention files (`local/`, `*.local*`),
and the `enabled` marker are carved out from it — see
[punt-labs-dir.md § 7](punt-labs-dir.md#7-the-punt-labstool-subtree-has-zones).

## 2.3 The `enable` / `disable` Convention

Every tool CLI with per-repo presence exposes two commands, run from inside a
repo. This extends the `enable` / `disable` entry in
[cli.md § Required Subcommands](cli.md#enable--disable).

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

## 2.4 Import Line Rules

- **Canonical import string.** The line is exactly `@.punt-labs/<tool>/CLAUDE.md`
  (repo) or `@~/.punt-labs/<tool>/CLAUDE.md` (user), with `<tool>` the CLI binary
  name. Forward slashes; no `./` prefix; no trailing slash; no leading or trailing
  whitespace; one physical line, no embedded newline. This exact string is what
  `enable` writes, what `disable` matches, and what `punt audit` greps — all 15
  CLIs must produce byte-identical lines.
- **One bare line, appended at end of file.** No heading, no marker, no comment.
- **Ensured separation.** If the host file does not end in a newline, add one
  before appending, so the import is never glued to the user's last line.
- **Idempotent by exact match, terminator-insensitive.** Presence is decided by
  matching the canonical line against each host line **net of its terminator** —
  strip the trailing `\r`, `\n`, or `\r\n` before comparing, so a CRLF host does
  not carry a spurious `\r` that defeats a byte-exact compare (which would make
  `enable` append duplicates and `disable` fail to remove). `enable` appends only
  if absent; `disable` removes every match (collapsing an accidental duplicate to
  zero). This match rule is content-level; the write path (below) stays
  byte-preserving of the file's existing line endings.
- **Top-level only; skip code blocks.** Claude Code resolves `@`-imports only at
  the top level, never inside a code block. Both the presence scan (`enable`) and
  the removal (`disable`) must ignore any matching line that is inside a fenced
  code block or an indented code block. Precise definition, so 15 implementations
  agree: a **fence delimiter** is a line whose first non-whitespace characters are
  three or more backticks (or three or more tildes), **optionally followed by an
  info string** (e.g. ` ```text `, ` ```markdown `) — the delimiter run need not
  be the whole line. A line is **inside a fenced block** if the number of
  preceding fence delimiters is odd; it is an **indented code block** line if it
  begins with a tab or four or more spaces. A line matching neither is top-level.
  `@`-imports and the canonical string are always written at column 0 with no info
  string, so they are top-level by construction.
- **Serialized, atomic, byte-preserving write.** The read-append-replace on the
  host file must be:
  - **Mutually exclusive — applies to every shared host file.** Hold an exclusive
    lock (`flock` on the target or a sibling lock file, or the platform
    equivalent) for the whole read-modify-write. This requirement governs **every
    shared host-file mutation in this standard** — the `CLAUDE.md` import line here
    *and* the `.claude/settings.json` entries in § 2.8 — since both are
    read-modify-write on a file other tools and invocations also touch. Atomic
    rename prevents a torn file; it does **not** prevent a lost update — two
    parallel `enable` runs each read the old bytes, write their change, and rename,
    and the second silently clobbers the first. The lock serializes them. (The old
    model relied on a stated single-writer assumption; the per-tool model drops it
    exactly where independent invocations become more likely, so the lock is
    mandatory, not optional.)
  - **Atomic.** Write a temp file in the target's own directory, then rename it
    over the target (atomic on POSIX; use the platform atomic-replace primitive).
    Never truncate-in-place.
  - **Byte-preserving, host EOL for the appended line.** Every byte outside the
    single import line is identical before and after, across LF, CRLF, and lone-CR
    endings. Read and write without newline translation (the language's
    universal-newline mode silently rewrites the user's endings). The line `enable`
    appends uses the **host file's existing EOL convention** (append `\r\n` on a
    CRLF file, `\n` on an LF file), so the tool's own line matches the surrounding
    endings and stays terminator-insensitively matchable on re-run.
  - **Symlink-resolving.** If the target is a symlink (dotfile managers do this),
    write the real target and preserve the link.
  - **Mode-preserving.** Keep an existing file's mode; a new file gets `0644`.
- **Canonical reference implementation.** `GlobalClaudeImports` in the **vox
  repo** (`punt-labs/vox`, `src/punt_vox/claude_md.py`) already satisfies the
  atomic / symlink / byte-preserving / deterministic contract for the global
  case. Port its correctness per tool (copy-not-symlink of the logic, each CLI in
  its own language) — this is distinct from a rejected shared-runtime writer:
  shared *correctness*, not a shared *process*. The one addition beyond vox today
  is the exclusive lock above.

## 2.5 Every tool ships a user-guide doc

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

## 2.6 Scope: repo versus user

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

**User-scope teardown is mandatory and symmetric with install.** The retired
shared reconcile pruned `~/.claude/CLAUDE.md` when a tool was removed; the bare
import model must not lose that. Install adds the user-scope line, so removal must
take it away: `<tool> uninstall` (or `disable --global`) MUST remove the
`@~/.punt-labs/<tool>/CLAUDE.md` line using the **same write contract as § 2.4** —
exclusive lock, exact-match, atomic, byte-preserving. The `~/.punt-labs/<tool>/`
directory then follows the same dormant rule as repo scope (2.9): the import line
goes, the vendored subtree stays unless the user purges it. Without this, an
uninstalled global tool leaves a dangling `@`-import that 404s at read time in
every session.

## 2.7 The enabled marker

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

## 2.8 Hooks and config

`enable` may register repo-scoped hooks or permissions. It may touch exactly one
file outside its own subtree — `<repo>/.claude/settings.json` — and only
additively. Because that file is shared with other tools and invocations, the
read-modify-write **must take the same exclusive lock as § 2.4** (the lock
requirement there covers every shared host-file mutation, `settings.json`
included); an unlocked merge has the identical lost-update race as an unlocked
import-line append.

- The tool computes a **deterministic set of entries** (the same inputs always
  produce the same rules — the wholesale-overwrite determinism of 2.2 guarantees
  this).
- `enable` merges that set with the order-preserving, idempotent `jq` pattern
  from [permissions.md § 6](permissions.md#6-plugin-distributed-permissions),
  adding only entries not already present.
- `disable` recomputes the identical set and removes those entries by **exact
  value-match** — the removal pattern permissions.md § 6 actually provides
  (`select(. as $r | $remove | index($r) | not)`). No tag schema is needed or
  implied; the deterministic entry set *is* the identity.
- Neither touches unrelated entries.

Most tools ship hooks through their marketplace plugin (global). Repo-scoped hook
deposit via `enable` is only for genuinely repo-scoped hook behavior.

## 2.9 `disable` is non-destructive

`disable` stops composition; it does not erase vendored data. It removes the
import line, deletes the `enabled` marker (2.7), and deregisters hooks, but leaves
the rest of `<repo>/.punt-labs/<tool>/` in place — the **dormant** state.
Rationale:

- The subtree is **tool-owned and repo-committed** (2.2): `enable` overwrites it
  wholesale, so user edits inside it are out of contract by design and are not a
  reason either to keep or to delete it. What dormancy actually preserves is the
  committed vendored content — the deposited guide and any config — which is
  git-tracked and git-recoverable. (That wholesale overwrite is the **vendored
  zone** only; repo config and local-convention files are carved out — see
  [punt-labs-dir.md § 7](punt-labs-dir.md#7-the-punt-labstool-subtree-has-zones).)
- **Deletion-on-toggle is surprising and asymmetric.** `enable` writes the
  subtree's vendored zone (repo config and local-convention files are carved out — see
  [punt-labs-dir.md § 7](punt-labs-dir.md#7-the-punt-labstool-subtree-has-zones));
  the symmetric inverse of *turning off* is removing the enabled signal and the
  import line, not erasing files. A toggle that deletes committed content is a
  much larger action than the user asked for.
- This matches the org rule to prefer `mv` over `rm` and never to delete what a
  tool did not just create — and here `disable` did not create the vendored
  content this run; `enable` did, on an earlier run.

A user who wants the tool fully gone deletes `<repo>/.punt-labs/<tool>/` manually,
or the tool offers `disable --purge`. Removal is deliberate, never a side effect
of a toggle.

## 2.10 `punt` follows the convention

`punt` is a tool like any other. `punt enable`, run in a repo, deposits
`<repo>/.punt-labs/punt/CLAUDE.md` — punt's own static user guide (how to drive
the `punt` CLI: `init`, `audit`, `reconcile`, and so on) — and adds
`@.punt-labs/punt/CLAUDE.md` to the repo `CLAUDE.md`. It is the same kind of
static user-guide doc every tool ships (2.5), not a per-repo rendered file.

`punt`'s deposited guide is **not** the new home for the four per-repo sections
the retired `punt auto claude` target rendered (quality gates, beads, standards
references, available tooling). Those were repo-specific dev-process content, not
a tool user guide; their disposition is out of scope for this standard.

## 2.11 What `punt audit` checks

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

## 2.12 Migration

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

### Sentinel migration (legacy `.biff`, `.quarry.toml` → `enabled` marker)

The legacy repo-root sentinel dotfile is retired **as a presence marker** in
favor of the in-directory `enabled` marker (2.7), which changes the L0 presence
contract in [integration.md](integration.md). A repo that still carries `.biff`
or `.quarry.toml` must not silently fail every peer presence check in the window
between the integration.md rewrite and each tool's re-enable. Forward-integration
closes the gap without a compat shim — but the migration must **never delete live
config**.

**Two classes of legacy sentinel, handled differently:**

| Class | Example | On migration |
|-------|---------|--------------|
| Pure presence sentinel — an empty or content-free marker whose only job was "this tool is here" | `.biff` when it carries no settings | Deleted, once `.punt-labs/<tool>/` + `enabled` are deposited |
| Sentinel-cum-config — a marker file that also holds live settings (roster, credentials, db name) | `.quarry.toml` | **Migrated, never deleted with content inside**: the tool either moves the settings into its owned location (e.g. `.punt-labs/<tool>/config.*`) and then removes the now-empty marker, or leaves the file in place and simply stops treating it as the presence signal. The tool owning the file decides which; neither path destroys live config. |

This reconciles with § 2.13 and
[distribution.md § Installation Scope](distribution.md#installation-scope), which
keep the tool's repo **config** file (`.beads/`, `.quarry.toml`, `.biff` when it
carries settings) as `init`'s artifact. Enablement stops *reading that file as
the presence marker*; it does not claim ownership of the config, and it never
deletes a file that still holds settings.

**Migration steps (per tool, on first run):**

- `enable` — or the tool's SessionStart hook — detects the legacy sentinel and,
  in one operation, deposits `.punt-labs/<tool>/` + the `enabled` marker, then
  applies the class rule above (delete a pure sentinel; migrate-then-clear or
  demote a config-bearing one). No separate migration command; the legacy sentinel
  stops being a *presence marker* on the tool's first post-adoption run.
- **Ordering dependency.** The integration.md L0 rewrite (peers now check the
  `enabled` marker) must land in the **same release train** as the tool releases
  that perform the migration, so no peer starts checking the new marker before
  the tools that write it have shipped.
- **`.beads/` needs no migration** — it is already a directory-form marker, not a
  dotfile, and is unaffected.

## 2.13 `enable` versus `init`

[distribution.md § Installation Scope](distribution.md#installation-scope)
defines `init` as the per-repo verb that writes a tool's repo config file
(`.biff`, `.quarry.toml`) and prompts for project-specific settings (team roster,
relay URL, database name). `enable` and `init` are **distinct roles**, not
duplicates:

| Verb | Job | Writes |
|------|-----|--------|
| `enable` / `disable` | Turn CLAUDE.md guidance composition and hooks on/off in this repo | `.punt-labs/<tool>/` (guide + `enabled` marker), the import line, additive `.claude/settings.json` entries |
| `init` | Create and populate the tool's repo config/state | The tool's repo config file (`.biff`, `.quarry.toml`, `.beads/`) |

The repo config file is **no longer the enabled signal** — the `enabled`
marker (2.7) is. A tool with both verbs runs `init` to configure and `enable` to
turn on; `enable` may call `init` when enabling requires config, but the two
concerns stay separate. Tools that used `init` *only* to drop an enabled
sentinel fold that into `enable` and retire the bare repo-root sentinel.

Those repo-root config files (`.biff`, `.quarry.toml`) move into the tool's
subtree config zone — see
[punt-labs-dir.md § 9](punt-labs-dir.md#9-migration) for the
config-into-subtree migration.
