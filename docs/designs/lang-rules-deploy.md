# Design: Language Rules Deploy Into Each Repo's Own `.claude/rules/`

**Introduced:** 2026-11-12
**Worker:** adt · **Evaluator:** mdm

This document settles where the deployment of punt-kit's per-language coding
rules lives on the `punt` CLI, how a deployed copy is owned, refreshed, and
audited, and how the workspace meta-repo retires the hand copy that floods
nested sessions. It follows the shape of
[claude-md-include-standard-design.md](../claude-md-include-standard-design.md):
summary, mechanism, the fork and each settled question with rejected
alternatives, a `DESIGN.md` ADR draft, the implementation write-set, and the
operator-decisions list.

---

## 1. Summary

punt-kit's per-language rule sets (`python/`, `go/`, `c/`, `swift/`) are
deposited into a repo's own `.claude/rules/` by the bare `punt enable`, the
same verb that deposits punt's user guide, the `enabled` marker, and the
`@.punt-labs/punt/CLAUDE.md` import line. Re-running `punt enable` is the
update path. Which sets a repo gets is decided by a declaration in punt's
config zone when one exists, else by detection from the repo's root marker
files. Every deployed file is byte-identical to its canonical source, and the
set is governed by a manifest persisted in punt's vendored zone
(`.punt-labs/punt/rules-manifest.toml`) that names each deployed path and its
content hash. `punt audit` compares each deployed copy against the installed
punt-kit's canonical set and fails on any difference, any missing file, and
any canonical file the manifest does not cover. The canonical sets move into
the package (`src/punt_kit/lang_rules/`) so the installed wheel carries them
and a consumer repo needs no punt-kit checkout.

The workspace meta-repo deletes its `.claude/rules/` after every Python child
repo has merged its own deployed set, and hosts no rule set of its own while
the upstream ancestor-traversal defect is open: any `.claude/rules/` in the
workspace, current or stale, loads unconditionally into every nested child
session. Deleting the directory is what ends the flood; redeploying a current
copy there would reproduce it.

---

## 2. Fleet reality check

Surveyed on 2026-11-12 across every sibling under the workspace root.

**Rule directories.** Exactly three repos carry a `.claude/rules/`:

| Repo | Files | Content |
|------|-------|---------|
| workspace (`punt-labs/punt-labs`) | 23 `python-*.md` | A hand copy of the Python set from May 2026; all 22 files that have a canonical counterpart differ from `lang-rules/python/` (`diff -rq`), and `python-tooling-enforcement.md` is the only file touched since July. |
| beadle | `beads.md`, `delegation.md`, `go-standards.md`, `mock-before-code.md` | Four hand-written repo rules. `go-standards.md` is a 12-line Go checklist scoped `**/*.go`; it is not a copy of `lang-rules/go/` and overlaps it in subject. The other three have no `paths:` frontmatter. |
| z-spec | `claude-tools.md`, `python-standards-pointer.md`, `z-conventions.md` | Three hand-written repo rules. `python-standards-pointer.md` is scoped `**/*.py` and points at `../.claude/rules/python-*.md`, the workspace hand copy, by the ancestor walk; it describes the exact mechanism this design retires. |

No other sibling has a `.claude/rules/` directory. The Python siblings
without one are biff, lux, quarry, vox, and punt-kit itself; the Go siblings
are agent-image, agent-image-buzz, beads, circuit, cryptd, ethos, mcp-proxy,
and points; the Swift siblings are koch-trainer-swift and quarry-menubar. No
sibling has a C marker.

**Deploy tooling.** No Makefile, `scripts/`, `src/`, or workspace `.bin/`
file in any sibling mentions `lang-rules`. Nothing deploys the sets.

