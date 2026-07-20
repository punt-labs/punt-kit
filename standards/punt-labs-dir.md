# Repo-Local State Directory Standard

**Introduced:** 2026-07-20

Where a tool stores per-repo state, what is committed, what is ignored, and how
the two are told apart. One directory — `<repo>/.punt-labs/<tool>/` — holds
everything a tool keeps inside a repo; one convention — the `*local*` glob —
marks the files that do not travel with it. This standard builds on
[tool-enable-disable.md](tool-enable-disable.md), which governs how a tool's
CLAUDE.md guidance is turned on and off, and on [filesystem.md](filesystem.md),
which governs the global `~/.punt-labs/<tool>/` tree. It settles the
committed-vs-ignored and repo-vs-global questions those two leave open.

Section numbering is this document's own (1…); cross-references to
tool-enable-disable.md keep that document's `§ 2.x` numbers.

---

## 1. Core Principle

**One repo-local root per tool; everything in it is committed unless its name
says otherwise.** A tool that keeps state inside a repo keeps it under
`<repo>/.punt-labs/<tool>/` and nowhere else. Every file under that path is
git-tracked shared history except paths whose name matches `*local*`, which are
per-user or per-machine and are never committed. Secrets are not kept here at
all.

Two questions this standard answers, that
[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership) and
[filesystem.md](filesystem.md) leave open:

