# Tool Enable/Disable Standard

**Introduced:** 2026-07-19 · **Updated:** 2026-11-27

How a tool turns its CLAUDE.md guidance composition on and off in a repo: one
bare `@`-import line in the repo's `CLAUDE.md` (or, for one person,
`CLAUDE.local.md`), one tool-owned `.punt-labs/<tool>/` directory, and the
`enable` / `disable` verbs in two scopes: shared and personal. Section
numbering starts at 2.1; external cross-references cite these section numbers.

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
| `<repo>/CLAUDE.md` | The user | `enable` adds one import line, `disable` removes it; every other byte is untouched. `~/.claude/CLAUDE.md` is user-owned and no tool ever writes it |
| `<repo>/.punt-labs/<tool>/` | Zoned ([punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones)): tool (vendored + `enabled` marker), repo (config, including any file a daemon rewrites), user (local-convention) | Deposited on `enable` when absent, vendored zone overwritten wholesale only on `enable --refresh` (config and local-convention zones untouched), left dormant on `disable` |
| `~/.punt-labs/<tool>/` | Zoned: tool (machine config/state), user (local-convention) | Holds machine-scoped config and state written by `install`; carries no imported guide and no import line |

Each tool owns the **vendored zone** (and the `enabled` marker) of its
`.punt-labs/<tool>/` subtree — not the whole subtree: the config zone is
repo-owned and the local-convention zone is user-owned
([punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones)).
The tool rewrites the vendored zone only on `enable --refresh` (§2.5) and never
reads-modifies-merges it: same tool version, identical output. Repo config is
**not** an input to that write and is never rewritten by it — enable/upgrade
steps around the config and local-convention zones (below), and that includes
a config file a running daemon rewrites (`vox.md`): git status is
naming-determined only ([punt-labs-dir.md PLD-4](punt-labs-dir.md#pld-4-naming-determines-the-shared-versus-local-boundary)),
never write-cadence-determined, so a daemon-mutated file stays a tracked
Config-zone file like any other.

This wholesale-overwrite/determinism contract is scoped to the subtree's
**vendored zone**; repo config, local-convention files
(`local/`, `*.local`, `*.local.*`), and the `enabled` marker are carved out from
it — see
[punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones).

Everything a tool commits into this subtree — the deposited guide, repo config,
the ethos registry, `missions-closed/` exports, and vended agent content —
carries no incidental third-party PII and no profanity before it enters git.
[punt-labs-dir.md PLD-8](punt-labs-dir.md#pld-8-shared-records-are-safe-to-distribute)
owns that contract and defines exactly what is scrubbed versus what a record is
meant to carry (an identity record's own declared fields are in scope for its
tool, not stripped). The gitignored local zone and the home tree are out of
scope — they are never committed.

## 2.3 The `enable` / `disable` Convention

Every tool CLI with per-repo presence exposes two commands, run from inside a
repo. See [CLI-7](cli.md#cli-7-apply-the-platforms-naming-and-setup-boundaries)
for the distinction between machine setup and repository integration.

**`enable` and `disable` are their own tier: per-repo tool
integration.** They are neither machine setup nor
client-vocabulary (the noun-first product surface) — enablement is a
distinct concern, orthogonal to that split, and every Punt Labs tool
implements it across the surfaces this standard defines: CLI + MCP +
slash + library, per vox's pattern
(`vox enable`/`vox disable` on the CLI, `mic:enablement
action="enable"` on MCP, `/vox enable` as a slash command) — see
§2.14 for the full surface mapping.

**Vocabulary is `enable` / `disable`.** The two verbs are
the fleet-wide vocabulary for turning a tool on and off, at both surfaces (§2.14).
A boolean `y|n` / `true|false` toggle is **not** permitted for enablement: it
reads as a per-user preference, it splits into two vocabularies (one in the
command, one in a config file), and it invites an auto-enable shortcut (below).
`enable` writes a marker; `disable` removes it; the only other recorded state is
the committed opt-out (§2.7), and there is no boolean. (Per-*user* preferences unrelated to enablement — e.g. a "do not contact
me" flag — may keep their own `y|n` verb; that is a separate layer, see §2.14.)

**No auto-enable.** A tool never turns itself on as a side effect of first use.
Enablement is explicit: the marker exists because a human ran `enable` and
committed it, never because the tool inferred intent. A tool invoked in a repo
where its marker is absent is a graceful no-op, not a trigger to self-enable.
Automation counts as first use: agent start, a SessionStart hook, an installer,
a plugin update or a nightly job never enables a tool in a repo where it is
absent, dormant or opted out; converting a legacy sentinel to the marker
(§2.12) records an existing enablement and is not enabling. Automation that re-runs `enable` in a repo where
the tool is already enabled must leave the bytes unchanged (no-op writes,
below) and skip any tool whose opt-out exists (§2.7).

**Two scopes: shared and personal.** `enable` and `disable` take a scope, named
as Claude Code names its settings scopes:

| Scope | Flag | Affects | Marker | Guide | Import line, host file | Grants |
|-------|------|---------|--------|-------|------------------------|--------|
| Shared | `--scope project` | everyone who clones | `.punt-labs/<tool>/enabled` (committed) | `.punt-labs/<tool>/CLAUDE.md` (committed) | `@.punt-labs/<tool>/CLAUDE.md` in `<repo>/CLAUDE.md` | `.claude/settings.json` |
| Personal | `--scope local` (default) | this checkout only | `.punt-labs/local/<tool>/enabled` (ignored) | `.punt-labs/local/<tool>/CLAUDE.md` (ignored) | `@.punt-labs/local/<tool>/CLAUDE.md` in `<repo>/CLAUDE.local.md` | `.claude/settings.local.json` |

The default is `local`. A bare `<tool> enable` changes no tracked file; only a
deliberate `--scope project` edits team policy (`CLAUDE.md`,
`.claude/settings.json`, the committed marker), and that change lands through a
PR. Personal scope writes only paths the gitignore baseline (§2.6) ignores:
before writing, the tool confirms each target is ignored and untracked
(`git check-ignore`, `git ls-files`) and refuses, naming the file, if one is not.
The check applies to the resolved path too: a personal target that is a symlink
resolving outside the ignored paths (for example `CLAUDE.local.md` linked to
`CLAUDE.md`) is refused.

**`enable`** — idempotent; never an upgrade (see `--refresh`):

1. Refuse if the opt-out `.punt-labs/<tool>/opt-out` exists (§2.7): exit
   non-zero, name the file, write nothing.
2. Deposit the scope's guide **only if it is absent** (and any other files the
   tool ships, under the same rule). An existing guide is left alone even when
   the installed tool ships different bytes.
3. Write the scope's marker (see 2.7).
4. Add the scope's import line to the scope's host file in its sorted position
   (§2.4) if absent. Never add it twice.
5. Add the tool's permission entries to the scope's settings file in their
   sorted position (§2.8).
6. Shared scope only: optionally register repo-scoped hooks, config and a
   tool-owned CI workflow (see 2.8). Personal scope registers none.

Personal `enable` in a repo where the shared marker is present writes no
personal marker, guide, import or grant; it only deletes
`.punt-labs/local/<tool>/disabled` if present, because the shared guide, import
and grants already cover the checkout. If the project later disables the tool,
the checkout is off until the person runs personal `enable` again. Personal
`enable` always deletes `.punt-labs/local/<tool>/disabled`, in either case.

**`disable`**:

1. Remove the scope's import line from the scope's host file.
2. Delete the scope's marker.
3. Remove the permission entries, hooks and config the scope added.
4. Leave the rest of `.punt-labs/<tool>/` (and `.punt-labs/local/<tool>/`) in
   place, dormant (see 2.9).
5. Personal scope, when the shared marker is present: write
   `.punt-labs/local/<tool>/disabled`, which turns the tool off at runtime in
   this checkout (§2.15). It cannot unload the shared import or withdraw shared
   grants (Claude Code merges permission arrays across scopes, and
   `CLAUDE.local.md` cannot cancel an import), so `status` says the shared guide
   still loads.
6. `disable --scope project --opt-out` also writes the committed opt-out
   (§2.7), in the same change that removes the shared marker.

**`enable --refresh`** is the one path that rewrites a deposited guide or any
other vendored file: it makes the scope's vendored zone match the installed
tool, writing each shipped file whose bytes differ and removing vendored files
the installed tool no longer ships. Every replacement and removal follows
[punt-labs-dir.md PLD-9](punt-labs-dir.md#pld-9-replacement-requires-verifiable-ownership):
a path the previous inventory does not list aborts the refresh with no writes.
In personal scope each write and each removal also passes the ignored-and-
untracked check above. Config and local-convention zones are untouched.
In shared scope it is the reviewable upgrade, one diff in one PR. It never runs
as a side effect of SessionStart, `install`, `uninstall`, a plugin update or
any other verb (§2.5).

**No-op writes.** When the result of any step would equal the file's current
bytes, the tool writes nothing: no temporary file, no rename, no mode or mtime
change. This covers every file this standard names — guides, markers, host
files, settings files and the CI workflow — so repeating `enable` or `disable`
leaves `git status --porcelain` empty.

## 2.4 Import Line Rules

- **Canonical import string.** The line is exactly `@.punt-labs/<tool>/CLAUDE.md`,
  repo-relative, with `<tool>` the CLI binary name. Forward slashes; no `./` prefix; no trailing slash; no leading or trailing
  whitespace; one physical line, no embedded newline. This exact string is what
  `enable` writes, what `disable` matches, and what `punt repo audit` greps — all 15
  CLIs must produce byte-identical lines.
- **One bare line, in its sorted position.** No heading, no marker, no comment.
- **Sorted position, never reordered.** Tool-owned import lines (top-level lines
  that are a canonical `@.punt-labs/<tool>/CLAUDE.md` or
  `@.punt-labs/local/<tool>/CLAUDE.md` import) are kept in ascending code-point
  order. `enable` inserts the new line immediately before the first existing
  tool-owned import line that sorts after it; if none does, immediately after
  the last tool-owned import line; if the host file has none, at the end of the
  file. It never moves an existing line, human or tool-owned. From a host file
  whose tool-owned lines are already sorted (an audit check, §2.11), every
  enable order produces the same bytes.
- **Ensured separation.** If the host file does not end in a newline, add one
  before inserting at the end, so the import is never glued to the user's last
  line.
- **Idempotent by exact match, terminator-insensitive.** Presence is decided by
  matching the canonical line against each host line **net of its terminator** —
  strip the trailing `\r`, `\n`, or `\r\n` before comparing, so a CRLF host does
  not carry a spurious `\r` that defeats a byte-exact compare (which would make
  `enable` append duplicates and `disable` fail to remove). `enable` inserts only
  if absent; `disable` removes every match (collapsing an accidental duplicate to
  zero). This match rule is content-level; the write path (below) stays
  byte-preserving of the file's existing line endings.
- **Top-level only; skip code blocks.** Claude Code resolves `@`-imports only at
  the top level, never inside a code block. Both the presence scan (`enable`) and
  the removal (`disable`) must ignore any matching line that is inside a fenced
  code block or an indented code block. Precise definition, so 15 implementations
  agree (reference: `ClaudeMdImport` in `punt-labs/biff`):
  - A **fence delimiter** is a **non-indented** line — at most three leading
    spaces, no leading tab (CommonMark) — whose first non-blank characters are a
    run of three or more of a single marker character (backticks or tildes),
    **optionally followed by an info string** (e.g. ` ```text `, ` ```markdown `)
    — the delimiter run need not be the whole line. A line indented by a tab or
    four or more spaces is an inert indented-code line and **never a delimiter**,
    even when its first non-whitespace characters are ` ``` ` or `~~~` — treating
    it as one toggles block state and flips the classification of every following
    line (an indented run inside a real fenced block would otherwise expose the
    block's remainder as top level).
  - Fenced blocks are **balanced pairs**. A delimiter opens a block; the block
    closes only on a later delimiter of the **same marker character** whose run
    is **at least as long** as the opener's — a ` ``` ` block cannot be closed by
    `~~~` or by a shorter run; a mismatched or shorter delimiter inside the block
    is content, not a close. Blocks do not nest: once open, every line up to the
    matching close is content.
  - A line is **inside a fenced block** iff it lies after an opener and at or
    before that opener's matching close (the content and the closing delimiter
    are inside; the opening delimiter is not). An **unterminated opener runs to
    the end of the file**, as in CommonMark: Claude Code resolves `@`-imports
    from its Markdown lexer's tokens and skips code tokens, and that lexer
    treats a fence that never closes as code through EOF, so an import after it
    loads nothing. An import **before** the dangling opener is unaffected.
    `enable` must therefore refuse — before granting any rule — when the import
    is absent and the file ends inside an open fence, instead of appending an
    inert line and reporting success. (The naive "odd count of preceding
    delimiters" rule is still wrong: a balanced pair above the import must not
    flip its classification.)
  - A line is an **indented code block** line if it begins with a tab or four or
    more spaces. A line matching neither fenced-inside nor indented is top-level.
    `@`-imports and the canonical string are always written at column 0 with no
    info string, so they are top-level unless a fence above them is open.
- **Serialized, atomic, byte-preserving write.** The read-append-replace on the
  host file must be:
  - **Mutually exclusive — one mandated sibling lock, every shared host file.**
    Hold an exclusive lock (`flock`, or the platform equivalent) for the whole
    read-modify-write. The lock file is the sibling
    `.<host-file-name>.punt-import.lock` in the host file's own directory — for
    `<repo>/CLAUDE.md`, exactly `<repo>/.CLAUDE.md.punt-import.lock`. That
    name is mandated and **tool-agnostic by requirement, not by taste**: vox,
    quarry, and biff all mutate the same `<repo>/CLAUDE.md` when each is enabled
    in the same repo (§ 2.6), so a per-tool lock name
    (`.CLAUDE.md.<tool>-import.lock`) serializes only a tool against itself and
    leaves the cross-tool lost update in place — all 15 CLIs must take the
    identical lock. Locking the **target itself is forbidden**: the
    atomic rename below replaces the target's inode, so a lock held on the target
    travels with the dead inode and the next writer serializes against nothing.
    This requirement governs **every shared host-file mutation in this standard**
    — the `CLAUDE.md` import line here *and* the `.claude/settings.json` entries
    in § 2.8 (sibling lock `.settings.json.punt-import.lock`, same rule) — since
    both are read-modify-write on a file other tools and invocations also touch.
    Atomic rename prevents a torn file; it does **not** prevent a lost update —
    two parallel `enable` runs each read the old bytes, write their change, and
    rename, and the second silently clobbers the first. The lock serializes them.
    (There is no single-writer assumption: each tool is an independent
    invocation against the same host file, so the lock is mandatory, not
    optional.)
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
- **Canonical reference implementation.** `ClaudeMdImport` in the **biff repo**
  (`punt-labs/biff`, `src/biff/claude_md.py`) implements this full
  contract for the bare-line model — balanced-pair fence semantics, the shared
  sibling lock, and the atomic / symlink-resolving / byte-preserving /
  mode-preserving write; vox's `ClaudeMdImport` (`punt-labs/vox`,
  `src/punt_vox/claude_md.py`) is the same contract in a second tool. An
  implementation carries no managed-section markers (§ 2.1). Port the
  correctness per tool (copy-not-symlink of the logic, each CLI in its own
  language) — this is distinct from a rejected shared-runtime writer: shared
  *correctness*, not a shared *process*.

## 2.5 Every tool ships a user-guide doc

**Every tool MUST ship a user-guide `CLAUDE.md`, deposited by `enable` into
the scope's guide path (§2.3) — `<repo>/.punt-labs/<tool>/CLAUDE.md` shared,
`<repo>/.punt-labs/local/<tool>/CLAUDE.md` personal.** It is the
tool's agent-facing manual — how an agent or user *drives* the tool: slash
commands, auto-behaviors, tips, gotchas. It is not the tool repo's developer
`CLAUDE.md` and not a reference dump. Precedent: vox's deposited
`<repo>/.punt-labs/vox/CLAUDE.md`, whose opening line is "how an *agent* drives
vox — not how to develop vox itself."

The doc is **static content shipped with the tool**. It needs no per-repo
localization or rendering — the same guide is deposited everywhere. How the tool
produces or stores that content is an implementation detail this standard stays
silent on.

The doc loads fully into every session that imports it, so keep it usage
guidance, not an exhaustive reference. Keep imports shallow: Claude Code resolves
`@`-imports recursively only to a bounded depth, so do not chain deep import
trees from the tool doc.

**A deposited guide is a pinned copy; only a refresh changes it.** Once
deposited, a guide changes only through `<tool> enable --refresh` (§2.3).
SessionStart, `install`, `uninstall`, `upgrade`, `doctor`, a plugin update and
a repeated `enable` never rewrite it, so a different tool version on another
machine leaves the committed guide alone. `status` and `doctor` may
report that the installed guide differs from the deposited one, as information;
they never rewrite it.

## 2.6 Scope: shared and personal, both in the repo

There are two layers, both inside the checkout:

| Layer | Host file | Tracked | Written by | Import line |
|-------|-----------|---------|-----------|-------------|
| Shared | `<repo>/CLAUDE.md` | committed | `<tool> enable --scope project` | `@.punt-labs/<tool>/CLAUDE.md` |
| Personal | `<repo>/CLAUDE.local.md` | ignored | `<tool> enable` (`--scope local`) | `@.punt-labs/local/<tool>/CLAUDE.md` |

`enable` is the **sole** path that deposits a guide and writes an import line,
and it writes the repo `CLAUDE.md` (shared) or `CLAUDE.local.md` (personal). `install` installs software only (the
MCP server, binaries, models, data directories); it deposits no guide and writes
no import line, and it never touches a `CLAUDE.md` (§2.3, §2.5). There is no
user-scope import: `~/.claude/CLAUDE.md` carries no tool guides, and no guide is
deposited at `~/.punt-labs/<tool>/CLAUDE.md`.

Repo scope is correct for every real deployment. A flat single repo gets the
guide via one `enable`; the guide travels with the repo, so a contributor who
clones gets it through the repo `CLAUDE.md` import without installing the tool
globally; and a non-Claude agent that ignores `@`-imports is unaffected either
way. The one residual duplication — a parent and a child `CLAUDE.md` both loaded
in a nested checkout, both enabling the same tool — is specific to the Punt Labs
metarepo and is solved in metarepo config, never by bending the standard toward a
global import.

**No user-scope import to tear down.** Forward integration, no compatibility shim
([PL-PP-1](../lang-rules/python/python-prohibited-patterns.md)): because
`install` never writes `~/.claude/CLAUDE.md`, there is nothing for `uninstall` to
remove there. A `@~/.punt-labs/<tool>/CLAUDE.md` line found in that file is
stripped **opportunistically** — on
the next `enable` or `uninstall` run for that tool — under the **same write
contract as § 2.4** (exclusive lock, exact-match, atomic, byte-preserving). The
strip is a migration convenience, not an enforced invariant: the repo-scoped
audit (§ 2.11) does not scan `~/.claude/CLAUDE.md`, so a user who never re-runs
either verb keeps the stale line until they do. No tool writes that file, so no
*new* user-scope import is ever created.

**Gitignore baseline.** Personal scope depends on these paths being ignored, so
every repo with a Punt Labs tool carries them in its root `.gitignore`:

```gitignore
.punt-labs/**/*.local.*
.punt-labs/local/
CLAUDE.local.md
.claude/settings.local.json
.*.punt-import.lock
```

The lock pattern covers the § 2.4 sibling locks (`.CLAUDE.md.punt-import.lock`,
`.CLAUDE.local.md.punt-import.lock`, `.claude/.settings.json.punt-import.lock`,
`.claude/.settings.local.json.punt-import.lock`). An ignore rule does not
untrack a file: a lock or personal file already tracked is removed from the
index with `git rm --cached` in a reviewed change. Committed team inputs (the
shared marker, guide, `.punt-labs/<tool>/config.*`) stay tracked.

## 2.7 The enabled marker

### Shared marker

The tool is **enabled for the project** when the marker file
`<repo>/.punt-labs/<tool>/enabled` exists. `enable` writes it; `disable` deletes
it. This is a distinct signal from directory presence: the directory can persist
(dormant vendored content) after `disable`, so directory-presence cannot mean
"enabled." The marker lives inside the tool's own subtree, so `disable` removes
it without touching anything the tool did not just create.

**The marker is committed — enablement is per-repo policy, not per-user
preference.** The marker is a git-tracked file (it is carved out of the
vendored-zone overwrite, §2.2, but it is *not* gitignored — unlike
local-convention files, §2.9). It travels with the repo: a project-level tool
(biff, quarry, ethos) is a collaboration/knowledge capability that is either on
for the whole project or off for it, so whether it is enabled is a property of
the repo that every contributor who clones — and has the tool installed —
shares. Committing the marker makes that decision reviewable in a PR and
identical for the whole team, with no hidden per-machine divergence. The
personal marker (below) does not replace it: a gitignored flag as the *only*
enablement would leave a fresh clone off for everyone and re-litigate the
decision on each machine. Genuinely per-*user* preferences (e.g. "do not contact me right now")
are a separate, local/gitignored layer — see §2.14.

### Personal marker and personal off

`<repo>/.punt-labs/local/<tool>/enabled`, written by personal `enable`, turns
the tool on in this checkout only. `<repo>/.punt-labs/local/<tool>/disabled`,
written by personal `disable` in a project-enabled repo, turns it off in this
checkout only. Both are ignored (§2.6) and never travel in a PR.

### Committed opt-out

`<repo>/.punt-labs/<tool>/opt-out` records that the project decided the tool
stays off — for example, the Punt Labs meta-repo keeping ethos off because its
child repos load it. It is committed and reviewed like the marker. Its content
is an optional one-line reason, never parsed. While it exists:

- `enable` in either scope refuses (§2.3): exit non-zero, nothing written.
- Automation — agent start, SessionStart, installers, `punt enable <tool>`,
  convergence jobs — skips the tool and exits 0.
- Hooks, MCP servers and daemons treat the tool as off (§2.15).

It never coexists with the shared marker: `disable --scope project --opt-out`
removes the marker and writes the opt-out in one change. Only a person lifts
it, by deleting the file in a PR or with
`enable --scope project --clear-opt-out`, which deletes it and enables in the
same change. Automation never passes `--clear-opt-out`.

### Effective state

The tool is **on** in a checkout when no opt-out and no personal `disabled`
marker exists, and the shared or the personal `enabled` marker does:

| State | Shared `enabled` | Personal `enabled` | `opt-out` | Personal `disabled` | On |
|-------|------------------|--------------------|-----------|---------------------|----|
| Enabled for the project | present | absent | absent | absent | yes |
| Enabled for one person | absent | present | absent | absent | yes |
| Off for one person | present | absent | absent | present | no |
| Dormant (disabled) | absent | absent | absent | n/a | no |
| Opted out | absent | absent | present | n/a | no |
| Absent (no directory) | absent | absent | absent | n/a | no |

Hook shell gates test effective state, and also confirm the tool is installed,
so a clone of an enabled repo on a machine *without* the tool is a graceful
no-op rather than a "command not found" error (the §2.11 "no stale enabled
tools" invariant, at gate time):

```bash
P="$REPO_ROOT/.punt-labs"
[ -f "$P/<tool>/opt-out" ] && exit 0
[ -f "$P/local/<tool>/disabled" ] && exit 0
[ -f "$P/<tool>/enabled" ] || [ -f "$P/local/<tool>/enabled" ] || exit 0
command -v <tool> >/dev/null 2>&1 || exit 0
```

This marker is the one presence signal; no repo-root sentinel is, whatever
shape it takes —
a settings dotfile, a config-bearing root directory, or a bare presence marker
([punt's compatibility reference](../docs/repo-layout.md#compatibility-inventory)
classifies legacy shapes): one file, inside the
tool's directory (plus its personal counterpart under `.punt-labs/local/`),
that both hook gates and `punt repo audit` read.

## 2.8 Hooks and config

`enable` may register repo-scoped hooks or permissions. Its primary file outside
its own subtree is the scope's settings file — `<repo>/.claude/settings.json`
for shared scope, `<repo>/.claude/settings.local.json` for personal scope;
personal scope never edits `settings.json` — touched only additively (a
tool-owned CI workflow file is the one further exception — see the carve-out at
the end of this section). Because that file is shared with other tools and invocations, the
read-modify-write **must take the same exclusive lock as § 2.4** (the lock
requirement there covers every shared host-file mutation, `settings.json`
included); an unlocked merge has the identical lost-update race as an unlocked
import-line append.

- The tool computes a **deterministic set of entries** (the same inputs always
  produce the same rules — the wholesale-overwrite determinism of 2.2 guarantees
  this).
- `enable` adds only entries not already present, each in its **sorted
  position**: immediately before the first existing entry in the same array
  that sorts after it (code-point order), or at the end if none does. It never
  moves or rewrites an existing entry, human or tool-owned, and writes nothing
  when no entry is missing (§2.3). From an array whose entries are sorted, every
  tool order produces the same bytes;
  [permissions.md § 6](permissions.md#6-plugin-distributed-permissions) gives
  the `jq` form.
- Personal scope grants the same set in `settings.local.json`. Claude Code
  merges permission arrays across scopes, so personal `disable` removes only
  the personal entries; it cannot withdraw a shared grant.
- `disable` recomputes the identical set and removes those entries by **exact
  value-match** — the removal pattern permissions.md § 6 actually provides
  (`select(. as $r | $remove | index($r) | not)`). No tag schema is needed or
  implied; the deterministic entry set *is* the identity. Exact value-match
  is safe because a permission value lives in exactly one place: either in
  the [permissions.md § 3](permissions.md#3-required-allow-rules) baseline or
  in exactly one tool's `enable` set, never both. A baseline value is never in
  an `enable` set, so `disable` cannot remove one; no author attribution is
  needed, and a flat string array carries none.
- Neither touches unrelated entries.
- For permissions the set is the tool's whole production surface, as a broad
  allow per surface plus exact `ask` carve-outs for unsafe operations: its CLI
  (`punt` excepted, 2.10), its MCP server wildcard as Claude Code names it
  (`mcp__plugin_<plugin>_<server>__*` for a plugin-bundled server,
  `mcp__<name>__*` for one the tool registers natively), and
  `Skill(<plugin>:*)`, never a `-dev` rule. The table, and what counts as
  unsafe, is in
  [permissions.md § 6](permissions.md#6-plugin-distributed-permissions)
  principle 3. `disable` removes the same `allow` and `ask` values.

Most tools ship hooks through their marketplace plugin (global). Repo-scoped hook
deposit via `enable` is only for genuinely repo-scoped hook behavior, and only
in shared scope.

**Carve-out: tool-owned CI workflow files.** Beyond `<repo>/.claude/settings.json`,
shared-scope `enable` may own and install a CI workflow file it fully owns —
`<repo>/.github/workflows/<tool>-notify.yml` — when the tool's behavior requires
a committed GitHub Actions workflow. biff's `enable` installs
`.github/workflows/biff-notify.yml` (and `disable` removes it), the workflow that
drives `/biff:wall`-on-CI-failure notifications (biff decision B3). This is a
second file outside the subtree, held to the same discipline as `settings.json`:
the tool owns the file wholesale (deterministic render, `enable` writes it,
`disable` removes it), touches nothing else under `.github/`, and never edits a
workflow it does not own. Because that workflow runs in the repo's CI with its
token and secrets, the rendered file must: declare a least-privilege
`permissions:` block (only the scopes it needs, never the default write-all);
pin every third-party action to a commit SHA, not a floating tag; and `enable`
must refuse to overwrite a file already present at that path whose content is
not the tool's own current rendered output, unless the operator passes an
explicit override — so a user-authored or tampered workflow is never silently
replaced.

## 2.9 `disable` is non-destructive

`disable` stops composition; it does not erase vendored data. It removes the
import line, deletes the `enabled` marker (2.7), and deregisters hooks, but leaves
the rest of `<repo>/.punt-labs/<tool>/` in place — the **dormant** state.
Personal `disable` likewise leaves `<repo>/.punt-labs/local/<tool>/` in place.
Rationale:

- Ownership and overwrite scope: [PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones).
- **Deletion-on-toggle is surprising and asymmetric.** `enable` writes the
  subtree's vendored zone (repo config and local-convention files are carved
  out — see
  [punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones));
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
Its permission set is `Skill(punt:*)` plus `ask` carve-outs only; `Bash(punt:*)` is
the permissions.md § 3 baseline, because `punt repo init` scaffolds that file and
must run unprompted from the first scaffold.

`punt`'s deposited guide is **not** a home for repo-specific dev-process
content — quality gates, issue tracking, standards references, available tooling. That
is not a tool user guide; where such content lives is out of scope for this
standard.

## 2.11 What `punt repo audit` checks

The checks key on the markers (2.7), not on directory presence, so a dormant
tool is not flagged. They run for every tool directory under `.punt-labs/`, not
only punt's own.

- **Import present iff enabled, per scope.** For every `<repo>/.punt-labs/<tool>/`
  whose shared `enabled` marker is present, the repo `CLAUDE.md` contains
  exactly one `@.punt-labs/<tool>/CLAUDE.md` line; for every tool whose shared
  marker is absent (dormant, opted out or gone), that line is absent. The same
  holds for the personal marker and `@.punt-labs/local/<tool>/CLAUDE.md` in
  `CLAUDE.local.md`; a personal marker with no `CLAUDE.local.md` fails as a
  missing import. This is the load-bearing
  biconditional: enabled ⟺ import line, in each scope.
- **Opt-out is exclusive.** No tool has both `opt-out` and the shared `enabled`
  marker, and an opted-out tool has no shared import line and no shared grants.
- **Sorted.** Tool-owned import lines in each host file are in ascending
  code-point order relative to one another (§2.4); human lines are not checked.
  A settings array that is not in ascending code-point order is a warning, not
  a failure: insertion (§2.8) is order-independent only on a sorted array, and
  permission order carries no meaning in Claude Code, so a one-time sort in a
  reviewed PR fixes it.
- **Personal paths are ignored.** Every path in the gitignore baseline (§2.6) is
  ignored (`git check-ignore`), and none is tracked
  (`git ls-files -ci --exclude-standard`); a tracked lock file fails.
- **No orphan imports.** No `@.punt-labs/<tool>/CLAUDE.md` line without a
  corresponding `.punt-labs/<tool>/CLAUDE.md` file, and no
  `@.punt-labs/local/<tool>/CLAUDE.md` line without
  `.punt-labs/local/<tool>/CLAUDE.md` (hard fail — the import will
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

- A tool's guidance lives in `<repo>/.punt-labs/<tool>/CLAUDE.md` and reaches
  the host file only through the bare repo import line `enable` writes. A
  marker block a tool once injected into a `CLAUDE.md` is content to move
  there and a block to delete, in one release — never a block to keep
  rendering. A user-scope `@~/.punt-labs/<tool>/CLAUDE.md` line is stripped on
  the next `enable` or `uninstall` (§2.6) — no guide and no import survive at
  user scope.
- No tool renders managed sections into a user-owned `CLAUDE.md`, and `punt`
  has no target or section registry that does. `punt`'s deposited file is
  punt's user guide (2.10), not a home for that content. Makefile marker
  sections (`punt repo seed makefile`) are a separate mechanism and **out of
  scope** here — this rule is CLAUDE.md-only.
- A `punt:begin` / `punt:end` marker section found in a repo `CLAUDE.md` is
  content to delete, leaving the user's prose plus bare import lines.
  Makefile marker sections are untouched.

### Scope split migration (shared and personal enable)

Repos enabled before the scope split stay enabled: every marker, guide, import
and grant that `enable` wrote was shared scope, so none moves. What changes:

- A bare `<tool> enable` now means personal scope. Scripts, playbooks and docs
  that enable a tool for a team pass `--scope project`. A tool that does not
  offer `--scope`, its bare `enable` is shared scope, and its README says so.
- A loop that runs `<tool> enable` for every tool at agent start is removed, or
  limited to repos where the tool is already enabled, and honors the opt-out;
  under the no-op rule (§2.3) it then changes no bytes.
- A repo that turned a tool off by hand (a commented-out import, missing
  grants) records that with `disable --scope project --opt-out`.
- The first shared `enable` after the split may sort tool-owned import lines
  and permission entries once, in a reviewed PR; after that, insertion keeps
  them sorted.
- Personal preferences a tool kept in a tracked file (a display or mute flag in
  `.punt-labs/<tool>/*.md` or `.punt-labs/lux.md`) move to an ignored
  `*.local.*` file (§2.14).

### Sentinel migration (legacy root sentinel → `enabled` marker)

The in-directory `enabled` marker (2.7) is the presence marker; a repo-root
sentinel is not, and the L0 presence contract in
[integration.md](integration.md) reads the marker. A repo that carries a
legacy sentinel — dotfile or directory; every shape is in scope
([punt-labs-dir.md PLD-1](punt-labs-dir.md#pld-1-shared-repository-data-has-a-declared-root)) — must not
silently fail every peer presence check between the peer's switch to the
marker and the tool's `enable` in that repo. Forward-integration closes
the gap without a compat shim — but the migration must **never delete live
config or live settings**.

Legacy content classes, preservation and destinations: [PLD-10](punt-labs-dir.md#pld-10-relocation-preserves-meaning-and-content) and [compatibility reference](../docs/repo-layout.md#compatibility-inventory).

**Migration steps (per tool, on first run):**

- `enable` — or the tool's SessionStart hook — detects the legacy sentinel and,
  in one operation, deposits `.punt-labs/<tool>/` + the `enabled` marker, then
  applies the matching class rule above (delete a pure sentinel; migrate-then-clear
  a config-bearing one, human-set or daemon-rewritten, into the config zone;
  move a runtime-state directory into the local zone). No separate migration
  command; the legacy sentinel ceases to be a *presence marker* on the tool's
  first run in the repo.
- **Ordering within that one operation: detect-and-move the legacy source
  before any enable-time write to its destination, never after.** A tool
  whose own `enable` writes a Config-zone field it owns (lux's `display`,
  [punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones))
  must check for and move a legacy source (`.lux/config.md`) **first** — if
  `enable`'s ordinary deposit step writes the destination
  ([canonical path](punt-labs-dir.md#pld-1-shared-repository-data-has-a-declared-root)) before the legacy source is moved, that write
  itself creates the destination, and [PLD-10](punt-labs-dir.md#pld-10-relocation-preserves-meaning-and-content)'s
  destination-collision rule then makes the required move fail permanently
  on every subsequent run. There is no case where writing the destination
  first is correct: detect, move, delete the empty legacy source, *then* let
  the tool's own logic read or write the now-migrated file.
- **Ordering dependency.** A peer's switch to checking the `enabled` marker
  (integration.md L0) lands in the **same release train** as the tool release
  that performs the migration, so no peer checks the marker before the tool
  that writes it has shipped.

## 2.13 `enable` versus `init`

[distribution.md § Installation Scope](distribution.md#installation-scope)
defines `init` as the per-repo verb that writes a tool's repo config file — in
the **config zone**, `.punt-labs/<tool>/config.*`
([punt-labs-dir.md PLD-7](punt-labs-dir.md#pld-7-tool-deployment-respects-ownership-zones));
a repo-root sentinel is never its destination
([punt-labs-dir.md PLD-1](punt-labs-dir.md#pld-1-shared-repository-data-has-a-declared-root)) — and prompts for
project-specific settings (team roster,
relay URL, database name). `enable` and `init` are **distinct roles**, not
duplicates:

| Verb | Job | Writes |
|------|-----|--------|
| `enable` / `disable` | Turn CLAUDE.md guidance composition and hooks on/off in this repo | `.punt-labs/<tool>/` (guide + `enabled` marker), the import line, additive `.claude/settings.json` entries |
| `init` | Create and populate the tool's repo config/state | For a Punt Labs tool: the config zone (`.punt-labs/biff/config.yaml`, `.punt-labs/quarry/config.md`). |

The `enabled` marker (2.7) is the enabled signal; the repo config file is
not, and no tool reads a bare repo-root sentinel (`.biff`, `.quarry.toml`)
for it. A tool with both verbs runs `init` to configure and `enable` to turn
on; `enable` may call `init` when enabling requires config, but the two
concerns stay separate.

## 2.14 Dual surface, and the separate per-user layer

### Two front-ends, one marker

Every project-level tool exposes the `enable` / `disable` verbs, with both
scopes, at **both** front-ends, and both write and remove the **same** markers
(§2.7). There is one source of truth; the surfaces are two doors to it.

| Surface | Form | Writes |
|---------|------|--------|
| CLI | `<tool> enable` / `<tool> disable [--scope project\|local]`, run in the repo | The scope's marker, import and grants (§2.3) |
| Claude Code | `/<tool> enable` / `/<tool> disable [project\|local]` | The same, via the tool's MCP server |

The two must be behaviorally interchangeable for the enablement decision: a
marker written by `/<tool> enable` is identical to one written by
`<tool> enable`, and either verb's `disable` removes it. Neither surface runs
git — the marker is a working-tree change the user commits via a PR like any
other, so enablement lands through review, not through a tool's side effect.

An MCP enable/disable tool takes an `action` argument constrained to
`"enable" | "disable"` — **not** an `enabled: bool` — and a `scope` argument
constrained to `"project" | "local"`, defaulting to `"local"`. The boolean shape is the
forbidden `y|n` vocabulary (§2.3) wearing a type; the verb shape keeps the one
vocabulary across both surfaces.

### The per-user layer is separate

Repo enablement (this standard) answers "is the tool on for this project, or
for me in this checkout?" Shared scope is committed and whole-repo; personal
scope is ignored and one checkout. It is **not** the place for a per-user, per-session
preference such as "I am here but do not deliver messages to me right now." That
preference is a distinct, **local/gitignored** layer the tool owns separately
(biff's `mesg y|n` is the reference: a per-user delivery switch, not the
enablement switch). The two never conflate:

- Repo policy (the markers and the opt-out, §2.7) decides whether the tool runs
  in the checkout at all. Removing it turns the tool off for everyone on their next clone/pull.
- The per-user layer decides one contributor's momentary behavior *while the
  tool is enabled* — biff's `mesg`, lux's display mode, vox's mute and
  notify. It lives in a gitignored file (`.punt-labs/<tool>/*.local.*` or
  `.punt-labs/local/<tool>/`, §2.6) and never travels in a PR. A command that
  sets a personal preference never writes a tracked file.

A per-user preference verb may keep a `y|n` form (it is a genuine two-state
preference, not enablement); the `y|n` prohibition in §2.3 applies to
*enablement* only.

## 2.15 What "off" means

When the effective state (§2.7) is off — absent, dormant, opted out, or off for
one person — the tool does nothing automatic in that checkout. biff's dormant
relay is the reference.

- **MCP tools are dormant.** The server may still start, because the plugin is
  installed at user scope, but every tool other than enablement and status
  returns a result that says the tool is off in this repo and how to enable it.
  A dormant tool writes nothing, sends nothing over the network and starts
  nothing.
- **Hooks do nothing.** Every hook passes the §2.7 gate before any work and
  exits 0 with no output and no side effect when the tool is off. The one
  exception is a hook that serves the tool's user-scope machinery rather than
  the repo — biff's caller stamp, which its MCP tools need in any repo — and it
  may run only if it writes nothing in the checkout, sends nothing over the
  network and prints nothing.
- **Daemons ignore the repo.** A background service does not watch, index,
  sync, capture, poll, deliver or register anything for an off checkout. A
  service already serving the repo drops it at its next event or check, and
  keeps the repo's data (§2.9).
- **Explicit commands still run.** A command a person types (`vox say`,
  `quarry search`) is intent and may run, but no command except `enable`,
  `disable`, `enable --refresh` and `init` writes repo state while the tool is
  off.
- **`status` names the deciding file.** `<tool> status` and `doctor` report the
  effective state and the file that decided it (shared marker, personal marker,
  personal `disabled`, opt-out).
