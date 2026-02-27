---
description: Guided release workflow for a Punt Labs project
argument-hint: "[version]"
allowed-tools: Bash(git:*), Bash(gh:*), Bash(uv:*), Bash(uvx:*), Bash(punt:*), Bash(rm:*), Bash(bash:*), Bash(claude:*), Read, Edit, Write, Glob, Grep, AskUserQuestion
---

# Release a Punt Labs Project

Walk through the complete release workflow for a Punt Labs project, phase by phase.
Each phase must pass before proceeding. If any phase fails, stop and report.

## Input

Version: $ARGUMENTS (if empty, ask user in Phase 2)

## Phase 1: Pre-flight

### 1a. Git state

Verify all three conditions. Fail if any are false:

```bash
git branch --show-current    # Must be "main"
git status --porcelain -uno  # Must be empty (clean working tree)
git fetch origin && git diff HEAD origin/main --stat  # Must be empty (up to date)
```

### 1b. Detect project type

Read `pyproject.toml` to get:

- `[project].name` — the package name (e.g., `punt-tts`)
- `[project].version` — the current version
- `[project].scripts` — CLI entry points (e.g., `tts`)

Check for `.claude-plugin/plugin.json`. Classify:

- **hybrid**: has both `pyproject.toml` and `.claude-plugin/plugin.json`
- **plugin-only**: has `.claude-plugin/plugin.json` but no `pyproject.toml`
- **CLI-only**: has `pyproject.toml` but no `.claude-plugin/plugin.json`

Check for `scripts/release-plugin.sh` — needed for plugin swap in Phase 4.

Print the detected configuration to the user.

### 1c. Changelog check

Read `CHANGELOG.md`. Verify it has an `[Unreleased]` section with at least one entry.
If `[Unreleased]` is empty or missing, refuse to proceed — there is nothing to release.

### 1d. Quality gates

Run the project's quality gates. For Python projects:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ tests/
uv run pyright src/ tests/
uv run pytest tests/ -v
```

All must pass with zero errors. If any fail, stop.

## Phase 2: Version bump

### 2a. Determine version

If `$ARGUMENTS` contains a version string (e.g., `1.2.3`), use it.

Otherwise, analyze the `[Unreleased]` section of CHANGELOG.md:

- If it contains `### Added` entries → suggest minor bump
- If it contains only `### Fixed` entries → suggest patch bump
- If it contains `### Changed` with breaking changes → suggest major bump

Present the suggestion to the user via AskUserQuestion and let them confirm or override.

### 2b. Bump version in all locations

For the target version X.Y.Z, update:

1. `pyproject.toml` → `version = "X.Y.Z"` under `[project]`
2. `src/<package>/__init__.py` → `__version__ = "X.Y.Z"`
   - Derive the package directory from `pyproject.toml` `[project].name` (replace `-` with `_`)
3. `.claude-plugin/plugin.json` → `"version": "X.Y.Z"` (if hybrid or plugin-only)

### 2c. Update CHANGELOG.md

Replace `## [Unreleased]` with `## [X.Y.Z] - YYYY-MM-DD` using today's date.
Add a new empty `## [Unreleased]` section above it.

### 2d. Commit

```bash
git add -A
git commit -m "chore: release vX.Y.Z"
```

## Phase 3: Build validation

For Python projects (has `pyproject.toml`):

```bash
rm -rf dist/ && uv build && uvx twine check dist/*
```

Verify twine reports PASSED for all artifacts. If it fails, stop.

For plugin-only projects, skip this phase.

## Phase 4: Tag and push

### 4a. Plugin swap (hybrid projects only)

If the project has `scripts/release-plugin.sh`:

```bash
bash scripts/release-plugin.sh
```

This creates a commit that swaps the plugin name from dev to prod and removes dev commands.

### 4b. Tag

```bash
git tag vX.Y.Z
```

### 4c. Push

**Ask the user to confirm before pushing.**

```bash
git push origin main vX.Y.Z
```

### 4d. Restore dev state (hybrid projects only)

If the project has `scripts/restore-dev-plugin.sh`:

```bash
bash scripts/restore-dev-plugin.sh
git push origin main
```

## Phase 5: Wait for CI

```bash
gh run list --branch main --limit 3
```

Find the run triggered by the tag push. Wait for it:

```bash
gh run watch <run-id>
```

If CI fails, stop and report the failure. The user must fix CI before continuing.

## Phase 6: GitHub release