**The closest deployed precedent is punt's own guide.** The workspace script
`.bin/tracker-guide-rollout.sh` deposits `src/punt_kit/templates/punt-guide.md`
into each child as `.punt-labs/punt/CLAUDE.md`, writes the `enabled` marker,
and appends the bare import line to the child's `CLAUDE.md` under the §2.4
write rules, one PR per repo. Ten repos carry that deposit (anthropic-sdk-pharo,
beadle, biff, circuit, cryptd, koch-trainer-swift, mcp-proxy, prfaq,
public-website, use-cases). The script detects drift by `cmp` against the
template, byte-identical. No `punt enable` verb exists in the CLI
(`src/punt_kit/__main__.py` has `init`, `audit`, `pii`, `release`, `seed`,
`version`, `doctor`, `status`).

**What this design generalizes.** The shell rollout's contract: a
byte-identical deposit, an `enabled` marker, one bare import line, drift
detected by exact comparison. This design moves that contract into the `punt`
CLI as the bare `punt enable` and extends its deposit set with the language
rules, so the guide and the rules travel by one verb instead of one shell
script per artifact.

**What this design supersedes.** The workspace hand copy, and z-spec's pointer
rule, both of which depend on the ancestor walk. z-spec's
`python-standards-pointer.md` is deleted in the same PR that deploys z-spec's
own set. beadle's `go-standards.md` is a repo rule, not a copy; it stays, and
the deployed `go-*.md` set sits beside it.

---

## 3. The mechanism

### 3.1 Command lines

```text
punt enable            # deposit guide + marker + import line + language rules; idempotent; re-run to update
punt disable           # remove the import line and the marker; leave the guide and the rules in place
punt audit             # includes the "language rules current" check
punt audit --fix       # refreshes a drifted set through the same deployer enable uses
```

`/punt enable` and `/punt disable` are the slash equivalents, wrapping the
CLI exactly as `/punt audit` wraps `punt audit`. There is no `rules` noun and
no `repo-install` or `repo-update` verb; install and update are one idempotent
operation, which is what `enable` already means.

### 3.2 What `punt enable` writes

| Path | Zone | Write |
|------|------|-------|
| `.punt-labs/punt/CLAUDE.md` | vendored | the guide from `templates/punt-guide.md`, overwritten wholesale |
| `.punt-labs/punt/enabled` | marker | created |
| `CLAUDE.md` | user-owned | one bare `@.punt-labs/punt/CLAUDE.md` line appended if absent, under the §2.4 write rules (exclusive lock, atomic replace, byte-preserving, host EOL, code blocks skipped) |
| `.punt-labs/punt/rules-manifest.toml` | vendored | the manifest of every deployed rule path and its SHA-256, overwritten wholesale |
| `.claude/rules/<lang>-<name>.md` | Claude-Code-dictated | each file of each selected set, byte-identical to its canonical source |
| `.punt-labs/punt/config.toml` | config | never written by `enable`; read if present |

`punt disable` removes the import line and the marker and nothing else, per
§2.9: the guide, the manifest, and the deployed rules stay in place, dormant.
A repo that wants the rules gone deletes the manifest-listed paths by hand;
the standard offers no `--purge` and this design adds none.

### 3.3 Language selection

The selected set is a list of language names drawn from the canonical set's
directory names (`python`, `go`, `c`, `swift`):

1. If `.punt-labs/punt/config.toml` exists and has a `[rules]` table with a
   `languages` key, that list is the selection, in full. An empty list selects
   nothing. An unknown name is an error naming the name and the known set.
2. Otherwise the selection is every language whose root marker is present:
   `pyproject.toml` with a `[project]` table selects `python`; `go.mod`
   selects `go`; `project.yml` or any `*.swift` file selects `swift`. C has no
   detector and is declared. A repo may match more than one.

The declaration replaces detection; it never unions with it, so a repo can
state its languages exactly, including none.

```toml
# .punt-labs/punt/config.toml
[rules]
languages = ["python"]
```

### 3.4 The manifest

