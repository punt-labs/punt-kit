# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- `standards/python.md` now mandates `uv_build` rather than `hatchling`
  as the build backend, with DES-026 recording why. The standard had
  said `hatchling` since punt-kit's first commit while ten of the twelve
  Python repos migrated to `uv_build`; punt-kit was one of the two that
  did not, and the one that leaked local agent session logs into a
  published sdist. Hatchling's default sdist ships everything not
  VCS-ignored — fails open — while `uv_build` ships the declared module
  and fails closed by construction
- punt-kit migrated to `uv_build`, and the
  `[tool.hatch.build.targets.sdist]` allowlist added in 0.12.0 is deleted
  — there is no longer a list to keep current. Verified by building both
  backends and diffing member lists: the wheel is unchanged in content
  (templates and `py.typed` still ship) and the sdist drops from 151
  members to 31, carrying `src/` and metadata only. The migration
  silently dropped `LICENSE` from the wheel until PEP 639
  `license-files` was added — a licensing regression the member diff
  caught and a test now guards
- DES-026's repo census corrected: refactory declares `hatchling` too, so
  the fleet had two hatchling repos, not one. The original count came from
  grepping a three-line window after `[build-system]`, which refactory's
  multi-line `requires` pushed `build-backend` out of; parsing the TOML
  gives the right answer. The incident and the decision are unchanged —
  the count is not, nor is the method that produced it. refactory migrates
  in punt-labs/refactory#34, where the same fails-open default was live:
  its sdist carried 303 members, 245 of them `.punt-labs/` submodule
  content plus `.envrc` and `.beads/`, against 12 members of actual `src/`

- Dependency upgrades, consolidating five Dependabot PRs that all edited
  `uv.lock` and therefore conflicted with each other: mypy 1.19.1 → 2.3.0,
  ruff 0.15.1 → 0.16.3, pyright 1.1.408 → 1.1.411, rich 14.3.2 → 15.0.0,
  typer 0.24.0 → 0.27.1, pytest 9.0.3 → 9.1.1
- ruff 0.16 formats Python code blocks inside Markdown, which reformatted
  12 documentation files. The change is meaning-preserving but it does
  flatten column-aligned comments in the teaching examples under
  `lang-rules/`. Accepted deliberately: those documents teach the style
  `ruff format` enforces, so samples that disagree with the formatter
  teach a style the formatter would immediately undo

## [0.13.0] - 2026-08-14

### Fixed

- `standards/permissions.md` claimed Claude Code does not enforce
  `Skill()` permission rules. It does. `SkillTool` has its own permission
  layer: deny rules win first, then explicit allow rules are honored, and
  anything outside the safe-property allowlist prompts the user. The
  seeded `Skill()` entries are therefore load-bearing, not the dead
  weight the standard described, and the audit checklist no longer tells
  projects to remove them
- The seeded `Skill()` list was 16 entries wrong: 3 named
  `commit-commands`, which is not a Punt Labs plugin and was never
  installed, and 13 real skills were missing including `biff:poll`,
  `vox:music` and `quarry:use`. It is now generated from the installed
  plugin set (86 entries across 10 plugins), with `make skills-check` to
  report drift. That target is deliberately not in `make check`: it can
  only see plugins installed on the machine running it, and CI has none,
  so a gate there would pass vacuously. The old test encoded the drift — it
  asserted the non-existent `Skill(commit-commands:commit)` was present,
  so it passed while the list was wrong

### Changed

- `punt init` no longer seeds `Bash(bash:*)` or `Bash(sed:*)`.
  `Bash(bash:*)` permits any command — `bash -c "<anything>"` matches it —
  which made every other Bash entry decorative and reached straight
  through the deny rules, since `bash -c "curl ..."` satisfies the allow
  list while `Bash(curl:*)` is denied. A scaffolded repo was getting an
  unrestricted shell in a committed file nobody re-reads. `Bash(sed:*)`
  edits any file in place, bypassing the `Edit(path)` rules. `git` and
  `gh` are unchanged — they are development tools and this scaffolds a
  development environment
- The seeded MCP wildcard list is now every Punt Labs plugin that ships an
  MCP server, rather than a subset. It previously named
  `mcp__plugin_github_github__*`, for which no plugin exists, so it had
  never matched anything; carried two spellings of quarry; and omitted
  beadle, dungeon, ethos, lux, vox and z-spec. Each entry is now derived
  from the plugin's own manifest, and a test asserts the list still
  matches
