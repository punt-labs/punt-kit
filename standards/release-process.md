# Release Process

## Status: SETTLED

Releases are invoked via `/punt:auto release [version=X.Y.Z]`, which runs the
`release` playbook (`playbooks/release.yaml`). The playbook delegates to the
`punt release` CLI (`src/punt_kit/release.py`) for the deterministic phases 1–11,
then runs an LLM verification step that spot-checks artifacts across all repos.
The playbook executor provides `on_failure: diagnose` recovery — if `punt release`
fails mid-way, the executor reads the error output, diagnoses root cause,
attempts a fix, and re-runs the step.

All main-branch changes go through PRs — there are zero bypass actors on any
branch protection ruleset (DES-015). See DES-013 and DES-016 in DESIGN.md for
the full design history.

## Phase Structure

| Phase | Name | Scope |
|-------|------|-------|
| 1 | Preflight | Originating repo |
| 2 | Version Bump | Originating repo (`release/vX.Y.Z` branch) |
| 3 | Build | Originating repo (`uv build` + `twine check`) |
| 4 | Release PR | Originating repo (plugin swap → push → PR → CI → squash-merge) |
| 5 | Tag | Originating repo (tag main HEAD, push tag) |
| 6 | CI Wait | Remote (tag-triggered `release.yml`) |
| 7 | GitHub Release | Remote (create release with changelog notes) |
| 8 | PyPI Verify | Remote (install from PyPI, run doctor, restore editable) |
| 9 | Post-Release | Originating repo (dev restore + README SHA bump via PR) |
| 10 | Propagate | Sibling repos (local edits → PRs) |
| 11 | Verify | All repos (read-only checks) |

## Phase 10: Propagate

Four sub-steps, executed in fixed order. Each is independently skippable
based on project type and sibling availability. Each sub-step creates a
branch, commits the change, pushes, creates a PR, waits for CI, and
squash-merges (via `_sibling_pr_merge`).

### 10a. install-all.sh (punt-kit)

Update the project's curl line SHA in `punt-kit/install-all.sh`:

```bash
curl -fsSL "$GH/<project>/<new-sha>/install.sh" | sh
```

The SHA is the short hash of the commit that last modified `install.sh`
(not the tag SHA — for hybrid projects the tag sits on the plugin-swap
commit, which comes after the version-bump commit).

**Self-referential case**: when releasing punt-kit, this modifies punt-kit's
own `install-all.sh`. The sibling resolution returns the originating repo
itself. The logic is identical.

**Applies to**: all projects with an `install.sh`.

### 10b. Marketplace (claude-plugins)

Update `.claude-plugin/marketplace.json`:

- `version` → release version
- `source.ref` → `vX.Y.Z`

**Applies to**: hybrid and plugin projects.

### 10c. Org Profile (.github)

Update the `install-all.sh` curl URL in `profile/README.md` to punt-kit's
current main HEAD SHA (which includes the 10a commit).

**Depends on**: 10a must complete first.

**Applies to**: any release where 10a modified install-all.sh (not only
punt-kit releases — any project with an install.sh advances punt-kit's
HEAD when 10a merges).

### 10d. Website (public-website)

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
- **CI failure on PR**: the release halts with a message identifying the
  branch and PR number. Fix on the branch and resume with `--resume-from`.
- **Sibling missing**: skip with a warning for optional targets (website).
  Fail for required targets (install-all.sh, marketplace).

### Applicability Matrix

| Sub-step | CLI-only | Hybrid | Plugin-only | punt-kit |
|----------|----------|--------|-------------|----------|
| 10a. install-all.sh | Yes | Yes | No | Yes (self) |
| 10b. Marketplace | No | Yes | Yes | Yes |
| 10c. Profile | If 10a ran | If 10a ran | No | If 10a ran |
| 10d. Website | If entry | If entry | If entry | If entry |

## Phase 11: Verify

Checks that the automated, file-level requirements from
`release-requirements.md` listed below are satisfied. Prints a pass/fail
checklist and exits non-zero if any check fails.

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

```bash
punt release 0.8.0 --resume-from propagate   # Skip 1-9, run 10-11
punt release 0.8.0 --resume-from verify      # Skip 1-10, run 11 only
punt release 0.8.0 --resume-from post-release # Skip 1-8, run 9-11
```

Valid phase names: `preflight`, `bump`, `build`, `release-pr`, `tag`, `ci`,
`github-release`, `pypi`, `post-release`, `propagate`, `verify`.

When resuming without an explicit version, the version is read from
`pyproject.toml` (not the changelog). Always pass the version explicitly
when resuming from `bump` if Phase 2 hasn't completed.