```toml
# .punt-labs/punt/rules-manifest.toml — written by punt enable; do not edit
version = 1
punt_kit = "0.19.0"
languages = ["python"]

[[file]]
path = ".claude/rules/python-build-system.md"
sha256 = "…"
```

One `[[file]]` entry per deployed path, sorted by path. The manifest is the
provenance marker: a path is punt-deployed if and only if the manifest lists
it. Nothing is written into the rule files themselves.

### 3.5 The deploy algorithm

`enable` computes the new manifest from the selection and the canonical set,
reads the previous manifest from disk if one exists, then:

- **Writes** every new-manifest path whose bytes differ from the canonical
  file, or which is absent. A path listed in the previous manifest is punt's
  prior output and is overwritten whatever its current content; when its
  on-disk hash matches neither the previous manifest's hash nor the new
  canonical hash, `enable` prints one line naming the file as a replaced local
  edit. The replacement is not refused: the vendored-zone contract is wholesale
  overwrite, and a local variant belongs in a hand-written file with a
  different name.
- **Removes** every path in the previous manifest that is not in the new one
  (a language dropped from the selection, a canonical file renamed or
  retired).
- **Refuses** when a new-manifest path exists on disk and is not in the
  previous manifest: that file is foreign, so `enable` errors naming the
  path and the canonical source, and deposits nothing. The one exception is
  bootstrap: with no previous manifest on disk, the new manifest's own paths
  are treated as the previous manifest, so a repo carrying an old hand copy
  under the canonical names is overwritten on first run. This is the
  punt-labs-dir § 7 bootstrap rule applied unchanged.
- **Never touches** any other path under `.claude/rules/`.

Every deployed file carries the language prefix in its name (`python-`,
`go-`, `c-`, `swift-`), so the canonical `c/tests.md` is renamed `c-tests.md`
at its source. The prefix is a reading aid for a human in the directory; the
manifest is the authority.

### 3.6 The audit check

`punt audit` adds one check per selected language, keyed on the `enabled`
marker per §2.11 (a dormant or never-enabled repo is not flagged):

| Condition | Verdict | Detail |
|-----------|---------|--------|
| marker present, selection non-empty, no manifest | FAIL | `language rules not deployed — run punt enable` |
| manifest lists a path that is absent | FAIL | the path |
| manifest lists a path whose bytes differ from the installed canonical file | FAIL | `N of M files differ — run punt enable` |
| a canonical file of a selected language is not in the manifest | FAIL | `rule set outdated — run punt enable` |
| manifest `languages` differs from the current selection | FAIL | both lists |
| everything matches | PASS | `python rules current (23 files)` |

The comparison is byte-equality against the canonical file inside the
installed punt-kit. The manifest hash is not what decides pass or fail; it
exists so `enable` can tell a replaced local edit from an upstream change.
`--fix` runs the same deployer `enable` runs, only when the marker is present;
with the marker absent the finding stays FAIL and names `punt enable`.

### 3.7 Wheel packaging

The canonical sets move from the repo root `lang-rules/` to
`src/punt_kit/lang_rules/`, beside `templates/`. `uv_build` ships the declared
module wholesale, so no `pyproject.toml` change is needed; the deployer reads
the sets with `importlib.resources.files("punt_kit") / "lang_rules"`, the
same call `audit` uses for templates. `tests/test_packaging.py` gains an
assertion that a built wheel contains `lang_rules/python/`.

### 3.8 The workspace sequence

1. Release the punt-kit that ships `punt enable`.
2. In every Python child repo (biff, lux, quarry, vox, z-spec, punt-kit) run
   `punt enable` and merge the result by PR. z-spec's PR also deletes
   `.claude/rules/python-standards-pointer.md`. Go and Swift children are
   enabled the same way, in any order, and nothing gates on them.
3. Only after every Python child has merged: in the workspace repo, one PR
   that removes `.claude/rules/` entirely. The workspace deploys no rule set
   of its own while anthropics/claude-code#16299 is open.