- `punt init` no longer appends `.claude` exception lines to a `.gitignore`
  stanza it did not write (pkit-zzx3). The guard was a substring test, so a
  `.claude/*` parent satisfied it and the negations were appended to the end
  of the file. Those lines are inert under the `.claude/` parent punt writes —
  git never descends into an excluded directory — but live under `.claude/*`,
  so seeding *activated* a re-include that had never taken effect in that
  repo's history. A foreign stanza is now reported and left untouched. This is
  the same never-activate discipline the permission seeder got in 0.12.0,
  applied to the gitignore seeder

## [0.12.0] - 2026-08-13

### Fixed

- The source distribution no longer ships every untracked file in the
  working tree (pkit-fkkv). Hatchling's default sdist includes everything
  not VCS-ignored, so editor config, scratch files, local agent state, and
  internal tracker content were all published — permanently and unlistably.
  `pyproject.toml` now declares an explicit
  `[tool.hatch.build.targets.sdist]` allowlist, so the sdist ships what it
  names rather than whatever happens to be present: 566 members before,
  148 after, nothing added. The wheel was never affected, which is why a
  wheel-only check reported clean

- `punt init` no longer seeds `Write(.env)` and `Write(.envrc)` deny
  rules (pkit-lv32) — Claude Code matches path-scoped rules under
  `Edit(path)` only, so both entries matched nothing and produced a
  startup warning; the `Edit(.env)` / `Edit(.envrc)` twins already cover
  the Write tool, so no guard was ever unenforced
- `standards/permissions.md` documented `Write(path)` as valid syntax in
  three sections and prescribed injecting non-MCP plugin rules into the
  user's global `~/.claude/settings.json` (pkit-lv32); §6 now scopes
  plugin rules to the project's own `.claude/settings.json`, granted by
  the plugin's permissions command rather than by its installer, with
  MCP tool wildcards as the sole global exception

- `punt release` propagation now pins the org profile README to the
  install-all.sh commit that exists AFTER the install-all.sh PR merges
  (pkit-vmo) — the pin was captured before the merge, leaving the profile
  one commit behind (serving the previous installer) on every release;
  the profile sync is a second sequential PR, also repairs stale pins on
  resume, and Phase 11 verify now fails on a resolvable-but-stale pin
- `punt release` preflight now fails on untracked files (pkit-v3k) —
  previously they passed preflight and were swept into release commits
  by `git add -A`; the version-bump and post-release commits also stage
  their edit set explicitly (pyproject.toml, CHANGELOG.md, install.sh,
  plugin.json, uv.lock, `__init__.py`; README.md) instead of `git add -A`
- `punt release` no longer aborts when the post-merge branch deletion
  404s (pkit-k5j, pkit-u8f): repos with "automatically delete head
  branches" remove the branch during the squash merge, so gh's own
  deletion fails after a successful merge; the merge helper now checks
  the PR's actual state and treats a MERGED PR as success regardless of
  the deletion exit code
- `punt release` no longer resumes on stale same-named release PRs
  (pkit-g0gv): a CLOSED PR (dead CI, infinite wait) and a MERGED PR whose
  head does not match the local release branch (skipped bump, wrong tag)
  are now ignored and a fresh PR is created; a MERGED PR counts only when
  its `headRefOid` matches the local branch head
- Incomplete URL substring sanitization in the marketplace check flagged by
  code scanning (alert 5): the GitHub host comparison now parses the URL
  instead of substring-matching it
- `punt init` no longer writes broken permission entries, and the generated
  `docs.yml` workflow globs match the files it lints

### Added

- `punt audit` reports permission rules Claude Code can never match
  (pkit-lv32) — `Write(path)`, `MultiEdit(path)`, `NotebookEdit(path)`,
  and `Glob(path)` are not valid rule forms; each one warns at every
  session start in every project that carries it. Both
  `.claude/settings.json` and `.claude/settings.local.json` are checked,
  since Claude Code warns for either
- `punt init` removes unmatched path rules from both settings files. It
  drops them and never rewrites them, in any tier, so effective
  permissions are identical before and after — every rule it removes was
  already inert. Rewriting an orphan would switch on a grant (`allow`) or
  a block (`deny`, `ask`) that has never been in effect, which is a policy
  change, not a cleanup. Each removal is printed with which case it was:
  redundant with an existing live twin, or a rule that never took effect
  and may need the live form added deliberately
