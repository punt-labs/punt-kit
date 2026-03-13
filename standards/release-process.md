# Release Process Design

## Status: PROPOSED

Replaces the GitHub Actions propagation workflows with local, synchronous
operations performed by the `punt release` CLI.

## Problem

The current Phase 8 (cross-repo propagation) dispatches GitHub Actions
workflows in three repos (punt-kit, claude-plugins, .github), each creating
and auto-merging PRs via `PROPAGATE_TOKEN`. This architecture has failed
on every release attempt:

- **Secret misconfiguration**: `PROPAGATE_TOKEN` must exist in every target
  repo. Missing or expired tokens cause silent failures.
- **Merge conflicts**: concurrent propagation PRs conflict with each other.
- **Stale PRs**: failed auto-merges leave open PRs requiring manual cleanup.
- **Race conditions**: chaining workflow (`propagate-profile.yml`) triggers
  on push, but the triggering commit may not have landed yet.
- **Silent failures**: `_trigger_and_wait` returns False but the release
  continues, reporting success.

## Key Insight

All propagation targets are sibling directories in the workspace. The user
has push access to all of them. Every propagation is a deterministic text
substitution. There is no need for remote workflows, secrets, PRs, or
async coordination.

## New Phase Structure

| Phase | Name | Scope |
|-------|------|-------|
| 1 | Preflight | Originating repo |
| 2 | Version Bump | Originating repo |
| 3 | Build | Originating repo |
| 4 | Tag and Push | Originating repo |
| 5 | CI Wait | Remote (tag-triggered) |
| 6 | GitHub Release | Remote |
| 7 | PyPI Verify | Remote |
| 8 | Propagate | Sibling repos (local) |
| 9 | Verify | All repos (read-only) |

Phases 1-7 are unchanged from today. Phases 8-9 replace the old Phase 8
(workflow dispatch) and the entire `release.yaml` playbook.

## Phase 8: Propagate

Four sub-steps, executed in fixed order. Each is independently skippable
based on project type and sibling availability.

### 8a. install-all.sh (punt-kit)

Update the project's curl line SHA in `punt-kit/install-all.sh`:

```
curl -fsSL "$GH/<project>/<new-sha>/install.sh" | sh
```

The SHA is the short hash of the `vX.Y.Z` tag.

**Self-referential case**: when releasing punt-kit, this modifies punt-kit's
own `install-all.sh`. The sibling resolution returns the originating repo
itself. The logic is identical.

**Applies to**: all projects with an `install.sh`.

### 8b. Marketplace (claude-plugins)

Update `.claude-plugin/marketplace.json`:

- `version` → release version
- `source.ref` → `vX.Y.Z`

**Applies to**: hybrid and plugin projects.

### 8c. Org Profile (.github)

Update the `install-all.sh` curl URL in `profile/README.md` to punt-kit's
current main HEAD SHA (which includes the 8a commit).

**Depends on**: 8a must complete first.

**Applies to**: punt-kit releases only.

### 8d. Website (public-website)

Update `src/data/projects.json`:

- `version` → release version
- `installCommand` SHA if present

**Applies to**: all projects with a website entry. Skipped gracefully if
`../public-website` does not exist.

### Sibling Validation

Before modifying any sibling:

1. Resolve path: `../name` relative to originating repo's parent
2. Confirm `.git` exists
3. Confirm on `main` branch
4. Confirm clean working tree
5. `git pull --ff-only origin main`

If any check fails, the release halts with an explicit error.

### Idempotency

Each sub-step checks for a diff before committing. If the substitution
produces no change (already current), the step is skipped. Re-running
`punt release X.Y.Z` after an interruption is safe — completed steps
produce no diff and are skipped.

### Error Handling

- **Fail-fast**: any error halts the release immediately.
- **Push rejected (non-ff)**: retry once — pull, re-apply substitution,
  push. If still rejected, fail with instructions.
- **Sibling missing**: skip with a warning for optional targets (website).
  Fail for required targets (install-all.sh, marketplace).

### Applicability Matrix

| Sub-step | CLI-only | Hybrid | Plugin-only | punt-kit |
|----------|----------|--------|-------------|----------|
| 8a. install-all.sh | Yes | Yes | No | Yes (self) |
| 8b. Marketplace | No | Yes | Yes | Yes |
| 8c. Profile | No | No | No | Yes |
| 8d. Website | If entry | If entry | If entry | If entry |

## Phase 9: Verify

Read-only checks confirming that the automated, file-level requirements from
`release-requirements.md` listed below are satisfied. Does not cover all
requirements (for example, GitHub Release existence). Prints a pass/fail table.

| Check | Method |
|-------|--------|
| Git tag exists | `git tag --list vX.Y.Z` |
| Version consistency | Read pyproject.toml, \_\_init\_\_.py, plugin.json, install.sh |
| Changelog stamped | Regex match `## [X.Y.Z] - YYYY-MM-DD` in CHANGELOG.md |
| install-all.sh SHA | Read sibling, extract SHA, verify `git show <SHA>:install.sh` has correct VERSION |
| Marketplace version | Read sibling marketplace.json, check version and ref |
| Profile SHA | Read sibling profile/README.md, verify punt-kit HEAD |
| Website version | Read sibling projects.json, check version |
| PyPI available | `uv pip index versions <package>` (word-boundary match) |

## Resume Flag

`--resume-from <phase>` skips earlier phases, enabling recovery from
interrupted releases:

```
punt release 0.8.0 --resume-from propagate   # Skip 1-7, run 8-9
punt release 0.8.0 --resume-from verify      # Skip 1-8, run 9 only
```

## What Gets Deleted

| File | Repo | Why |
|------|------|-----|
| `.github/workflows/propagate.yml` | punt-kit | Replaced by Phase 8a |
| `.github/workflows/propagate-profile.yml` | punt-kit | Replaced by Phase 8c |
| `.github/workflows/propagate.yml` | claude-plugins | Replaced by Phase 8b |
| `.github/workflows/propagate.yml` | .github | Replaced by Phase 8c |
| `playbooks/release.yaml` | punt-kit | Replaced by thin wrapper that calls CLI |
| `PROPAGATE_TOKEN` secret | all repos | No longer needed |

The `release.yml` CI workflow (build/test/publish on tag push) is **kept**.

## Implementation Files

| File | Action |
|------|--------|
| `src/punt_kit/release.py` | Replace Phase 8, add Phase 9, add sibling helpers |
| `src/punt_kit/__main__.py` | Add `--resume-from` CLI flag |
| `tests/test_release.py` | Add propagation tests |
| `standards/release-requirements.md` | Update to document local propagation |
| `CHANGELOG.md` | Add entry |
| Workflow files (4) | Delete |
| `playbooks/release.yaml` | Replace with thin CLI wrapper |