4. Verify by starting a nested child session and confirming its loaded memory
   lists no `python-*.md` from the ancestor; and `punt audit` in each enabled
   child reports its set current.

The ordering constraint is a coverage invariant: at no point does a Python
child session have fewer rules than before. Children gain their own set first;
the ancestor set is removed last. Removing the ancestor set is pure gain for
every non-Python child, which inherits the Python set wrongly.

---

## 4. The fork: where the operation lives

**Recommendation: the bare `punt enable`, shipped by this unit, with the
language rules as one of its deposits.** The command lines are those in
§ 3.1.

The three governing texts agree once read together:

- [tool-enable-disable.md § 2.10](../../standards/tool-enable-disable.md#210-punt-follows-the-convention)
  says `punt` is a tool like any other and `punt enable` deposits
  `.punt-labs/punt/CLAUDE.md` plus the import line. § 2.3 says `enable`
  deposits the guide "and any other files the tool ships" and that re-running
  is the upgrade path. A rule set is a file the tool ships.
- `DESIGN.md` DES-024 fixes that the bare `punt enable` is punt enabling
  itself, and the kit-manager form always takes an argument. Putting the rules
  on the bare verb keeps that split intact.
- `DESIGN.md` DES-027 forbids aliases and two names for one operation. A
  separate `punt rules install` beside an `enable` that also deploys rules
  would be exactly that. An `enable` that does not deploy rules, beside a
  `rules install` that does, contradicts DES-024's own description of what
  the bare verb activates.

**Relationship to the kit-manager unit.** This unit ships the bare `punt
enable` and `punt disable` (self only, no argument): the guide deposit, the
marker, the § 2.4 import-line writer, and the rules deployer. It leaves to the
kit-manager unit everything that takes an argument or reshapes another verb:
`punt install <tool>`, `punt enable <tool>` and `punt disable <tool>`
dispatch, the `init` shrink, and the `punt status` installed-by-enabled
matrix. The kit-manager unit then builds on an `enable` that exists.

**Rejected alternatives.**

| Alternative | Why rejected |
|-------------|--------------|
| `punt rules install` / `punt rules update` as a noun group, no `enable` | Two verbs for one idempotent operation; a second name for a deposit § 2.3 already assigns to `enable`; the bare `enable` the standard and DES-024 describe would still not exist. |
| Ship the rules verb now, fold it into `enable` when the kit-manager unit lands | Two surfaces for one operation during the gap, which DES-027 forbids, and a rename train afterwards. |
| Deposit the rules from `punt init` | § 2.13 separates `init` (one-time scaffolding of user-owned files) from `enable` (maintained guidance); the kit-manager unit shrinks `init` further. Rules are maintained guidance. |
| A workspace shell rollout only, no CLI verb | Reproduces the tracker-guide rollout for a second artifact; a consumer repo outside the workspace could not deploy; the CLI is the complete product. |

---

## 5. The six questions

### 5.1 Language selection

**Recommendation:** declaration in `.punt-labs/punt/config.toml` when
present, else detection from root markers, as § 3.3 states. Detection yields a
set, not one language, so a repo with `pyproject.toml` and `go.mod` gets both
sets. The workspace repo, whose Python lives only under `.bin/`, would declare
`languages = ["python"]`; it does not do so while the upstream defect is open
(§ 7, decision 1).

| Alternative | Why rejected |
|-------------|--------------|
| `ProjectInfo.language` alone | Single-valued and first-match (`python` wins over `go`), so a two-language repo gets one set; and a repo with no root marker, such as the workspace, gets nothing with no way to say otherwise. |
| Declaration only | Every repo would need a config file before its first `enable`; detection covers the common case with no file. |
| Union of declaration and detection | A repo could not opt out of a detected set, and the declaration would stop being the exact statement it reads as. |
| YAML declaration (`config.yaml`, as biff) | punt-kit parses TOML (`tomllib`, `tomli-w`) and has no YAML dependency; punt-labs-dir § 7 allows any `config.*`. |

### 5.2 Ownership, idempotency, and provenance

**Recommendation:** files byte-identical to the canonical source; the
manifest in punt's vendored zone is the provenance marker and the only thing
that decides which paths punt owns; foreign files are never touched;
collisions refuse; a replaced local edit is reported, not refused (§ 3.4,
§ 3.5). beadle's four files and z-spec's three are foreign under this rule
and are untouched by `enable`.

| Alternative | Why rejected |
|-------------|--------------|
| A provenance comment inserted into each deployed file at deploy time | Breaks byte-equality, so drift detection needs a transform that strips the line; and the deployed bytes then differ by punt-kit version for identical content. The guide precedent is byte-identical too. |
| A provenance sentence authored into each canonical file | Makes the canonical source describe its own deployment, which is true but is content, not mechanism; it can be adopted later without changing anything here. |
| Infer ownership from the `<lang>-` filename prefix | Write provenance cannot be inferred after the fact (punt-labs-dir § 7); a hand-written `python-local.md` would be overwritten. |
| Refuse to overwrite a locally edited deployed file | The vendored-zone contract is wholesale overwrite; a refusal makes `enable` non-idempotent and leaves the repo on a private fork of a canonical rule with no upgrade path. |
| Per-repo `exclude` list to drop individual canonical rules | Not in this unit: a uniform set is the point. A repo that disagrees with a rule changes the rule in punt-kit. |

### 5.3 The audit drift check

**Recommendation:** § 3.6. Byte-equality against the installed punt-kit's
canonical file, one row per language, `--fix` refreshes through the same
deployer when the marker is present.

| Alternative | Why rejected |
|-------------|--------------|
| Compare manifest hashes only, never the canonical bytes | A manifest written by an older punt-kit would pass against its own stale hashes; the check must see the installed set. |
| `--fix` does not refresh; only `enable` writes | Precedent is that `--fix` creates the mechanical files `init` creates; the operator's stated outcome is update on demand; one deployer class serves both doors. |
| Fail when a repo has no manifest regardless of the marker | Contradicts § 2.11, which keys every check on the marker so a dormant tool is not flagged. |

### 5.4 Wheel packaging

**Recommendation:** move the canonical home to `src/punt_kit/lang_rules/`
(§ 3.7). Links in `standards/tool-enable-disable.md`,
`standards/punt-labs-dir.md`, `README.md`, and `CLAUDE.md` are rebased; the
`lang_rules/README.md` moves with the sets.

| Alternative | Why rejected |
|-------------|--------------|
| Symlink `src/punt_kit/lang_rules` to `../../lang-rules` | A link inside the shipped module is backend- and platform-dependent; the sdist would carry a dangling link. |
| Copy at build time (`make build` step) | A second copy of the canonical set, the exact source of drift this design removes. |
| `uv_build` `data` files | Installed under the prefix, not the package; unreachable through `importlib.resources`; absent in editable installs, so development needs a fallback path. |
| Keep `lang-rules/` and read it from a punt-kit checkout | A consumer repo without the checkout cannot deploy, which is the requirement. |

### 5.5 The workspace-delete sequence

**Recommendation:** § 3.8: children first, the workspace last, and the
workspace hosts no rule set while the upstream defect is open.

| Alternative | Why rejected |
|-------------|--------------|
| Delete the workspace set first | Every Python child loses rules until it is enabled; the coverage invariant breaks. |
| Delete and redeploy a current Python set in the workspace for `.bin/` | The same ancestor path loads it unconditionally into every nested child session; the flood continues with current content, and Python children load the set twice. The `.bin/` directory is governed by its own three-requirement exception, not by the OO rules, so losing the set there costs nothing the workspace rules require. |
| Keep the workspace set and only tighten its `paths:` globs | The defect ignores `paths:` on the ancestor path; narrowing changes nothing. |

### 5.6 Paths: verbatim or rewritten

**Recommendation:** verbatim. The `paths:` globs are relative to the directory
that holds `.claude/`, which is the repo root the deployer writes to, so a glob
means the same thing in every repo. `python-distribution.md`'s narrowing to
`pyproject.toml`, `Makefile`, and `.github/**` is right everywhere it lands.
Verbatim deployment is also what makes byte-equality the drift test.

| Alternative | Why rejected |
|-------------|--------------|
| Rewrite globs per repo from a config key | Per-repo variants of a canonical file; drift detection needs a renderer; the place for repo-specific scoping is a hand-written rule. |
| Narrow `**/*.py` to `src/**` and `tests/**` at deploy time | Misses `.bin/`, `scripts/`, and tools directories, and encodes a layout the canonical set does not assume. |

---

## 6. `DESIGN.md` ADR draft

The leader lifts this section verbatim.

```markdown
## DES-038: Language Rules Deploy Into Each Repo's Own `.claude/rules/`, by `punt enable`

**Date:** 2026-11-12
**Status:** SETTLED
**Topic:** How punt-kit's per-language rule sets reach a repo, how a deployed
copy is owned and refreshed, and why the workspace hosts none

### Context

punt-kit holds the canonical per-language rule sets, but nothing deployed
them. The workspace meta-repo carried a hand copy of the Python set that had
drifted in 22 of 23 files, and Claude Code loads an ancestor directory's
`.claude/rules/` into every nested session unconditionally, `paths:`
ignored (anthropics/claude-code#16299, open). Every child-repo session under
the workspace therefore started with a stale Python set, Go and Swift repos
included.

### Design

1. The bare `punt enable` deposits the selected language sets into the
   repo's own `.claude/rules/`, beside the guide, the `enabled` marker, and
   the import line it already owns. Re-running it is the update. `punt
   disable` leaves the rules in place.
2. Selection is a `[rules] languages` list in `.punt-labs/punt/config.toml`
   when present, else every language whose root marker is present.
3. Each deployed file is byte-identical to its canonical source and carries
   the language prefix in its name. The manifest
   `.punt-labs/punt/rules-manifest.toml`, persisted in punt's vendored zone,
   is the only record of which paths punt owns. `enable` overwrites
   manifest-listed paths, removes old-manifest-minus-new, refuses a
   collision with a foreign file, and never touches any other path.
4. `punt audit` fails on any deployed file that differs from the installed
   punt-kit's canonical file, any missing file, and any canonical file the
   manifest omits; `--fix` refreshes through the same deployer.
5. The canonical sets live in `src/punt_kit/lang_rules/` so the wheel ships
   them.
6. The workspace meta-repo deletes its `.claude/rules/` after every Python
   child has its own set, and hosts no set while the upstream defect is
   open.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| A `punt rules install` / `update` noun group beside `enable` | Two names for one idempotent deposit (DES-027); § 2.3 already assigns shipped files to `enable`. |
| Deploy from `punt init` | § 2.13 keeps `init` to one-time scaffolding; rules are maintained guidance. |
| Provenance comment inside each deployed file | Breaks byte-equality; the manifest is the provenance the punt-labs-dir standard already requires. |
| Rewrite `paths:` per repo | Per-repo variants of a canonical file; globs are root-relative and already portable. |
| Redeploy a current set in the workspace for its `.bin/` Python | The ancestor path loads it into every nested session regardless of `paths:`; the flood continues with current content. |
| Symlink or build-time copy of `lang-rules/` into the package | A link is backend-dependent; a copy is a second source of drift. |
```

---

## 7. Operator decisions

Each item deviates from a settled ADR, a standard, or the operator's bead
text, and is phrased for a one-word ruling.

1. **The workspace deploys no rule set while anthropics/claude-code#16299 is
   open.** The bead (pkit-z711) says the workspace "installs its OWN set (for
   `.bin/` Python) via the same mechanism" and that the fix holds "by
   construction". It does not: the ancestor path loads any `.claude/rules/`
   in the workspace, current or stale, into every nested session. Deleting the
   directory is what ends the flood. Recommend: the workspace deletes
   `.claude/rules/` and runs no `punt enable` for rules until the upstream fix
   ships; `.bin/` Python stays under its own three-requirement exception.
   Confirm or course-correct.