- `standards/pr-review.md` and `standards/agent-engineering.md` — the PR/review
  sequence and the agent operating rules, split out of the old workflow doc
  into their own normative homes
- `standards/architecture.md` (engine-and-clients model), `standards/oo.md`
  (the cross-language OO stance), and per-language standards for Go, C, Swift,
  and Pharo
- `lang-rules/` — the per-language coding-rules corpus agents load
  automatically: canonical Go rules (4 files), canonical Swift rules (7 files,
  38 rules), and a generalization pass over the seeded Python and C rules,
  with a README status table
- `punt init` standard permissions now include 77 `Skill()` entries covering
  the org plugin surface

- `standards/agent-engineering.md` §16 — when a tool's behavior contradicts
  its source, suspect a stale installed binary before writing a fix
  (pkit-dgel): `git tag --contains <fix-commit>` plus a `<tool> --version`
  comparison distinguishes "not implemented" from "implemented but never
  released", where the remedy is a release rather than a patch. Cross-linked
  from §2 (root-cause tracing). Motivated by ethos-kptv, where a
  release-tooling defect was queued for implementation although both fixes
  were already correct on `main` and merely unshipped.
- `standards/git.md` — git mechanics standard (pkit-krc8): the local git
  operations between starting work and pushing it, owning what no punt-labs
  doc previously did. Covers the branch check before every commit, the
  no-rebase / no-force-push rule on open-PR branches with conflict resolution
  by merging `origin/main` (both SHA-preserving), the post-merge cleanup
  ordering (`branch -d` before `fetch --prune`, with the squash-merge
  reachability rationale), worktree lifecycle and the removal obligation,
  submodule mechanics (gitlink, detached HEAD normal, update-and-commit-the-ref,
  leading `-` means uninitialized), the `Mission:` / `Delegation:` commit-trailer
  convention for mission traceability, the stop-and-ask list harmonized with
  the org `CLAUDE.md` Destructive Operations enumeration, and the
  session-close push plus plain-English-over-`HEAD` rule for PR prose.
  Generalizes the most advanced deployed practice (`xboing-c/docs/GIT.md`) to
  punt-labs; mechanics only, cross-referencing workflow.md / pr-review.md /
  github.md and duplicating none of the PR loop, merge gate, or branch-prefix
  table. Wired into AGENTS.md, README.md, and the Related Standards lists of
  workflow.md and pr-review.md
- `standards/install-cli-only.md` — CLI-only install standard: every tool
  whose `install.sh` installs both a CLI and a Claude Code plugin MUST offer a
  `--no-plugin` flag and `<TOOL>_NO_PLUGIN=1` env var (strict `=1`) that skip
  **only** the marketplace-register and plugin-install steps, work over
  `curl … | sh` via `sh -s -- --no-plugin` and `<TOOL>_NO_PLUGIN=1 sh`,
  resolve through a single boolean OR (flag OR env OR capability-absence
  auto-skip) with no counter-flag, gate CLI-only success messaging on the skip
  boolean (no "restart Claude Code" line), and never auto-detect an enterprise
  policy block by probing the plugin command. Includes a 10-item conformance
  checklist. Reference implementation: ethos `install.sh` (v-next), ratified as
  ethos ADR DES-063
- `standards/punt-labs-dir.md` — repo-local state directory standard:
  `<repo>/.punt-labs/<tool>/` tool roots plus the machine-local
  `.punt-labs/local/` zone, committed except local-convention paths
  (`local/`, `*.local`, `*.local.*`), live state never tracked (the
  chunk-based seal pattern, per the ethos DES-058 design), the canonical
  gitignore block, and subtree zones (vendored/config/local/marker) scoping
  the tool-enable-disable §2.2 wholesale-overwrite contract to the vendored
  zone only

### Changed

- **Breaking:** `punt auto <target>` is now `punt seed <target>` (pkit-xych).
  The managed-section renderer shared a name with the `/punt:auto` slash
  command, which runs playbooks; the CLI side takes the new name and the
  slash command keeps its own. There is no alias and no deprecation shim —
  scripts and playbooks invoking `punt auto` must be updated.
