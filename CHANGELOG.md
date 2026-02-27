# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
