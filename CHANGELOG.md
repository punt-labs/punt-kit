# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