- `prfaq.tex` rewritten to describe the product punt-kit is (pkit-batl):
  an internal kit manager for the Punt Labs org — standards, tools,
  workflows, compliance — whose customer is the operator and the org's
  agents, with `/punt:auto` as the self-prompting engine and the drafted
  prompt state-machine DSL as the centerpiece investment. Claims the
  earlier version made and the tool never shipped are removed as
  capability: standards parsed into checkable assertions and `punt
  preflight` are retired in Won't Do, and a dedicated `punt rollout`
  command is retired there for the real reason — the `standards-rollout`
  and `permissions-rollout` playbooks already do the job. The MCP server
  and the REST surface stay committed as Should Do roadmap items — the
  engine-and-clients model in `standards/architecture.md` remains the
  destination, with the press release and Must Do describing shipped
  capability only. The tools pillar is named as the kit-manager direction
  rather than a shipped command, since punt has no `install` or `enable`
  at 0.11.2; the planned surface is specified as dispatch (`punt install
  <tool>` runs that tool's `install.sh`, `punt enable <tool>` delegates to
  `<tool> enable`) because `tool-enable-disable.md` §2.2–2.3 give the
  vendored zone, the marker, and the verbs to each tool itself. Market
  sizing and external-adoption strategy are explicitly deferred rather
  than dropped; the fictional customer testimonial is replaced with an
  internal voice. Stage macro moves from `hypothesis` to
  `internal-adoption` (README badge follows) and the document version to
  2.0; `prfaq.bib` drops the twelve entries that only propped the
  external-market case
- `standards/workflow.md` merge_gate Copilot condition corrected (pkit-krc8):
  the pseudocode assumed Copilot re-reviews on every push, which holds in
  punt-kit but not fleet-wide (other repos review once on open). The gate now
  encodes the silence-after-fix rule — if Copilot reviewed an earlier commit
  but not the latest and CI has been green for more than ten minutes, treat
  the silence as no-new-findings; a first review is always required. The
  gate's shape is unchanged
- `standards/workflow.md` rewritten around the ethos mission harness
  (pkit-k4fg): tiers tied to pipeline templates, typed mission contracts
  replace prose delegation, required-vs-optional thresholds, normative
  human-in-the-loop gates (design→implementation ratification), and
  ownership boundaries with pr-review.md / agent-engineering.md /
  makefile.md — review internals and checklists now live solely in their
  owner docs. Cross-references in `standards/pr-review.md` and
  `CLAUDE.md` repointed accordingly.
- Standards round-up (pkit-e7m2): `tool-enable-disable.md` §2.4 gains four
  write-contract corrections from biff's reference implementation
  (balanced-pair fences, the mandated `.<host-file-name>.punt-import.lock`
  shared lock, non-indented delimiters only, same-marker close of length ≥
  opener) and names biff's `ClaudeMdImport` as the canonical reference;
  `punt-labs-dir.md` §4 gains the redaction-at-write clause for committed
  content (DES-058) with a `punt pii` audit cross-ref in §8; `python.md`
  gains a Version Reporting section (`importlib.metadata.version`, no
  literal `__version__`); `patterns/claude-md-injection.md` renamed to
  `claude-md-import-includes.md` with all links updated
- `standards/punt-labs-dir.md` — local-zone amendment per the operator's
  DES-058 overturn: `.punt-labs/local/<tool>/` named as the org convention
  for per-checkout machine-local live state (the one non-tool entry under
  `.punt-labs/`, covered by the existing canonical-block line); §5 seal
  pattern updated to chunk-based add-only sealing citing the settled
  DES-058 invariants (immutable chunks, `(session, ts)` identity, frozen
  legacy lines undeduped); ethos §10 rows moved to local-zone live paths
  with the gitlink case as signaled deferral, bounded until vendored
- The `/punt auto` executor-protocol skill moved from
  `.cursor/skills/auto/SKILL.md` to `skills/auto/SKILL.md` at the plugin root,
  severing it from the removed `.cursor/` tree; `commands/auto.md` and
  `commands/auto-dev.md` repointed to the new path (no behavior change)
- Standards revisions across the corpus: `go.md` adopts golangci-lint as the
  Go lint gate (Go Report Card successor) and documents the staticcheck
  GOTOOLCHAIN workaround; `logging.md` revised from the vox logging audit;
  `distribution.md` gains the daemon v3 pattern and mandates
  uninstall-before-install with failure detection in `install.sh`;
  `permissions.md` requires bare `Read`/`Write`/`Edit` for sub-agents;
  `agent-engineering.md` §8 bans process narration in comments and
  docstrings; `readme.md` settles section naming, the Go badge set, and
  states its audience (users); the CLAUDE.md `@`-import include convention
  is documented global-first with vox as the reference implementation

### Removed

