# Repo-Local State Directory Standard

**Introduced:** 2026-07-20 · **Updated:** 2026-07-27

Where a tool stores per-repo state, what is committed, what is ignored, and how
the two are told apart. A tool's committed repo state lives under one directory —
`<repo>/.punt-labs/<tool>/`; its per-checkout, machine-local live state lives in
the **local zone**, `<repo>/.punt-labs/local/<tool>/`
([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) — the one
non-tool entry directly under `.punt-labs/`, always gitignored. One convention —
the boundary-aware **local convention**
([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) —
marks the files that do not travel with the repo, and the local zone is that same
convention (a `local` path segment) reserved at the top of `.punt-labs/`. This
standard builds on [tool-enable-disable.md](tool-enable-disable.md), which governs
how a tool's CLAUDE.md guidance is turned on and off, and on
[filesystem.md](filesystem.md), which governs the global `~/.punt-labs/<tool>/`
tree. It settles the committed-vs-ignored and repo-vs-global questions those two
leave open.

Section numbering is this document's own (1…); cross-references to
tool-enable-disable.md keep that document's `§ 2.x` numbers.

---

## 1. Core Principle

**A tool's committed repo state lives under one root — `<repo>/.punt-labs/<tool>/`
— and everything in it is committed unless its name says otherwise; its
per-checkout, machine-local live state lives in the local zone,
`<repo>/.punt-labs/local/<tool>/`, and is never committed.** A tool that keeps
committed state inside a repo keeps it under `<repo>/.punt-labs/<tool>/`. Every
file under that path is git-tracked shared history except paths the **local
convention** marks — a path segment named exactly `local`, or a basename ending in
`.local` or with a `.local.` interior segment
([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) —
which are per-user or per-machine and are never committed. Per-checkout,
machine-local live state — a running tool's audit and session logs, locks, live
mission logs — instead goes to the **local zone**
([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)):
`<repo>/.punt-labs/local/<tool>/`, gitignored by that same `local` convention and
never committed. Secrets are not kept in either at all.

Two questions this standard answers, that
[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership) and
[filesystem.md](filesystem.md) leave open:

- *Committed or ignored?* Everything under `.punt-labs/` is committed except
  local-convention paths ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) —
  and the local zone, `.punt-labs/local/`, is one such path (a `local` segment
  directly under `.punt-labs/`), so it is always ignored.
- *Repo or home?* Team-shareable state goes in the repo's tool root; repo-bound
  machine-local live state goes in the repo's local zone; machine-scoped state
  that is repo-independent goes in `~/.punt-labs/`
  ([§ 3](#3-repo-versus-home-the-placement-rule)).

---

## 2. Repo-Local Locations: the Tool Root and the Local Zone

A tool may write repo-local state in exactly **two** places, and no others:

- **The tool root — `<repo>/.punt-labs/<tool>/`.** Committed shared history
  (except local-convention paths within it,
  [§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)).
  Every file a tool commits to a repo lives here.
- **The local zone — `<repo>/.punt-labs/local/<tool>/`.** Per-checkout,
  machine-local live state — a running tool's audit and session logs, locks, live
  mission logs — gitignored and never committed. `local/` is the **one** non-tool
  entry directly under `.punt-labs/`: the name `local` is reserved org-wide for
  this zone and is never a tool name. Beneath it the zone is tool-namespaced
  (`local/<tool>/`) exactly as the tool root is, so two tools' live state never
  collide.

The local zone is **not** a second ignore mechanism. `.punt-labs/local/` is a
local-convention path — a `local` path segment directly under `.punt-labs/`
([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) —
so the canonical gitignore block already ignores it with **no new rule**
([§ 6](#6-the-canonical-gitignore-block)). It is the local convention reserved at
the top of the tree and namespaced by tool, nothing more.

The top-level local zone is distinct from a tool's in-subtree **Local zone**
([§ 7](#7-the-punt-labstool-subtree-has-zones)): the in-subtree zone is a tool's
own `.punt-labs/<tool>/local/` (or `*.local`) holding per-user **static
overrides**; the top-level local zone is `.punt-labs/local/<tool>/` holding
machine-local **live state**. Both are ignored by the same local convention; they
differ in location and in what they hold.

Outside these two, a tool creates no top-level dotfile or dot-directory of its own
— `.biff`, `.vox`, `.lux`, `.quarry.toml` at the repo root are **deprecated
legacy** and are retired on the tool's next release ([§ 9](#9-migration)). This
mirrors the global rule in
[filesystem.md § Core Principle](filesystem.md#core-principle) ("no tool creates
its own top-level dot-directory") and extends it to the repo.

The subtree name `<tool>` is the CLI binary name, identical to the global tree
([filesystem.md § Directory Root](filesystem.md#directory-root)); the local zone
uses that same `<tool>` name one level below `local/`.

---

## 3. Repo versus Home: the Placement Rule

[filesystem.md](filesystem.md) defines the global `~/.punt-labs/<tool>/` tree;
this standard defines the repo `<repo>/.punt-labs/<tool>/` tree. A tool decides
between them by one question: **can the team working on the repo share this
file?**

| The state is… | Goes in | Committed? | Examples |
|---------------|---------|-----------|----------|
| Team-shareable — same for everyone working the repo | `<repo>/.punt-labs/<tool>/` | Yes | Vendored user guide, `enabled` marker, repo config (roster, db name) |
| Person- or machine-scoped static config, but repo-bound | `<repo>/.punt-labs/<tool>/` local-convention path (`local/`, `*.local`, `*.local.*`) | No ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) | Per-user UI prefs, a contributor's local overrides |
| Person- or machine-scoped live state, but repo-bound | `<repo>/.punt-labs/local/<tool>/` — the local zone ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) | No ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) | Running-tool audit/session logs, locks, live mission logs |
| Person- or machine-scoped and repo-independent | `~/.punt-labs/<tool>/` | N/A (outside any repo) | Daemon runtime, caches, indexes, cross-repo preferences |
| Secret — credential, token, key | Platform secret store, or `~/.punt-labs/<tool>/` at mode `0600` | Never in any repo | API keys, signing keys |

**Secrets never live under a repo `.punt-labs/` at all** — not even as a
local-convention (uncommitted) file. Such a file is uncommitted, but it still
sits in a work tree that gets copied, backed up, and grepped; a secret belongs
in the platform
secret store (macOS Keychain / Linux `pass`) or in `~/.punt-labs/<tool>/` at
mode `0600`.

---

## 4. Committed by Default; the Local Convention is the Only Ignore Convention

**Everything under `.punt-labs/` is committed except paths the local convention
marks.** That includes the vendored user guide, the `enabled` marker
([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)),
and every repo config file. The convention marks a path as *not shareable by the
team working on the repo* — per-user or per-machine state — by one of two
**boundary-aware** forms:

- a **path segment named exactly `local`** — a `local/` directory (or a file
  named `local`) at any depth; or
- a **basename ending in `.local`** (`foo.local`) **or carrying `.local.` as an
  interior dotted segment** (`config.local.yaml`, `vox.local.md`).

**Substring matching is not the rule.** The marker is not "the letters `local`
appear somewhere in the path," and not even "`.local` appears somewhere." A bare
`*local*` glob over-matches `.punt-labs/quarry/locales/en.yaml` (`local` inside
the segment `locales`); a `*.local*` glob still over-matches
`config.locales.yaml` (the `.local` prefix of `.locales`). Both are ordinary
shared content and must stay committed. The boundary forms match `.local` only as
a **whole dotted component** — a trailing `.local` or an interior `.local.` — so
`config.locales.yaml`, `mylocal.txt`, and `locales/` all stay tracked.

The local convention is the **only** ignore convention under `.punt-labs/`. A
tool does not invent a second one. Two existing directories break this rule and
must change:

- `quarry`'s `captures/` — relocate to the global tree
  (`~/.punt-labs/quarry/captures/`) if machine-scoped, or rename to a
  local-convention path if genuinely repo-bound.
- `vox`'s `ephemeral/` — same: relocate to `~/.punt-labs/vox/` or adopt
  local-convention naming.

A name that is neither committed content nor a local-convention path is a bug: it
is either tracked state that should not be
([§ 5](#5-live-state-is-never-a-tracked-file)) or ignored state the canonical
gitignore ([§ 6](#6-the-canonical-gitignore-block)) will not catch.

**Committed content is redacted at write.** Anything a tool writes into a
committed (non-local-convention) path under `.punt-labs/` — config, mission
artifacts, delegation prompts, sealed audit chunks — carries **no absolute
paths, no usernames, and no machine identifiers**. Redaction happens at write
time, not in review: the writer substitutes `~` for the user's home directory
and `<repo>` for the repo root before the bytes land in the tracked tree. This
is the DES-058 path-redaction invariant (`punt-labs/ethos`,
`docs/audit-seal.md`, merged at `85489ba0ecba1911ed21d7a15e160f7bdd8f2432`),
extended from audit lines to **all** tool state that lands in tracked history.
Local-convention and local-zone paths are exempt — they never travel. A secret
is exempt from nothing: redaction is about machine identity in shared history,
not a license to write credentials
([§ 3](#3-repo-versus-home-the-placement-rule)). `punt pii` is the best-effort
audit tooth ([§ 8](#8-what-punt-audit-checks)).

---

## 5. Live State is Never a Tracked File

**A file a live process appends to continuously must never be git-tracked.** A
tracked file changes only on a deliberate operator or lifecycle action — an
edit, an `enable`, a `mission close`. A file re-dirtied within seconds of every
cleanup fails that test: any repo with the tool running then has a permanently
dirty work tree, which breaks every clean-tree gate (the `punt release`
preflight over cross-repo siblings is the reported case).

Live state has two correct homes:

- **The global tree or the local zone.** Continuous appends land in
  `~/.punt-labs/<tool>/` (outside every work tree) or, when the live state is
  repo-bound, in the local zone `.punt-labs/local/<tool>/`
  ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) — present but
  gitignored. Either keeps the tracked set still.
- **The seal pattern, when the record must be committed.** Some live streams
  *are* shared history — an audit log whose lines must travel in the same PR as
  the work they document. For those, the live writer appends to the **live
  session log in the local zone** (`.punt-labs/local/<tool>/…`, untracked), and a
  **seal** step — at a deliberate lifecycle point (pre-commit primary,
  `mission close` secondary) — writes a **new immutable tracked file**, a
  **chunk**, into the tool subtree via temp-and-rename. Sealing is **chunk-based
  and add-only**: a chunk is written once and **never modified after creation** —
  there is no growing tracked `audit.jsonl`, and no merge driver. Because each
  seal is a fresh file rather than an edit to a shared one, cross-branch conflicts
  are structurally impossible, and any overlap left by a branch rewind is resolved
  at read time, not by merge. Between seals the tracked set does not move, so the
  tree stays clean.

  The mechanism rests on DES-058's invariant block (`punt-labs/ethos`,
  `docs/audit-seal.md`) — cite it, but do not pin section numbers, which may move
  before the design lands:
  - **I10-audit-atomic** (amended): appends target the live session log under the
    session flock, which allocates a strictly-monotonic per-session timestamp
    `ts = max(now, last_ts + 1ns)`. The per-session floor is seeded from the seal
    watermark's **full source set**, so every allocated `ts` is greater than every
    already-sealed `ts` the watermark records — across the session's sealed chunks,
    each covering `.quarantine` marker's verified `<last>`, and a frozen legacy
    file's max `ts` — not merely the max chunk `ts`. A live writer never appends a
    sealed chunk.
  - **I11-chunk**: each chunk is written exactly once via temp-and-rename and,
    while named a chunk, never rewritten. Within one branch lineage a session's
    chunks are disjoint, contiguous `ts` ranges (the watermark is tree-derived); a
    branch rewind may overlap in merged history, resolved at read, not forbidden.
  - **I11-idem**: sealing is lossless — every complete live line lands in at least
    one chunk after a following seal; duplicate copies share `(session, ts)` and
    are byte-identical.
  - **I12-merge**: a read is the union of the sealed chunks and the live tail past
    the sealed watermark. Post-discipline lines (post-upgrade chunks + live) dedup
    on `(session, ts)`, loss-free; **frozen legacy lines are not deduped at all** —
    they predate the monotonic-ts discipline and have no duplication source (the
    seal never copies a legacy line into a chunk), and the two pools never mix
    because every legacy `ts` sits below every post-upgrade `ts`.

  Line identity is `(session, ts)`; there is no `seq` field. A corrupt chunk — one
  that does not parse whole, or whose last `ts` disagrees with its filename — is
  surfaced as an error naming the chunk, never a silent drop; the specified
  recovery is `ethos audit quarantine` (DES-058), not `--no-verify`. A seal-managed
  stream is **declared per file** in the tool's **seal manifest** (distinct from
  the **vendored-zone manifest** of [§ 7](#7-the-punt-labstool-subtree-has-zones),
  which lists deposited files) — seal management is a property of the named file,
  never inferred from its directory. (A directory glob over-matches: a
  non-seal-managed index file sitting beside sealed chunks must not inherit the
  exemption.) The seal pattern's design home is the ethos audit-seal design
  (DES-058, draft in `punt-labs/ethos` at `docs/audit-seal.md`).

**The seal exemption is gated on DES-058.** Until then no tool may claim it and
no seal-manifest entry grants it: every git-tracked, continuously-appended file under
`.punt-labs/` is a violation ([§ 8](#8-what-punt-audit-checks)). The gate is a
version check, not a design lookup — it flips when the `punt` release that ships
the seal-audit machinery is installed; audit reads the local tool version and
never inspects a cross-repo design's merge state. Because installing that
release is what opens the gate, the release that ships the seal-audit machinery
must not be cut before DES-058 merges, or the gate opens early. The exemption
opens only once the seal mechanism it depends on exists.

The distinction is not "important file vs. throwaway file." It is **write
cadence**: operator- and lifecycle-driven writes may be tracked; process-driven
continuous writes may not.

---

## 6. The Canonical Gitignore Block

The ignore rule is **one canonical block, written and verified by tooling —
never hand-maintained per tool.** It is boundary-aware, not a substring glob
([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)):

```gitignore
.punt-labs/**/local
.punt-labs/**/local/**
.punt-labs/**/*.local
.punt-labs/**/*.local.*
```

Each line covers one boundary form:

- `.punt-labs/**/local` — a file or directory whose path segment is **exactly**
  `local`, at any depth. A trailing-slashless pattern matches both a `local`
  directory and a file named `local`; `locales/` does not match (segment
  `locales` ≠ `local`).
- `.punt-labs/**/local/**` — everything **beneath** a `local/` directory. The
  segment line above already prunes the whole directory in **both** forms — even
  under the deny-all re-include, a later directory-exclude cascades past the
  earlier `!.punt-labs/**` parent re-include (empirically confirmed, git 2.50.1).
  This line is therefore **defense-in-depth, not a correctness requirement**: it
  states the descendant-exclusion intent explicitly and keeps holding if the
  segment line is ever narrowed.
- `.punt-labs/**/*.local` — a basename **ending** in `.local` (`foo.local`).
- `.punt-labs/**/*.local.*` — a basename with `.local.` as an **interior dotted
  segment** (`config.local.yaml`, `vox.local.md`). Two lines are required, not
  one: a single `*.local*` glob anchors only the leading boundary and would
  wrongly ignore `config.locales.yaml` (the `.local` prefix of `.locales`
  matches). Splitting into "ends in `.local`" and "has a `.local.` segment"
  matches only a whole dotted `local` component, so `config.locales.yaml`,
  `mylocal.txt`, and `locales/` all stay tracked (empirically confirmed, git
  2.50.1).

**The local zone needs no rule of its own.** The local zone
`.punt-labs/local/<tool>/` ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone))
is already covered by the segment line above: `.punt-labs/**/local` matches
`.punt-labs/local` because `**` matches **zero** directories at the `.punt-labs/`
level, and that directory match prunes the whole zone beneath it. Both block forms
hold empirically (git 2.50.1) — in a normal-gitignore repo and in the deny-all
form, `.punt-labs/local/ethos/sessions/<id>.audit.jsonl`, its sibling `.lock`, and
`.punt-labs/local/ethos/missions/<id>.jsonl` are all ignored, while
`.punt-labs/ethos/CLAUDE.md` stays tracked. Naming the zone
([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) added no
gitignore line; the canonical block covers it unchanged.

For a **deny-all + allowlist** repo — one whose first non-comment `.gitignore`
pattern is `*` or `/*`, ignoring everything — re-inclusion is order-sensitive,
and **git will not re-include the contents of a still-ignored directory.** The
directory must be re-included first, then its contents, then the local-convention
paths re-excluded:

```gitignore
!.punt-labs/
!.punt-labs/**
.punt-labs/**/local
.punt-labs/**/local/**
.punt-labs/**/*.local
.punt-labs/**/*.local.*
```

The bare-directory line `!.punt-labs/` must come **before** the recursive
`!.punt-labs/**`: git evaluates patterns top to bottom and cannot descend into a
directory it still considers ignored, so `!.punt-labs/**` alone leaves the whole
subtree ignored (empirically confirmed). The workspace's own tracked `.beads/` —
`!.beads/` then `!.beads/**` — is the precedent. A block without the
bare-directory line is non-functional under deny-all.

**Interim excludes for not-yet-migrated live paths.** A live directory that is
not yet local-convention-named — because its owning tool has not migrated — is
committed-by-default in **both** repo types, so the exposure is not deny-all-only:
a normal-gitignore repo ignores nothing under `.punt-labs/`, and the deny-all
form's `!.punt-labs/**` re-includes everything. Either way `git add -A` would
stage a live transcript, ephemeral stream, or daemon-rewritten file. So the block
carries one temporary exclude for **every** live path an open
[§ 10](#10-adoption-status) live-state row names — **file or directory**, not
directories only — today:

```gitignore
.punt-labs/quarry/captures/
.punt-labs/vox/ephemeral/
.punt-labs/vox/vox.md
```

`.punt-labs/vox/vox.md` is a file, not a directory: the vox daemon rewrites it
and it is untracked in some repos, so the deny-all re-include would let `git
add -A` stage it. An interim-exclude list built from directories alone would miss
it — the list is derived from the concrete live paths the open rows name
([§ 10](#10-adoption-status) gives each open live-state row explicit paths so the
derivation is machine-resolvable), whatever their file type.

Each interim line is **tied to a [§ 10](#10-adoption-status) row, not to prose**:
the rollout generates this list from the § 10 table's open live-state rows and
**removes** a line when its row reads complete — i.e. once that path has relocated
to the global tree or adopted local-convention naming ([§ 9](#9-migration)) and
therefore no longer needs a special-case exclude. The list is never
hand-maintained; when § 10 has no open live rows the block carries no interim
excludes.

Lifecycle:

- **`punt init`** writes the canonical block.
- **`punt audit`** verifies the block **behaves** correctly — `git check-ignore`
  probes decide pass/fail; the verbatim-text match is a diagnostic only
  ([§ 8](#8-what-punt-audit-checks)).
- **The rollout** propagates changes to the block across all consuming repos by
  the canonical-template pattern the **workspace meta-repo** (`punt-labs/punt-labs`,
  the parent directory) uses for its `.envrc` — its `.bin/envrc-canonical-rollout.sh`
  pushes one source template to every repo — not the fixed-artifact release
  propagation of [release-process.md](release-process.md) phase 10.

A tool **may** write defense-in-depth ignore rules of its own (a narrower glob
for a path it knows is local-convention), but those are additive belt-and-suspenders,
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
| Local | `.punt-labs/<tool>/` local-convention path (`local/`, `*.local`, `*.local.*`) | The user | No ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) | Never touched |
| Marker | `.punt-labs/<tool>/enabled` | The tool | Yes | Written by `enable`, deleted by `disable` ([§ 2.7](tool-enable-disable.md#27-the-enabled-marker)) |

The determinism guarantee of
[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership) — "writes the
whole subtree on enable/upgrade and never reads-modifies-merges it" — is hereby
scoped to the **vendored zone**. `enable` / upgrade rewrites the vendored files
and the marker; it steps around the Config and Local zones (this in-subtree
**Local** zone is a tool's own `.punt-labs/<tool>/local/`, distinct from the
top-level local zone of [§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)).
This is the amendment that lets repo config and tool-vendored content share one
directory without the upgrade eating the config.

**Vendored-zone membership is a shipped manifest, not write provenance.** Which
files belong to the vendored zone cannot be inferred after the fact — nothing on
disk records that `enable` wrote a given file rather than `init` or the user. So
the tool ships a **vendored-zone manifest** (distinct from the **seal manifest**
of [§ 5](#5-live-state-is-never-a-tracked-file), which names seal-managed live
streams): the explicit list of paths it deposits. On every `enable` / upgrade the
tool writes exactly the vendored-zone-manifest set **and removes any path in the
previous manifest but not the current one** (old-manifest-minus-new). Without
that removal step a file the tool vendored in an old version but dropped in a new
one would orphan silently — left on disk as mystery content the next audit cannot
classify as vendored, config, or stray. The config, local, and marker zones are
outside the vendored-zone manifest and this step never touches them. That
manifest is what makes the vendored zone a **decidable set** rather than a guess
from whatever happens to be on disk.

The vendored-zone manifest is **itself shipped and persisted in the subtree** —
part of the vendored zone it describes, deposited on every `enable` / upgrade. The
old-manifest-minus-new removal presupposes the *previous* manifest is recoverable
at upgrade time; persisting it in the subtree (rather than only in the installed
tool package) is what guarantees the upgrading tool can read what the prior
version deposited.

**A manifest-set write never overwrites a file the tool did not vendor.** "Writes
exactly the manifest set" is bounded by the same collision-is-an-error rule as a
migration ([§ 9](#9-migration)): the tool may overwrite only a path that the
**previous** manifest also listed (its own prior vendored output, whose wholesale
replacement is the § 2.2 contract). A new-manifest path that already exists on
disk but is **not** in the previous manifest — a config file `init` wrote, or any
file the tool never vendored — is a **collision**: the write **errors and names
both paths**, and deposits nothing, rather than clobbering config or user content.
This is what keeps a manifest that grows to name a previously-config path from
silently eating that config on the next upgrade.

**Bootstrap: the first manifest-aware write grandfathers the pre-manifest
deposit.** A repo enabled before manifests existed has **no** previous manifest,
so a literal reading would collision-error on every existing vendored file on the
first manifest-aware `enable` / upgrade — a fleet-wide failure. Resolve it by
treating the **new** manifest's own paths as if they were the previous manifest
when none is on disk: the tool overwrites exactly those (the pre-manifest vendored
files it is re-depositing) and errors only on a new-manifest path that collides
with a file **outside** the vendored set. Full previous-vs-new collision
protection then applies from the **second** manifest-aware write onward, once a
real previous manifest is persisted. The config-zone carve-out is **not**
grandfathered: a new-manifest path landing on a config-zone file
([§ 3](#3-repo-versus-home-the-placement-rule)) errors unconditionally, bootstrap
or not — the grandfather covers only the tool's own prior vendored deposit, never
`init`-written config.

---

## 8. What `punt audit` Checks

These extend the audit list in
[tool-enable-disable.md § 2.11](tool-enable-disable.md#211-what-punt-audit-checks):

- **Gitignore behaves correctly** *(behavioral probe, not a text match)*. Pass
  or fail is decided by running `git check-ignore` on synthetic probe paths —
  never by matching the block's bytes, because a textual block can be present yet
  be overridden by a later pattern (fails open) and an altered block can still
  behave correctly. **Probe scope is the union of two independent sets** — neither
  subsumes the other:
  - **(a) Per present tool.** For **every `<tool>` directory present under
    `.punt-labs/`** — not one representative subtree, and **excluding the reserved
    `local/` zone, which is not a tool** ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) —
    run the fixed probe set below. A block that behaves for one tool but not
    another (a tool-specific exclude shadowing the canonical rules) is caught only
    by probing each.
  - **(b) Per interim-exclude path.** For **every** [§ 6](#6-the-canonical-gitignore-block)
    interim-exclude path (derived from the [§ 10](#10-adoption-status) Live path(s)
    column), one probe that MUST be ignored — run **regardless of whether that
    path's `<tool>` subtree is present**. A stale interim exclude for an absent or
    removed tool is never reached by set (a), so it is probed explicitly here; an
    interim line that ignores nothing is itself a **fail**.

  Set (a)'s probe set, for each present `<tool>`:
  - shared content — `.punt-labs/<tool>/CLAUDE.md`, `.punt-labs/<tool>/config.yaml`
    — MUST NOT be ignored;
  - each local-convention form — `.punt-labs/<tool>/local/x` (segment),
    `.punt-labs/<tool>/foo.local` (trailing `.local`),
    `.punt-labs/<tool>/config.local.yaml` (interior `.local.` segment) — MUST be
    ignored;
  - the counterexamples — `.punt-labs/<tool>/locales/en.yaml` and
    `.punt-labs/<tool>/config.locales.yaml` — MUST NOT be ignored (the second
    catches a `*.local*` glob that anchors only the leading boundary);
  - the local zone — `.punt-labs/local/<tool>/x` — MUST be ignored: the sanctioned
    machine-local zone ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone))
    is expected-ignored, never a stray, and the segment line covers it with no new
    rule ([§ 6](#6-the-canonical-gitignore-block)).

  Any probe in either set with the wrong outcome is a **fail**. The verbatim-text check that
  the canonical block ([§ 6](#6-the-canonical-gitignore-block)) is present and
  exact is retained **only as a diagnostic** — it explains *why* a probe failed
  (block missing, altered, or the deny-all form dropping the bare-directory line),
  but it never decides pass/fail on its own. The probe is the authority.
- **No tracked local-convention path.** No path the local convention marks — a
  segment exactly `local`, or a basename ending in `.local` or carrying a
  `.local.` interior segment
  ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)) —
  appears in `git ls-files`. A tracked local-convention file means the ignore
  block is wrong or the file was force-added. (Boundary-aware, not a `*local*` or
  `*.local*` substring scan: `locales/en.yaml` and `config.locales.yaml` are
  shared content and are expected to be tracked.)
- **No unsanctioned live state.** This check ranges over
  seal-manifest entries only — not over every tracked file. For
  each file a tool's seal manifest declares seal-managed, apply the § 5
  gate: while the gate is closed no exemption exists, so a declared
  seal-target that is git-tracked is a **fail**; once the gate
  lifts, a declared, tracked seal-target **passes**
  ([§ 5](#5-live-state-is-never-a-tracked-file)). A file in **no**
  seal manifest is out of scope for this bullet — whether it may be
  tracked is decided by committed-by-default
  ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)),
  the bare-file check, and the local-convention check, not here.
  "Continuously appended" is not statically decidable, so audit
  never tries to detect it: an undeclared live-append file that was
  tracked anyway is caught at design review, not by this check.
  Membership is per-file and explicit, never inferred from a
  directory.
- **Live-state migration pending** *(graded, table-driven)*. The seal-manifest
  check above is silent for a tool that ships **no seal manifest** — so the
  motivating case, ethos's in-repo audit and mission logs, passes it unflagged
  today. This check closes that gap **without** reintroducing a dirty-tree fail
  (the seal manifest stays the post-DES-058 mechanism,
  [§ 5](#5-live-state-is-never-a-tracked-file)):
  for each [§ 10](#10-adoption-status) row whose target is a live-state migration
  and whose status is still pending, if the live path that row names is
  git-tracked, grade a **warning** — "live-state migration pending." The § 10
  table is the sole source, exactly as the § 9 bare-file table drives the
  bare-file grade below. Like that grade, this one is **expiring**: a named,
  still-tracked live path is a **warning** while its § 10 row is open and
  **escalates to fail** once the row reads complete — a live-state migration the
  table calls finished must not leave the live path tracked. This is never the
  seal-manifest bullet's unconditional fail; the grade is bounded by the § 10
  status ([§ 10](#10-adoption-status) defines which statuses count as open).
- **No interim exclude survives a completed migration** *(table-driven)*. When a
  [§ 10](#10-adoption-status) row becomes **complete per the § 10 legend**
  (`Done` or `Complete`), the rollout drops the
  [§ 6](#6-the-canonical-gitignore-block) interim exclude that row owned. If that
  exclude is **still in the canonical block** while the row is complete — the
  migration is finished on paper yet its Live path is still ignored — audit
  **fails**. Keying on the legend's completed-set, not a literal `Done`, is
  deliberate: a `Complete` row lapses every other exemption, so it must trip this
  check too. This closes a gap the escalation rules leave open: the bare-file and
  live-state grades escalate to fail only on a *tracked* path, but a still-excluded
  path is not tracked, so a prematurely-completed migration whose path is still
  excluded would otherwise trip no grade at all. The check keys on the § 10 status
  and the § 6 block together, never on tree state.
- **No completed row strands a migration it unblocks** *(table-driven)*. The
  ethos(registry) de-gitlink is a prerequisite for what needs the
  `.punt-labs/ethos/` subtree present: the `.punt-labs/ethos.yaml` → config-zone
  move ([§ 9](#9-migration)) and in-repo sealing of the deferred chunks
  ([§ 5](#5-live-state-is-never-a-tracked-file)). When the registry row becomes
  **complete per the § 10 legend**, that move becomes possible and MUST be carried
  through in the **same change**. Audit **fails** a complete ethos(registry) row
  while the identity-pointer move it unblocks is not yet complete: the prerequisite
  resolved on paper but the dependent migration was left stranded. The ethos(logs)
  live paths are **not** a dependent here — they are gitlink-immune in the local
  zone ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) and never
  blocked; only the tracked landings in the subtree depend on the de-gitlink.
  Symmetrically, once that de-gitlink **completes**, the vendored subtree must
  actually deliver the audit trail it now can: a tool with a **seal-pattern § 10
  row** (ethos(logs)) whose vendored subtree carries **no readable seal manifest**
  ([§ 5](#5-live-state-is-never-a-tracked-file)) is a **fail**. Vendoring exists to
  make the trail verifiable, so a vendored-but-manifest-less subtree leaves the
  unsealed tail invisible forever — the same vacuous pass the gitlink warning
  flags, now un-exempted because the gitlink is gone.
- **Unvendored gitlink is audit-unverifiable** *(graded)*. A `.punt-labs/<tool>`
  entry recorded at **gitlink mode `160000`** (a submodule, not an inline subtree)
  grades a deterministic **warning** — "audit trail unverifiable until vendored."
  A gitlink is not tracked shared history ([§ 1](#1-core-principle)) and audit
  cannot read through it: the tool's seal manifest, its sealed chunks, and any
  state inside the subtree are all unreachable, so every probe that would range
  over them **passes vacuously**. The warning is the audit-side tooth for the
  vendor-first rule ([§ 10](#10-adoption-status), DES-058) — vendor the subtree
  (`ethos-e29s`) before relying on its audit trail — and it names the specific
  hole: a green result on a gitlinked tool proves nothing was checked, not that
  nothing is wrong.
- **Tool ignore files are committed.** Any `.gitignore` a tool ships inside its
  own `.punt-labs/<tool>/` subtree (the [§ 6](#6-the-canonical-gitignore-block)
  defense-in-depth rules) must itself be git-tracked; an untracked one is live
  drift, not defense.
- **No bare file under `.punt-labs/`** *(graded, expiring)*. Repo-local state
  lives in `.punt-labs/<tool>/`, never as `.punt-labs/<file>` directly
  ([§ 1](#1-core-principle)). The stray scan reads the **worktree**, not just
  `git ls-files` — a stray can be untracked or gitignored and still occupy a path.
  A bare file named in the [§ 9](#9-migration)
  bare-file table (e.g. `.punt-labs/lux.md`, `.punt-labs/ethos.yaml`) grades by
  **the [§ 10](#10-adoption-status) row that names that specific artifact** — the
  join is by row, not by tool (ethos has three § 10 rows at different statuses, so
  a tool-level aggregate would mis-grade `.punt-labs/ethos.yaml`): a **warning**
  ("migration pending") while that row is still open, but a **fail** once the row
  reads complete — a migration the table calls finished must not leave the bare
  file behind, so the exemption **lapses** instead of exempting forever. A bare
  file with **no** § 9 row (e.g. a stray `.punt-labs/foo`) is a **fail** outright.
  The § 9 table names the exempt paths; the matching § 10 row's status bounds how
  long the exemption lasts ([§ 10](#10-adoption-status) defines which statuses
  count as open), so the grade is deterministic and time-bounded. The reserved
  `local/` zone ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone))
  is a directory, not a bare file, and is the **one sanctioned non-tool entry**
  directly under `.punt-labs/` — it is expected (gitignored) and never flagged as
  a stray. But **if `.punt-labs/local` exists it MUST be a directory**: a stray
  *file* by that name is gitignored (so `git ls-files` and an ignore-respecting
  walk both miss it) yet blocks the zone's `mkdir` with `ENOTDIR`, silently
  denying every tool its live-state home. Audit checks the path's type explicitly
  and **fails** a non-directory `.punt-labs/local`.
- **No secret under `.punt-labs/`** *(best-effort)*. A heuristic scan for
  credential-shaped content in repo `.punt-labs/` paths — defense-in-depth
  against a mis-scoped write ([§ 3](#3-repo-versus-home-the-placement-rule)). A
  green result is a tripwire, not proof of absence.
- **No machine identity in committed `.punt-labs/` content** *(best-effort)*.
  `punt pii` scans tracked `.punt-labs/` paths for absolute home paths
  (`/Users/<x>`, `/home/<x>`), email addresses, and `.local` hostnames — the
  audit tooth for the redaction-at-write rule
  ([§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention)).
  Best-effort exactly like the secret scan above: writer-side redaction is the
  primary control, the scan is the tripwire.
- **No legacy root sentinel** *(graded, expiring)*. No `.biff`, `.vox`, `.lux`,
  or `.quarry.toml` at the repo root ([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)).
  Graded exactly like the bare-file check, not an unconditional fail: a sentinel
  named in the [§ 9](#9-migration) root-sentinel table grades by **the
  [§ 10](#10-adoption-status) row that names that sentinel** (by row, not by tool)
  — a **warning** ("migration pending") while that row is open, a **fail** once the
  row is complete per the § 10 legend, or if the sentinel appears with **no** § 9 /
  § 10 row at all. An unconditional fail
  would fail every repo in the fleet today, since every listed sentinel's migration
  is still open ([§ 10](#10-adoption-status)) — the same day-one-fleet-fail the
  bare-file and `.punt-labs/ethos.yaml` grades avoid.

---

## 9. Migration

No existing rule is removed; the one amendment this standard makes — scoping
[tool-enable-disable.md § 2.2](tool-enable-disable.md#22-ownership)'s
wholesale-overwrite contract to the vendored zone
([§ 7](#7-the-punt-labstool-subtree-has-zones)) — is explicit and reciprocal, as
that section's own § 2.2 cross-reference records. Three migrations bring existing
tools into line, all **forward-integration, no compat shim**
([PL-PP-1](../lang-rules/python/python-prohibited-patterns.md#pl-pp-1-no-backwards-compatibility-shims))
and all bound by the rule that **live config is never deleted with content
inside** ([tool-enable-disable.md § 2.12](tool-enable-disable.md#212-migration)).

**Destination-collision is an error, never an overwrite.** Every migration below
is a *move*, and a move must not clobber what is already there. If the
destination path already exists, the migration **makes no change, errors, and
names both paths** — the source it was moving and the occupied destination — for
an operator to resolve. A migration that silently overwrote its destination could
destroy live config or a hand-placed file, violating the never-delete-live-config
rule; surfacing the collision is the safe default. This applies to every move in
the tables that follow.

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
([§ 1](#1-core-principle), [§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)); the
single-file form is **not** sanctioned. `lux` ships `.punt-labs/lux.md` across
the biff, vox, ethos, and quarry siblings; `ethos` ships a git-tracked
`.punt-labs/ethos.yaml` identity pointer in ~33 repos. Both move into a subtree,
staying git-tracked:

| Legacy | Destination | Rule |
|--------|-------------|------|
| `.punt-labs/lux.md` (bare file) | `.punt-labs/lux/` (subtree) | Move the file under the tool subtree; the bare form is retired — subtree-only stands |
| `.punt-labs/ethos.yaml` (git-tracked identity pointer) | `.punt-labs/ethos/config.yaml` (config zone, [§ 7](#7-the-punt-labstool-subtree-has-zones)) | Stays tracked; moves from bare root into the config zone. **Sequenced after** the registry gitlink → vendored `ethos/` migration ([§ 10](#10-adoption-status)) and carried through in the **same change** that completes the de-gitlink ([§ 8](#8-what-punt-audit-checks)) — the config file needs the `ethos/` subtree to exist first |

The `.punt-labs/ethos.yaml` move is deliberately ordered behind the
`.punt-labs/ethos` gitlink → inline-vendored-subtree migration
([§ 10](#10-adoption-status)) and carried through in the **same change** that
completes the de-gitlink ([§ 8](#8-what-punt-audit-checks)): the pointer lands in
the config zone of a subtree that must already be present to receive it, and the
same-change rule keeps the move from stranding as a separate later change.

**Ignore-convention → local convention** relocates the two non-conforming
directories named in
[§ 4](#4-committed-by-default-the-local-convention-is-the-only-ignore-convention):
`quarry`'s `captures/` and `vox`'s `ephemeral/` move to the global tree or adopt
local-convention naming on their next release.

---

## 10. Adoption Status

| Tool | State today | Live path(s) | Target | Status |
|------|-------------|--------------|--------|--------|
| ethos (logs) | audit / mission live logs written under the `.punt-labs/ethos` gitlink today | — | seal pattern (DES-058): **live** writes go to the local zone `.punt-labs/local/ethos/` (`sessions/<id>.audit.jsonl` + per-session `.lock`, `missions/` live logs) — gitlink-immune (a `local/` sibling of the gitlink), auto-ignored; **sealed** chunks land in the tracked `.punt-labs/ethos/` subtree, but a gitlink-mounted repo defers each seal with a signaled notice until vendored (bead `ethos-e29s`) — a bounded limitation (below) | Design |
| ethos (registry) | `.punt-labs/ethos` gitlink (submodule) | — | inline vendored registry — a gitlink is not tracked shared history ([§ 1](#1-core-principle)) | Deprecating |
| ethos (identity pointer) | `.punt-labs/ethos.yaml` bare file (git-tracked, ~33 repos) | — | `.punt-labs/ethos/config.yaml` config zone, after the registry migration | Planned |
| biff | `.biff` root sentinel | — | `.punt-labs/biff/config.yaml` config zone | Planned |
| quarry (config) | `.quarry.toml` root sentinel | — | `.punt-labs/quarry/config.toml` config zone | Planned |
| quarry (captures) | `captures/` live capture dir in-repo | `.punt-labs/quarry/captures/` | global tree or local-convention | Planned |
| vox (vox.md) | `vox.md` daemon-rewritten, tracked in some repos | `.punt-labs/vox/vox.md` | live state → global or local-convention | Planned |
| vox (ephemeral) | `ephemeral/` live stream dir in-repo | `.punt-labs/vox/ephemeral/` | relocated → global or local-convention | Planned |
| vox (sentinel) | `.vox` pure-presence root sentinel | — | deleted once `.punt-labs/vox/` + `enabled` exist ([§ 2.7](tool-enable-disable.md#27-the-enabled-marker)) | Planned |
| lux (bare file) | `.punt-labs/lux.md` bare file (biff, vox, ethos, quarry) | — | `.punt-labs/lux/` subtree | Planned |
| lux (sentinel) | `.lux` pure-presence root sentinel | — | deleted once `.punt-labs/lux/` + `enabled` exist ([§ 2.7](tool-enable-disable.md#27-the-enabled-marker)) | Planned |
| punt | writes the canonical gitignore block | — | `init` writes, `audit` verifies, rollout propagates | Building |

The **Live path(s)** column is machine-resolvable: it lists the concrete paths
(files and directories, glob-expanded) each **live-state** row names, and is the
sole source the [§ 6](#6-the-canonical-gitignore-block) interim excludes and the
[§ 8](#8-what-punt-audit-checks) live-state grade derive from. A `—` marks a row
carrying no interim-exclude live path — either it is not a live-state migration
(registry, bare-file, or config-zone moves carry no live path), **or its live
state lands in the local zone**, which the canonical block already ignores
([§ 6](#6-the-canonical-gitignore-block)), so no interim exclude is derived and the
live-state grade has nothing to catch. ethos(logs) is the second kind: its live
writes go to `.punt-labs/local/ethos/`
([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)) — a `local/`
sibling of the `.punt-labs/ethos` gitlink (mode `160000`), so **gitlink-immune**
and auto-ignored — and its Live path(s) stay `—` permanently. The gitlink bounds
one thing: the **sealed chunks** (tracked, [§ 5](#5-live-state-is-never-a-tracked-file))
land in the `.punt-labs/ethos/` subtree, but a gitlink-mounted repo (a consuming
repo before bead `ethos-e29s`) cannot reach it, so each seal **defers with a signaled
notice** and `ethos audit show` flags the unsealed tail
(`N unsealed lines, sealing deferred until vendored`); deleting such a checkout
destroys those unsealed lines. DES-058 accepts this as a **bounded pre-`ethos-e29s`
limitation** — no spool — and the org rule is to vendor a repo (`ethos-e29s`) before
relying on its audit trail. No live path is ever inferred from prose.

**The registry de-gitlink unblocks tracked landings, not live paths.** ethos's
live logs are gitlink-immune — they sit in the local zone
([§ 2](#2-repo-local-locations-the-tool-root-and-the-local-zone)), a sibling of the
`.punt-labs/ethos` gitlink — so the de-gitlink restores no live path, and
ethos(logs) Live path(s) stay `—` throughout. What it **does** unblock is tracked
content landing in the `.punt-labs/ethos/` subtree: the deferred sealed chunks
([§ 5](#5-live-state-is-never-a-tracked-file)) begin sealing in-repo, and the
`.punt-labs/ethos.yaml` → config-zone move ([§ 9](#9-migration)) becomes possible —
both need the subtree inline-vendored first. Audit enforces the sequencing
([§ 8](#8-what-punt-audit-checks)): a **complete** ethos(registry) row while the
identity-pointer move it unblocks has not been carried through in the **same
change** is a **fail**.

**Grades join by row, not by tool.** Each § 9 migration artifact maps to the
single § 10 row that names it, and every grade — bare-file, root-sentinel,
live-state, and interim-exclude-lapse — keys on **that row's** status, never a
tool-level aggregate. ethos alone spans three rows (logs, registry, identity
pointer) at three different statuses, so a tool-level join would mis-grade its
artifacts; the row that names the specific artifact is always the authority.

**One row per artifact — no multi-target rows.** A tool with more than one
migrating artifact takes **one row each**, so no artifact shares a status with
another. quarry splits into quarry(config) (`.quarry.toml` → config zone) and
quarry(captures) (the live `captures/` dir); vox into vox(vox.md), vox(ephemeral),
and vox(sentinel). If the config and live halves shared a row, completing the
config half would flip the whole row to complete and drop the live path's interim
exclude ([§ 6](#6-the-canonical-gitignore-block)) while `captures/` / `ephemeral/`
/ `vox.md` are still live — re-opening `git add -A` staging of live state. Per-row
artifacts bind each interim exclude's lifecycle to exactly the row that names it,
which is what makes the by-row join unambiguous by construction.

**Status controls audit grading.** This table is the authority for how long an
audit exemption lasts ([§ 8](#8-what-punt-audit-checks) bare-file and live-state
grades, [§ 6](#6-the-canonical-gitignore-block) interim excludes). A row is
**complete** only when its status is exactly `Done` or `Complete`; **every other
value — `Design`, `Deprecating`, `Planned`, `Building`, or any status not in that
two-word complete enumeration — is treated as open** (fail-closed: an unrecognized
status never silently lifts an exemption). While a row is open, an audit finding
it produces grades a **warning** and any interim exclude it owns stays in the
canonical block. Not every open row grades the same, though. ethos(logs) —
gitlink-immune live state in the local zone, owning no interim-exclude path — is
genuinely **audit-silent** while open: nothing probes it, so it draws neither
warning nor fail, and its sequencing is held instead by the dependent-migration
fail ([§ 8](#8-what-punt-audit-checks)) and design review. ethos(registry) is
**not** silent — its `.punt-labs/ethos` gitlink draws the mandatory
**gitlink-unverifiable warning** ([§ 8](#8-what-punt-audit-checks)) for as long as
the row is open, and that warning must **not** be suppressed on the theory that a
submodule is unprobed. When a row becomes **complete** (`Done` or `Complete`), the
exemption **lapses** — the bare-file, root-sentinel, and live-state grades
escalate to **fail** and the rollout drops the row's interim exclude. No row is
complete yet; the escalation is the forward contract for when one is.