Extract the version section from CHANGELOG.md (everything between `## [X.Y.Z]` and the
next `## [` heading). Create the release:

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "<changelog-section>"
```

## Phase 7: Verify PyPI install

For Python projects only. Skip for plugin-only projects.

Derive the PyPI package name from `pyproject.toml` `[project].name`:

```bash
uv tool install --force --refresh <package>==X.Y.Z
```

If the project has a `doctor` subcommand (check `[project.scripts]`), run it:

```bash
<cli-name> doctor
```

Restore editable install for local development:

```bash
uv tool install --force --editable .
```

## Phase 8: Marketplace sync

**Skip for CLI-only projects (no `.claude-plugin/`).**

Look for `../claude-plugins/.claude-plugin/marketplace.json` relative to the project root.

### If found

1. Read the file and find the entry matching this project's plugin name
1. Update `"version"` to `"X.Y.Z"`
1. Update `"source"."ref"` to `"vX.Y.Z"`
1. Commit and push in the claude-plugins repo:

```bash
cd ../claude-plugins
git add .claude-plugin/marketplace.json
git commit -m "chore: bump <plugin-name> to vX.Y.Z"
git push origin main
```

1. Run marketplace update:

```bash
claude plugin marketplace update punt-labs
```

1. Return to the project directory.

### If not found

Print manual instructions:
> Update marketplace.json in claude-plugins: set version to X.Y.Z, source.ref to vX.Y.Z,
> then run `claude plugin marketplace update punt-labs`.

## Phase 9: Public website sync

Look for `../public-website/src/data/projects.json` relative to the project root.

### If found

1. Read the file and find the entry matching this project (by `id` or `pypiUrl`)
1. Update `"version"` to `"X.Y.Z"`
1. If the project has an `install.sh` and it changed in this release
   (`git log v<prev>..vX.Y.Z -- install.sh` has output), update the `"installCommand"`
   with the new commit SHA: `curl -fsSL https://raw.githubusercontent.com/punt-labs/<repo>/<new-SHA>/install.sh | sh`
1. Commit and push in the public-website repo:

```bash
cd ../public-website
git add src/data/projects.json
git commit -m "chore: bump <project-name> to vX.Y.Z"
git push origin main
```

1. Return to the project directory.

### If not found

Print manual instructions:
> Update projects.json in public-website: set version to X.Y.Z. If install.sh changed,
> update the SHA in installCommand. Push to trigger Vercel deploy.

## Phase 10: Install-all SHA update

Check if this project has an `install.sh` and if it changed in this release:

```bash
git log v<prev-version>..vX.Y.Z -- install.sh
```

If install.sh did NOT change, skip this phase.

If install.sh changed:

1. Get the new SHA: `git rev-parse vX.Y.Z`
2. Derive the short project name from the repo (e.g., `tts`, `biff`, `quarry`)

### Update install-all.sh in punt-kit

Look for `../punt-kit/install-all.sh` (or `./install-all.sh` if releasing punt-kit itself).

If found, update the curl URL for this project from the old SHA to the new SHA.
The pattern is: `curl -fsSL "$GH/<project>/<SHA>/install.sh" | sh`

### Update org profile README

Look for `../.github/profile/README.md`.

If the README contains a curl URL referencing `punt-kit/.../install-all.sh`, and we are
releasing punt-kit itself, update that SHA too.

### Commit and push

For each repo that was modified, commit and push:

```bash
cd <repo>
git add <file>
git commit -m "chore: update <project> install SHA to vX.Y.Z"
git push origin main
```

Return to the project directory.

If the sibling directories are not found, print manual instructions listing which SHAs
need updating and where.

## Phase 11: Summary

Print a structured summary of everything that was done:

```text
## Release vX.Y.Z Complete

- Package: <package-name>
- Version: X.Y.Z
- Tag: vX.Y.Z
- PyPI: ✓ published (or N/A)
- GitHub Release: ✓ created
- Marketplace: ✓ updated (or N/A or manual)
- Website: ✓ updated (or N/A or manual)
- Install-all: ✓ updated (or skipped — install.sh unchanged)

Restart Claude Code to pick up marketplace changes.
```

## Important Rules

1. **Stop on failure.** Every phase is a gate. If quality gates fail, CI fails, or a build
   fails — stop and report. Do not skip phases.

2. **Confirm before pushing.** Before `git push` in Phase 4, ask the user to confirm.
   Pushing is hard to reverse.

3. **Cross-repo changes are best-effort.** Phases 8-10 look for sibling directories.
   If they don't exist, print manual instructions instead of failing.

4. **One project at a time.** Release the project in the current working directory.

5. **Follow the project's CLAUDE.md.** If the project documents additional release steps
   or overrides (e.g., different quality gate commands), follow those instead.