- `punt auto claude` target, the `CLAUDE_SECTIONS` registry, and the four
  CLAUDE.md section templates (quality-gates, beads, standards-references,
  available-tooling), superseded by the tool-enable-disable standard — one
  `@`-import line per enabled tool instead of rendered managed sections.
  Makefile managed sections (`punt auto makefile`) are unaffected
- `playbooks/claude.yaml` — its only job was running `punt auto claude`
  across child repos
- `/punt claude2cursor` and its `-dev` variant, plus the
  `Skill(punt:claude2cursor)` permission `punt init` wrote into
  `.claude/settings.json`. Operator ruling (pkit-k29q, product rethink): the
  Cursor-conversion command is cut from punt-kit entirely — no deprecation
  shim, no stub
- The generated `.cursor/` tree that was `claude2cursor`'s output —
  `.cursor/commands/`, `.cursor/rules/punt-kit-context.mdc`,
  `.cursor/punt-generated.json`, and the per-command skills under
  `.cursor/skills/` — orphaned once nothing regenerates it. The hand-authored
  `/punt auto` executor protocol, which lived at `.cursor/skills/auto/SKILL.md`
  because the generator wrote alongside it, is preserved (see Changed)

## [0.11.2] - 2026-03-29

### Changed

- Release CI: removed TestPyPI and test-install jobs from `release.yml`. The
  pipeline is now `build → pypi` (was `build → testpypi → test-install → pypi`),
  cutting CI wait from ~20 minutes to ~3 minutes
- Release phases 9 (post-release) and 10 (propagate) now run concurrently
- Phase 10 propagation PRs (.github, claude-plugins, public-website) now run
  concurrently via ThreadPoolExecutor, with error collection across all three
- Playbook executor: script steps support `background: true` for non-blocking
  execution; LLM steps delegate to background sub-agents. Main agent stays
  responsive during long-running playbook steps

### Fixed

- `restore-dev-plugin.sh`: find dev commit by content instead of `HEAD~1`
  position, which broke when multiple PRs merged between the release tag and
  Phase 9 post-release

## [0.11.1] - 2026-03-28

### Changed

- `install-all.sh` moved from punt-kit to the `.github` org repo. Child project
  releases now update SHAs directly in `.github/install-all.sh` and the org
  profile README in a single PR. Phase 10c (`_propagate_profile`) eliminated —
  punt-kit is no longer in the release critical path for child projects.
- Phase 11 verify profile SHA check now validates that the SHA in the README
  resolves to a real `install-all.sh` file, rather than comparing against the
  latest `git log` SHA (which changes after PR merge).

### Fixed

- `punt release` CI wait now polls only required checks via
  `gh pr view --json statusCheckRollup` instead of blocking on all checks
  with `gh pr checks --watch`. Non-required checks like "Claude Code Review"
  no longer hang the release process indefinitely.
- `punt release` preflight and sibling dirty-tree checks now exclude
  `.beads/` paths — both untracked (`??`) and tracked (`M .beads/issues.jsonl`)
  files. The beads daemon continuously writes `issues.jsonl`, which was
  blocking every release during active sessions.
- `punt release` removes manual PyPI approval gate (`environment: release`)
  from `release.yml`. TestPyPI + test-install verification is sufficient.
- Profile propagation during `punt release` no longer silently skips when
  `--resume-from propagate` detects install-all.sh is already current. The
  `_propagate_install_all` step's own `new_content == content` check now
  correctly handles the "already current" case.
- `punt release` Phase 10 auto-recovers sibling repos left on `propagate/v*`
  branches from prior interrupted runs. SIGINT/SIGTERM handlers return siblings
  to main on interrupt. Non-propagation branches (feature work by other agents)
  are never touched.
- `_resolve_pr_threads` now logs JSONDecodeError and reports accurate
  resolved/attempted thread counts instead of silently swallowing errors.
- `_sibling_pr_merge` finally block now logs checkout failures instead of
  silently discarding them.

## [0.11.0] - 2026-03-28

## [0.10.0] - 2026-03-28

### Added

- `reconcile-memory` playbook — consolidates auto-memories into CLAUDE.md
  layers, eliminating duplication and promoting general content upward.
  Run via `/punt:auto reconcile-memory`. Supports `scope` parameter:
  `memories` (consolidate only), `project` (project CLAUDE.md), `full`
  (all three levels including org CLAUDE.md install).

### Fixed

- `punt release` Phase 10c now uses the last commit that touched
  `install-all.sh` instead of HEAD for the org profile SHA.