- *Committed or ignored?* Everything under `.punt-labs/` is committed except
  `*local*` ([§ 4](#4-committed-by-default-local-is-the-only-ignore-convention)).
- *Repo or home?* Team-shareable state goes in the repo; person- or
  machine-scoped state goes in `~/.punt-labs/` ([§ 3](#3-repo-versus-home-the-placement-rule)).

---

## 2. The Only Repo-Local Location

`<repo>/.punt-labs/<tool>/` is the **only** place a tool may write repo-local
state. A tool creates no top-level dotfile or dot-directory of its own —
`.biff`, `.vox`, `.lux`, `.quarry.toml` at the repo root are **deprecated
legacy** and are retired on the tool's next release ([§ 9](#9-migration)). This
mirrors the global rule in
[filesystem.md § Core Principle](filesystem.md#core-principle) ("no tool creates
its own top-level dot-directory") and extends it to the repo.

The subtree name `<tool>` is the CLI binary name, identical to the global tree
([filesystem.md § Directory Root](filesystem.md#directory-root)).

---

## 3. Repo versus Home: the Placement Rule

[filesystem.md](filesystem.md) defines the global `~/.punt-labs/<tool>/` tree;
this standard defines the repo `<repo>/.punt-labs/<tool>/` tree. A tool decides
between them by one question: **can the team working on the repo share this
file?**

| The state is… | Goes in | Committed? | Examples |
|---------------|---------|-----------|----------|
| Team-shareable — same for everyone working the repo | `<repo>/.punt-labs/<tool>/` | Yes | Vendored user guide, `enabled` marker, repo config (roster, db name) |
| Person- or machine-scoped, but repo-bound | `<repo>/.punt-labs/<tool>/…*local*…` | No ([§ 4](#4-committed-by-default-local-is-the-only-ignore-convention)) | Per-user UI prefs, a contributor's local overrides |
| Person- or machine-scoped and repo-independent | `~/.punt-labs/<tool>/` | N/A (outside any repo) | Daemon runtime, caches, indexes, cross-repo preferences |
| Secret — credential, token, key | Platform secret store, or `~/.punt-labs/<tool>/` at mode `0600` | Never in any repo | API keys, signing keys |

**Secrets never live under a repo `.punt-labs/` at all** — not even as a
`*local*` file. A `*local*` file is uncommitted, but it still sits in a work
tree that gets copied, backed up, and grepped; a secret belongs in the platform
secret store (macOS Keychain / Linux `pass`) or in `~/.punt-labs/<tool>/` at
mode `0600`.

---

## 4. Committed by Default; `*local*` is the Only Ignore Convention

**Everything under `.punt-labs/` is committed except paths matching the glob
`*local*`.** That includes the vendored user guide, the `enabled` marker
([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)),
and every repo config file. `*local*` means *not shareable by the team working
on the repo* — per-user or per-machine state. The token can appear anywhere in
the path: `config.local.yaml`, `local/`, and `vox.local.md` all match.

`*local*` is the **only** ignore convention under `.punt-labs/`. A tool does not
invent a second one. Two existing directories break this rule and must change:

- `quarry`'s `captures/` — relocate to the global tree
  (`~/.punt-labs/quarry/captures/`) if machine-scoped, or rename to a `*local*`
  path if genuinely repo-bound.
- `vox`'s `ephemeral/` — same: relocate to `~/.punt-labs/vox/` or adopt
  `*local*` naming.

A name that is neither committed content nor `*local*` is a bug: it is either
tracked state that should not be ([§ 5](#5-live-state-is-never-a-tracked-file))
or ignored state the canonical gitignore
([§ 6](#6-the-canonical-gitignore-block)) will not catch.

---

## 5. Live State is Never a Tracked File

**A file a live process appends to continuously must never be git-tracked.** A
tracked file changes only on a deliberate operator or lifecycle action — an
edit, an `enable`, a `mission close`. A file re-dirtied within seconds of every
cleanup fails that test: any repo with the tool running then has a permanently
dirty work tree, which breaks every clean-tree gate (the `punt release`
preflight over cross-repo siblings is the reported case).

Live state has two correct homes:

- **The global tree or a `*local*` path.** Continuous appends land in
  `~/.punt-labs/<tool>/` (outside every work tree) or a `*local*` file (present
  but ignored). Either keeps the tracked set still.
- **The seal pattern, when the record must be committed.** Some live streams
  *are* shared history — an audit log whose lines must travel in the same PR as
  the work they document. For those, the live writer appends to an untracked
  location and a **seal** step snapshots complete lines into the tracked file at
  a deliberate lifecycle point (pre-commit primary, `mission close` secondary).
  Between seals the tracked file does not move, so the tree stays clean. A
  seal-managed stream is **declared per file** in the tool's manifest — seal
  management is a property of the named file, never inferred from its directory.
  (A directory glob over-matches: a non-seal-managed index file sitting beside a
  sealed log must not inherit the exemption.) The seal pattern's design home is
  the ethos audit-seal design (DES-058, draft in `punt-labs/ethos` at
  `docs/audit-seal.md`) — cite it for the mechanism, but do not pin its section
  numbers, which may move before it lands.

**The seal exemption is gated on DES-058.** Until then no tool may claim it and
no manifest entry grants it: every git-tracked, continuously-appended file under
`.punt-labs/` is a violation ([§ 8](#8-what-punt-audit-checks)). The gate is a
version check, not a design lookup — it flips when the `punt` release that ships
the seal-audit machinery is installed; audit reads the local tool version and
never inspects a cross-repo design's merge state. The exemption opens only once
the seal mechanism it depends on exists.

The distinction is not "important file vs. throwaway file." It is **write
cadence**: operator- and lifecycle-driven writes may be tracked; process-driven
continuous writes may not.

---

## 6. The Canonical Gitignore Block

The ignore rule is **one canonical block, written and verified by tooling —
never hand-maintained per tool.**

```gitignore
.punt-labs/**/*local*
```

For a **deny-all + allowlist** repo — one whose first non-comment `.gitignore`
pattern is `*` or `/*`, ignoring everything — re-inclusion is order-sensitive,
and **git will not re-include the contents of a still-ignored directory.** The
directory must be re-included first, then its contents, then `*local*`
re-excluded — three lines, in this order:

```gitignore
!.punt-labs/
!.punt-labs/**
.punt-labs/**/*local*
```

The bare-directory line `!.punt-labs/` must come **before** the recursive
`!.punt-labs/**`: git evaluates patterns top to bottom and cannot descend into a
directory it still considers ignored, so `!.punt-labs/**` alone leaves the whole
subtree ignored (empirically confirmed). The workspace's own tracked `.beads/` —
`!.beads/` then `!.beads/**` — is the precedent. A two-line block without the
bare-directory line is non-functional under deny-all.

Lifecycle:

- **`punt init`** writes the canonical block.
- **`punt audit`** verifies it is present and exact
  ([§ 8](#8-what-punt-audit-checks)).
- **The rollout** propagates changes to the block across all consuming repos by
  the canonical-template pattern the workspace uses for its `.envrc`
  (`.bin/envrc-canonical-rollout.sh` — one source template pushed to every
  repo), not the fixed-artifact release propagation of
  [release-process.md](release-process.md) phase 10.

A tool **may** write defense-in-depth ignore rules of its own (a narrower glob
for a path it knows is `*local*`), but those are additive belt-and-suspenders,
never a substitute for the canonical block — and **the tool's own ignore file is
itself committed.** No tool hand-edits the canonical block; that is the
rollout's job.

---

## 7. The `.punt-labs/<tool>/` Subtree Has Zones

[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership) states the
tool owns `.punt-labs/<tool>/` and overwrites it **wholesale** on every
`enable` / upgrade — "same tool version, same repo config, identical output."
That contract collides with the placement rule
([§ 3](#3-repo-versus-home-the-placement-rule)), which puts **repo config** —
the artifacts `init` writes (a roster, a database name; today `.biff`,
`.quarry.toml` per
[tool-enable-disable.md § 2.13](tool-enable-disable.md#213-enable-versus-init)) —
inside the same subtree. A wholesale overwrite would clobber that config on
every upgrade.

**Resolution: the subtree has four zones, and the wholesale-overwrite contract
applies to exactly one of them.**

| Zone | Path shape | Owner | Committed? | On `enable` / upgrade |
|------|-----------|-------|-----------|----------------------|
| Vendored | tool-deposited files (e.g. the `CLAUDE.md` guide) | The tool | Yes | Overwritten wholesale — the § 2.2 determinism contract lives here and **only** here |
| Config | `.punt-labs/<tool>/config.*` and other `init`-written files | The repo (via `init`) | Yes | **Never touched** — `enable` / upgrade must not read, merge, or overwrite it |
| Local | `.punt-labs/<tool>/…*local*…` | The user | No ([§ 4](#4-committed-by-default-local-is-the-only-ignore-convention)) | Never touched |
| Marker | `.punt-labs/<tool>/enabled` | The tool | Yes | Written by `enable`, deleted by `disable` ([§ 2.7](tool-enable-disable.md#27-the-enabled-marker)) |

The determinism guarantee of
[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership) — "writes the
whole subtree on enable/upgrade and never reads-modifies-merges it" — is hereby
scoped to the **vendored zone**. `enable` / upgrade rewrites the vendored files
and the marker; it steps around the config and local zones. This is the
amendment that lets repo config and tool-vendored content share one directory
without the upgrade eating the config.

---

## 8. What `punt audit` Checks

These extend the audit list in
[tool-enable-disable.md § 2.11](tool-enable-disable.md#211-what-punt-audit-checks):

- **Canonical block present and exact.** Every repo's `.gitignore` carries the
  [§ 6](#6-the-canonical-gitignore-block) block verbatim — the one-line form, or
  the three-line deny-all form where the repo is deny-all (first non-comment
  pattern `*` or `/*`). A missing, altered, or two-line deny-all block is a fail.
- **No tracked `*local*`.** No path matching `.punt-labs/**/*local*` appears in
  `git ls-files`. A tracked `*local*` file means the ignore block is wrong or
  the file was force-added.
- **No unsanctioned live state.** The audit predicate is manifest membership
  only: a git-tracked file under `.punt-labs/` listed as seal-managed in its
  tool's manifest passes; one not listed fails
  ([§ 5](#5-live-state-is-never-a-tracked-file)). "Continuously appended" is not
  statically decidable, so audit does not try to detect it — an undeclared
  live-append file is caught at design review, not by this check. Membership is
  per-file and explicit, never inferred from a directory. Until the § 5 gate
  lifts, the manifest grants no exemption, so every listed file still fails.
- **Tool ignore files are committed.** Any `.gitignore` a tool ships inside its
  own `.punt-labs/<tool>/` subtree (the [§ 6](#6-the-canonical-gitignore-block)
  defense-in-depth rules) must itself be git-tracked; an untracked one is live
  drift, not defense.
- **No bare file under `.punt-labs/`** *(graded)*. Repo-local state lives in
  `.punt-labs/<tool>/`, never as `.punt-labs/<file>` directly
  ([§ 1](#1-core-principle)). A bare file whose migration is recorded in the
  [§ 9](#9-migration) bare-file table (e.g. `.punt-labs/lux.md`,
  `.punt-labs/ethos.yaml`) is a **warning** — "migration pending." A bare file
  with **no** § 9 row (e.g. a stray `.punt-labs/foo`) is a **fail**. The § 9
  bare-file table is the sole exemption source, so the grade is deterministic.
- **No secret under `.punt-labs/`** *(best-effort)*. A heuristic scan for
  credential-shaped content in repo `.punt-labs/` paths — defense-in-depth
  against a mis-scoped write ([§ 3](#3-repo-versus-home-the-placement-rule)). A
  green result is a tripwire, not proof of absence.
- **No legacy root sentinel.** No `.biff`, `.vox`, `.lux`, or `.quarry.toml` at
  the repo root ([§ 2](#2-the-only-repo-local-location),
  [§ 9](#9-migration)).

---

## 9. Migration

Additive standard — no existing rule is removed or shifted. Three migrations
bring existing tools into line, all **forward-integration, no compat shim**
([PL-PP-1](../lang-rules/python/python-prohibited-patterns.md#pl-pp-1-no-backwards-compatibility-shims))
and all bound by the rule that **live config is never deleted with content
inside** ([tool-enable-disable.md § 2.12](tool-enable-disable.md#212-migration)).

**Root sentinel → subtree** extends the
[§ 2.12 sentinel table](tool-enable-disable.md#212-migration). That table already
moves a config-bearing sentinel's settings into the tool's owned location; this
standard names the destination (the config zone,
[§ 7](#7-the-punt-labstool-subtree-has-zones)) and the shape:

| Legacy | Destination | Rule |
|--------|-------------|------|
| `.biff` (settings) | `.punt-labs/biff/config.yaml` (config zone) | Move settings, then delete the empty root file; never delete with settings inside |
| `.quarry.toml` (root) | `.punt-labs/quarry/config.toml` (config zone) | Same |
| `.biff` / `.vox` / `.lux` (pure presence) | — | Deleted once `.punt-labs/<tool>/` + `enabled` exist ([§ 2.7](tool-enable-disable.md#27-the-enabled-marker)) |

The moved file lands in the **config zone**: `init`-owned, committed, never
overwritten by `enable`.

**Bare file → subtree.** A tool that keeps state as a single file directly under
`.punt-labs/` — not inside its `<tool>/` subtree — breaks clause 1
([§ 1](#1-core-principle), [§ 2](#2-the-only-repo-local-location)); the
single-file form is **not** sanctioned. `lux` ships `.punt-labs/lux.md` across
the biff, vox, ethos, and quarry siblings; `ethos` ships a git-tracked
`.punt-labs/ethos.yaml` identity pointer in ~33 repos. Both move into a subtree,
staying git-tracked:

| Legacy | Destination | Rule |
|--------|-------------|------|
| `.punt-labs/lux.md` (bare file) | `.punt-labs/lux/` (subtree) | Move the file under the tool subtree; the bare form is retired — subtree-only stands |
| `.punt-labs/ethos.yaml` (git-tracked identity pointer) | `.punt-labs/ethos/config.yaml` (config zone, [§ 7](#7-the-punt-labstool-subtree-has-zones)) | Stays tracked; moves from bare root into the config zone. **Sequenced after** the registry gitlink → vendored `ethos/` migration ([§ 10](#10-adoption-status)) — the config file needs the `ethos/` subtree to exist first |

The `.punt-labs/ethos.yaml` move is deliberately ordered behind the
`.punt-labs/ethos` gitlink → inline-vendored-subtree migration
([§ 10](#10-adoption-status)): the pointer lands in the config zone of a subtree
that must already be present to receive it.

**Ignore-convention → `*local*`** relocates the two non-conforming directories
named in [§ 4](#4-committed-by-default-local-is-the-only-ignore-convention):
`quarry`'s `captures/` and `vox`'s `ephemeral/` move to the global tree or adopt
`*local*` naming on their next release.

---

## 10. Adoption Status

| Tool | State today | Target | Status |
|------|-------------|--------|--------|
| ethos (logs) | audit / mission live logs tracked in-repo | seal pattern; live writes to the global tree (DES-058) | Design (draft) |
| ethos (registry) | `.punt-labs/ethos` gitlink (submodule) | inline vendored registry — a gitlink is not tracked shared history ([§ 1](#1-core-principle)) | Deprecating |
| ethos (identity pointer) | `.punt-labs/ethos.yaml` bare file (git-tracked, ~33 repos) | `.punt-labs/ethos/config.yaml` config zone, after the registry migration | Planned |
| biff | `.biff` root sentinel | `.punt-labs/biff/config.yaml` config zone | Planned |
| quarry | `.quarry.toml` root; `captures/` in-repo | `.punt-labs/quarry/config.toml`; `captures/` → global or `*local*` | Planned |
| vox | `vox.md` daemon-rewritten, tracked in some repos; `ephemeral/` | live state → global or `*local*`; `ephemeral/` relocated | Planned |
| lux | `.punt-labs/lux.md` bare file (biff, vox, ethos, quarry) | `.punt-labs/lux/` subtree | Planned |
| punt | writes the canonical gitignore block | `init` writes, `audit` verifies, rollout propagates | Building |