2. **`punt enable` writes outside `.punt-labs/`.** tool-enable-disable.md
   § 2.8 lets `enable` touch exactly one file outside its subtree
   (`.claude/settings.json`), and punt-labs-dir.md § 1 and § 2 say a tool
   keeps no per-repo state outside `.punt-labs/`. Claude Code reads rules
   only from `.claude/rules/`, so the deposit must land there. Recommend:
   amend § 2.8 and punt-labs-dir § 2 so `.claude/rules/` joins
   `.claude/settings.json` as a Claude-Code-dictated location a tool may
   write, bounded by the manifest. Confirm or course-correct.
3. **The verb is the bare `punt enable`, not a `repo-install` /
   `repo-update` verb.** The bead names the latter; DES-024, § 2.10, and
   pkit-pjwn name the former. Recommend `enable` (§ 4). Confirm or
   course-correct.
4. **This unit takes the bare `punt enable` and `punt disable` from
   pkit-pjwn.** pkit-pjwn keeps `punt install <tool>`, the `<tool>` dispatch
   forms, the `init` shrink, and the `status` matrix. Recommend the split.
   Confirm or course-correct.
5. **The canonical home moves from `lang-rules/` to
   `src/punt_kit/lang_rules/`.** `CLAUDE.md` and DES-028 list `lang-rules/`
   as a root directory; the move is what makes the wheel ship it with no
   second copy. Recommend the move. Confirm or course-correct.