## [0.9.0] - 2026-03-28

### Added

- `punt doctor` command — checks Python version, uv, ruff, mypy, pyright
  availability with pass/fail per dependency
- `punt status` command — shows detected project type, language, plugin/MCP
  status, and beads counts for the current project
- Global flags: `--json`, `--verbose`/`-v`, `--quiet`/`-q` on all commands.
  `--json` produces machine-readable output; `--verbose` and `--quiet` are
  mutually exclusive
- CLI integration tests via typer CliRunner (10 tests)

### Changed

- `punt version` now uses plain `print()` instead of Rich `console.print()`,
  matching cli.md standard. Supports `--json` output.
- Help text is now plain text (no Rich panels/box-drawing characters)
- App tagline follows cli.md format: `punt: <description>`

### Fixed

- `punt release` Phase 10c (org profile SHA update) now runs after every
  release that modifies `install-all.sh` via Phase 10a, not only during punt-kit
  releases. Previously, releasing biff/quarry/ethos/etc. updated `install-all.sh`
  in punt-kit but left the org profile pointing to the old punt-kit commit,
  causing users to install stale versions.
- `punt release` now runs `release-plugin.sh` and `restore-dev-plugin.sh` for
  pure plugin projects (not just hybrid). Previously, Go+plugin projects like
  ethos shipped with `-dev` names. (wy5)
- `punt release --verify` now recognizes pure-plugin entries in the
  `for plugin in ...` loop in `install-all.sh`, instead of reporting
  "entry not found". (pvb)
- Added `Lux.ini` to `.gitignore` to prevent the lux plugin config file from
  blocking release preflight's clean-tree check. (6wa)
- `punt release` propagation branches now include the source project name
  (e.g., `propagate/v0.14.1-z-spec-claude-plugins` instead of
  `propagate/v0.14.1-claude-plugins`), preventing collisions when two
  projects release the same version. (srn)

## [0.8.0] - 2026-03-21

### Added

- **CLI help text as agent interface** — cli.md now frames `--help` as an agent
  interface (not just human convenience), requires flags to show defaults/types,
  and requires `--json` to be mentioned in help text
- **Remote mode standard** — cli.md `--remote <url>` pattern for projects with
  `serve` commands, enabling CLIs to consume their own HTTP APIs as an
  alternative to local execution
- `punt auto <target>` command — marker-based section management for CLAUDE.md, Makefile, and settings.json. Renders Jinja2 templates and merges managed sections while preserving local content.
- Templates for CLAUDE.md (7 sections: no-preexisting, scratch-files, quality-gates, code-review, pre-pr-checklist, standards-references, available-tooling)
- Templates for Makefile (python targets, help target)
- Playbooks for cross-repo rollout (`claude.yaml`, `makefile.yaml`)

### Fixed

- `punt release`: preflight (phase 1) now validates sibling repos are on main with clean trees before starting — previously failed mid-propagation (phase 10)
- `punt release`: `_sibling_pr_merge` returns sibling to main branch even on failure — previously left siblings on stale propagation branches
- `punt release`: merge retry with backoff (up to 6 attempts) when branch protection blocks merge due to pending checks or unresolved conversations
- `install-all.sh`: update biff install SHA from 9149bdc to 6647733 (v1.3.6)

## [0.7.8] - 2026-03-13

## [0.7.7] - 2026-03-13

### Fixed

- `punt release`: `_pr_merge` CI wait retries up to 60s when checks haven't started yet (was failing immediately with "no checks reported")
- `punt release`: `_pr_merge` auto-resolves Copilot/Bugbot review threads before merging (was blocked by `required_review_thread_resolution`)
- `punt release`: Phase 9 re-stamps plugin.json version after dev restore (restore script reverts version along with name)

## [0.7.6] - 2026-03-13

### Changed

- `punt release`: route all main-branch changes through PRs instead of direct push (DES-016) — required by zero-bypass branch protection (DES-015)
- `punt release`: expand from 9 phases to 11 — split old Phase 4 (tag+push) into Phase 4 (release-pr) + Phase 5 (tag), add Phase 9 (post-release) for dev restore + README SHA bump
- `punt release`: sibling propagation (Phase 10) uses PRs via `_sibling_pr_merge` instead of `_sibling_commit_push`

## [0.7.5] - 2026-03-13

### Changed

