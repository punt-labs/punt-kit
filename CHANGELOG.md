# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