6. **`lang-rules/c/tests.md` is renamed `c-tests.md`.** Every deployed file
   then carries its language prefix, and the generic name cannot collide
   with a repo's own `tests.md`. Recommend the rename. Confirm or
   course-correct.
7. **`punt audit --fix` refreshes a drifted set.** A second door to the
   deployer, through the same class. Recommend yes, on the precedent that
   `--fix` creates what `init` creates. Confirm or course-correct.
8. **A locally edited deployed file is overwritten and reported, not
   refused.** This follows punt-labs-dir § 7's wholesale-overwrite contract
   for the vendored zone; it is listed because the bead does not say what
   happens to such a file. Recommend overwrite with a printed line per file.
   Confirm or course-correct.

---

## 8. Implementation write-set

One line per file. Paths are relative to the punt-kit root unless marked
workspace or child.

### Code

| File | Purpose |
|------|---------|
| `src/punt_kit/lang_rules/{python,go,c,swift}/*.md` | The canonical sets, moved from `lang-rules/`; `c/tests.md` renamed `c-tests.md`. |
| `src/punt_kit/lang_rules/README.md` | Moved; the "deployed elsewhere" text replaced by the `punt enable` mechanism. |
| `src/punt_kit/detect.py` | `ProjectInfo` gains `languages: tuple[str, ...]`, every language whose root marker is present, in canonical order; `language` stays the primary. |
| `src/punt_kit/rules_selection.py` | `RuleSelection`: reads `[rules] languages` from `config.toml` or falls back to `ProjectInfo.languages`; validates names against the shipped set. |
| `src/punt_kit/rules_manifest.py` | `RuleManifest`: load, compute from a selection and the shipped set, diff previous against new, write. |
| `src/punt_kit/rules_deployer.py` | `RuleDeployer`: the write, remove, refuse, and bootstrap algorithm of § 3.5; reports replaced local edits. |
| `src/punt_kit/claude_md_import.py` | `ClaudeMdImport`: the § 2.4 import-line writer (lock, atomic replace, byte-preserving, host EOL, code-block skip), ported from vox's `claude_md.py`. |
| `src/punt_kit/enable.py` | `run_enable` / `run_disable`: guide deposit from `templates/punt-guide.md`, marker, import line, rules. |
| `src/punt_kit/audit_rules.py` | `RulesAudit(info).findings`: the § 3.6 check; `--fix` path calls `RuleDeployer`. |
| `src/punt_kit/audit.py` | Registers `RulesAudit` in the checks tuple. |
| `src/punt_kit/__main__.py` | `enable` and `disable` commands. |
| `plugin/commands/enable.md`, `enable-dev.md`, `disable.md`, `disable-dev.md` | Slash equivalents wrapping the CLI. |