- `restore-dev-plugin.sh`: add `[skip ci]` to commit message across all 5 hybrid repos (punt-kit, biff, quarry, vox, lux) — prevents unnecessary CI runs on post-release dev-state restore
- `/punt:auto` playbook executor: run preconditions as parallel Bash calls (not `&&` chains) so each matches its allowed-tool pattern and auto-approves
- `release` playbook: remove redundant preconditions — `punt release` Phase 1 already validates project type, branch, clean tree, origin sync, scripts, changelog, and quality gates

## [0.7.4] - 2026-03-13

### Fixed

- `punt release` Phase 4e/8a/8d: use `git log -1 -- install.sh` for SHA resolution instead of `git rev-parse <tag>` — the tag points to the "prepare plugin" commit, not the version-bump commit that actually modifies install.sh

## [0.7.3] - 2026-03-12

### Fixed

- `punt release` Phase 2: refresh `uv.lock` after version bump to prevent dirty working tree in Phase 8
- `punt release` Phase 8: exclude untracked files from sibling clean-tree check
- `punt release` Phase 8/9: handle `null` values in website `projects.json` (`githubUrl: null`)
- `punt release` Phase 9: use `uv run pip index versions` for PyPI verification (was `uv pip index`, which doesn't exist)

## [0.7.2] - 2026-03-12

### Changed

- `punt release` Phase 8: local cross-repo propagation replaces GitHub Actions workflows — direct push to sibling repos instead of workflow dispatch, PRs, and async polling
- `punt release` Phase 9: verification phase checks all release requirements (version consistency, changelog, install-all.sh, marketplace, profile, website, PyPI)
- `punt release --resume-from <phase>`: resume interrupted releases from any phase

### Removed

- GitHub Actions propagation workflows (`propagate.yml` in punt-kit, claude-plugins, .github; `propagate-profile.yml` in punt-kit)
- Release playbook (`playbooks/release.yaml`) — CLI handles everything

## [0.7.1] - 2026-03-11

### Fixed

- Release playbook: replace manual `merge-propagation-prs` step with `settle` — waits for auto-merge instead of merging manually
- Release playbook: remove `update-github-profile` step — handled automatically by propagation chain (`propagate-profile.yml`)
- Marketplace propagation workflow (`claude-plugins`): use `PROPAGATE_TOKEN` for auto-merge (was `GITHUB_TOKEN`, which can't bypass branch protection)

## [0.7.0] - 2026-03-11

### Added

- Plugin: `/punt:auto <playbook>` — general-purpose automation agent that executes YAML playbooks with deterministic scripts and LLM error recovery
- Playbook schema: YAML format for defining multi-step processes with `script` (deterministic) and `llm` (judgment) step types, postconditions, and failure strategies
- Playbooks: `autopilot` (bead-driven dev loop), `permissions-rollout` (cross-repo permission changes), `standards-rollout` (cross-repo standards changes), `release` (full release workflow with verification)

## [0.6.3] - 2026-03-11

### Fixed

- Release workflow: increase TestPyPI propagation retry from 5×30s (2.5min) to 30min exponential backoff (15s→120s cap)
- Release template: add missing `skip-existing: true` and `--index-strategy unsafe-best-match` (drift from live workflow)

## [0.6.2] - 2026-03-10

## [0.6.1] - 2026-03-10

### Fixed

- `install.sh` now pins `VERSION="X.Y.Z"` for deterministic installs (was missing, installed latest from PyPI)
- Standards: `distribution.md` updated with propagation chain, README SHA auto-update, `PROPAGATE_TOKEN` requirements, mandatory VERSION pin
- Standards: `DESIGN.md` DES-008 known gap list updated (punt-kit and biff fixed; quarry and langlearn-tts remain)
- Standards: `DESIGN.md` DES-012 updated with `PROPAGATE_TOKEN` fine-grained PAT requirements and org approval policy gotcha

## [0.6.0] - 2026-03-09

### Added

- GitHub Action: `propagate-profile.yml` auto-updates `.github` profile README SHA when `install-all.sh` changes on main (closes propagation gap between child releases and punt-kit releases)

### Fixed

- `punt release` now auto-updates project README install.sh SHA pins after tagging (previously required manual update)
- Public install URL served stale `install-all.sh` between punt-kit releases, causing child version downgrades (DES-012)

## [0.5.0] - 2026-03-09

## [0.4.0] - 2026-03-09

### Added

- Plugin: `/punt claude2cursor` command converts plugin commands to Cursor-compatible skills, slash commands, and rules
- Plugin: `/punt claude2cursor` dev variant for local working tree conversion
- Generated Cursor artifacts: 6 skills, 6 commands, context rule, and manifest for safe cleanup
- Standards: hooks.md — Claude Code hook state machine, blocking vs non-blocking handlers, ownership model
- Standards: logging.md — structured logging with dictConfig, rotating files, PII-free correlation
- Docs: DES-009/010/011 design decisions (hook ownership, vox/lux asymmetry, Z specs)

### Changed

- `/punt release` propagation merges now use GitHub API instead of `gh pr merge` (worktree-safe)
- `/punt release` checks all 3 propagation target repos (.github was missing)
- `/punt autopilot` Copilot review gate tightened: no merge without review or explicit override
- `install.sh` VERSION pinning codified in standards and DESIGN.md
- Markdownlint path exclusions expanded (`.tmp/`, `research/`, `session.md`, `standards/makefile.md`)
- Adopted Makefile standard (make check, make help)

### Fixed

- `/punt release` branch deletion URL-encodes slashes in branch names
- install-all.sh SHAs updated for biff v0.17.0, quarry v1.0.2, vox v1.2.4, lux v0.5.2
- Marketplace install SHA fixed for stale punt-labs/tts reference
- `punt release` subprocess timeouts increased to 2 hours
- CI propagation creates PR with auto-merge instead of direct push

## [0.3.0] - 2026-03-06

### Added

- CLI: `punt release` deterministic release workflow (phases 1-8: preflight, version bump, build, tag/push, CI wait, GitHub release, PyPI verify, cross-repo propagation)
- CLI: `--dry-run` flag shows exact commands without side effects
- CLI: auto-detects version from CHANGELOG.md when not specified
- GitHub Action: three `propagate.yml` workflows for cross-repo updates (install-all.sh SHAs in punt-kit, marketplace.json in claude-plugins, org profile README in .github)
- `punt init` scaffolds standard deny rules (21 rules from `permissions.md` §4) alongside allow rules
- `punt audit` validates deny rules are present and complete

### Changed

- `/punt release` simplified to thin wrapper: calls `punt release` CLI, falls back to guided mode on failure

### Fixed

- `/autopilot` step 8: separate CI wait from Copilot review wait (they are independent), add explicit polling loop with 15-minute minimum, prevent rationalization of missing reviews
- `punt audit` no longer fails on GitHub checks when run in subdirectories of another git repo (e.g. test tmp dirs)

## [0.2.2] - 2026-02-28

### Fixed

- Installer auto-installs Python 3.13 via `uv python install` when system Python is too old (Ubuntu 24.04 ships 3.12)
- Installer checks for git before marketplace operations, failing fast with a clear message instead of opaque errors
- Installer uses uninstall-before-install for idempotency (`claude plugin update` is unreliable)
- Installer adds read-after-write verification after plugin install

## [0.2.1] - 2026-02-27

### Added

- Plugin: `/punt release` guided 11-phase release workflow
- Standards: distribution.md installer and release standards codified
- Patterns: copy-not-symlink, dual-command-path, two-phase-install (rewritten)
- CLI: `punt audit` installer and release checks
- Docs: DES-003 marketplace HEAD-vs-tag root cause analysis

### Fixed

- install.sh: add marketplace refresh after plugin install
- install.sh: pin all curl URLs to commit SHAs

## [0.2.0] - 2026-02-26

### Added

- CLI: `punt pii` command for PII scanning
- install.sh and install-all.sh one-command installers
- Standards: readme.md standard
- Docs: punt-kit PR/FAQ (hypothesis stage) and product vision
- LICENSE (MIT)

### Changed

- Standards: distribution.md, plugins.md, shell.md, naming.md
- Rewrote distribution.md around projection model and one-command principle
- Updated plugins.md with marketplace patterns and MCP server key naming
- Rewrite README as standards + plugin-kit reference

### Fixed

- TestPyPI publish: add skip-existing and unsafe-best-match index strategy

## [0.1.0] - 2026-02-24

### Added

- CLI: `punt init` scaffolding, `punt audit` compliance checks
- Plugin: `/punt reconcile` command, `/punt audit`, `/punt init`
- Plugin: dev/prod namespace isolation via `--plugin-dir`
- Standards: python.md, github.md, workflow.md, cli.md
- Patterns: sibling-ppid, dynamic-description-notify
- CI: lint, test, docs workflows
- Markdownlint configuration and docs CI