### Tests

| File | Purpose |
|------|---------|
| `tests/test_detect.py` | `languages` for single, dual, and no-marker repos. |
| `tests/test_rules_selection.py` | Declaration wins, empty list, unknown name errors, detection fallback. |
| `tests/test_rules_manifest.py` | Round trip, diff, sorted paths. |
| `tests/test_rules_deployer.py` | Fresh deploy, idempotent re-run, upgrade overwrites, old-minus-new removal, collision refusal, bootstrap grandfather, foreign files untouched, local-edit report. |
| `tests/test_claude_md_import.py` | Append once, CRLF host, fenced-block skip, byte preservation, symlink target. |
| `tests/test_enable.py` | Full deposit set; `disable` leaves guide and rules. |
| `tests/test_audit_rules.py` | Each verdict row of § 3.6; `--fix` with and without the marker. |
| `tests/test_packaging.py` | The built wheel contains `lang_rules/python/`. |
| `tests/test_cli.py` | `punt enable --help`, `punt disable --help`. |

### Docs and standards

| File | Purpose |
|------|---------|
| `standards/tool-enable-disable.md` | § 2.8 and § 2.10 amended per decision 2; § 2.11 gains the rules check; two `../lang-rules/` links rebased. |
| `standards/punt-labs-dir.md` | § 2 carve-out for `.claude/rules/` per decision 2; one `../lang-rules/` link rebased. |
| `standards/python.md`, `go.md`, `c.md`, `swift.md` | The sentence that names `.claude/rules/<lang>-*.md` says the files are deployed by `punt enable` from punt-kit. |
| `DESIGN.md` | DES-038 from § 6. |
| `CLAUDE.md` | The repository-layout list and the `demo_exempt` list name `src/punt_kit/lang_rules/` instead of `lang-rules/`. |
| `README.md` | The `lang-rules/` pointer and the install-excludes sentence updated; `punt enable` and `punt disable` documented. |
| `CHANGELOG.md` | Added: `punt enable`, `punt disable`, the rules audit check; Changed: canonical sets move into the package; Removed: `lang-rules/` at the root. |

### Workspace repo (separate PR, after every Python child has merged)

| File | Purpose |
|------|---------|
| `.claude/rules/` | Deleted. |
| `.bin/rules-rollout.sh` | Runs `punt enable` in each child in a worktree and opens the PR, on the `tracker-guide-rollout.sh` pattern; the rollout vehicle for step 2 of § 3.8. |
| `.gitignore` | No change while the workspace deploys nothing; when it later does, `!.punt-labs/punt/config.toml` and `!.punt-labs/punt/rules-manifest.toml` join the per-file allowlist. |

### Child repos (one PR each)

| File | Purpose |
|------|---------|
| `.punt-labs/punt/rules-manifest.toml`, `.claude/rules/<lang>-*.md` | The deposit from `punt enable`. |
| `.punt-labs/punt/CLAUDE.md`, `.punt-labs/punt/enabled`, `CLAUDE.md` | Unchanged in the ten repos the tracker-guide rollout covered; deposited in the rest. |
| z-spec `.claude/rules/python-standards-pointer.md` | Deleted. |
