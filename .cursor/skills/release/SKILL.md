---
name: release
description: Guided release workflow for a Punt Labs project
disable-model-invocation: true
---

# Release a Punt Labs Project

Complete release workflow: deterministic CLI for local phases, then cross-repo
propagation and end-to-end verification. The release is NOT complete until
verification passes.

## Input

If the user provided a version as an argument, use it. Otherwise it will be auto-detected from CHANGELOG.md.

## Step 1: Run the CLI

Run in the shell:

```bash
punt release <version>
```

Replace `<version>` with the user-provided version, or omit for auto-detection.

This handles Phases 1-8: pre-flight, version bump (including install.sh VERSION pin),
build validation, tag and push, CI wait, GitHub release, PyPI verification, and
cross-repo propagation triggers.

If `punt release` fails, see **Failure Recovery** at the bottom.

## Step 2: Merge propagation PRs

The CLI triggers GitHub Actions that create PRs in:

- **punt-labs/punt-kit** — updates the project's SHA in `install-all.sh`
- **punt-labs/claude-plugins** — updates version in `marketplace.json` (hybrid/plugin projects)
- **punt-labs/.github** — updates profile README install-all.sh URL (punt-kit releases only)

For each target repo, check for open propagation PRs:

```bash
gh pr list --repo punt-labs/punt-kit --state open --search "propagate"
gh pr list --repo punt-labs/claude-plugins --state open --search "propagate"
```

For each open propagation PR:

1. Wait for CI: `gh pr checks <number> --repo <repo> --watch`
2. Check for merge conflicts: `gh pr view <number> --repo <repo> --json mergeable`
3. If conflicting, rebase locally or update the branch
4. Merge: `gh pr merge <number> --repo <repo> --squash --delete-branch --admin`

**All propagation PRs must be merged before proceeding.**

## Step 3: Website sync

Update the public website's project data with the new version.

Look for `../public-website/src/data/projects.json` relative to the project root.

If found:

1. Read the file and find the entry matching this project (by `id`, `name`, or `pypiUrl`)
2. Update `"version"` to the release version
3. If install.sh changed in this release, update `"installCommand"` with the new SHA:
   - Get the SHA: the tag commit short SHA (`git rev-parse --short vX.Y.Z`)
   - Update the curl URL accordingly
4. Commit and push (confirm with user first):

```bash
cd ../public-website
git add src/data/projects.json
git commit -m "chore: bump <project-name> to vX.Y.Z"
git push origin main
cd -
```

If the directory is not found, print manual instructions and continue.

## Step 4: Update .github profile README

After install-all.sh changes are merged into punt-kit, the .github profile README needs
the new punt-kit SHA so that the one-liner install command is current.

1. Get the latest punt-kit main SHA: `git -C ../punt-kit rev-parse --short HEAD`
2. Update the curl URL in `../.github/profile/README.md`
3. Commit and push (confirm with user first):

```bash
cd ../.github
git add profile/README.md
git commit -m "chore: update install-all.sh SHA to <short-sha>"
git push origin main
cd -
```

Skip this step if the `.github` directory is not present or no install-all.sh changes were made.

## Step 5: Verification

**The release is NOT done until every check below passes.** Run all of these. If any
fail, fix the issue and re-verify.

### 5a. PyPI version

```bash
uv pip index versions <package-name> 2>/dev/null | head -1
```

Confirm the release version appears.

### 5b. install-all.sh SHA and VERSION pin

Read `../punt-kit/install-all.sh` and find this project's curl line. Extract the SHA.
Then verify the install.sh at that SHA pins the correct version:

```bash
git -C ../<project> show <SHA>:install.sh | grep 'VERSION='
```

The VERSION must equal the release version. If install.sh has no VERSION pin (unpinned
install), warn: `"WARNING: install.sh has no VERSION pin — install is non-deterministic"`.

### 5c. Marketplace version

For hybrid/plugin projects, verify marketplace.json — version must match and ref must be `vX.Y.Z`.

### 5d. Website version

If `../public-website/src/data/projects.json` exists, verify the project's version matches.

### 5e. .github profile SHA

Verify the profile README points to the current punt-kit main SHA.

### 5f. Print verification summary

Print a table showing each check and its result. Every row must show a pass.
If any row fails, stop and fix before declaring the release complete.

## Failure Recovery

### CLI failure modes

- **Quality gate failure**: Fix the issue, then re-run `punt release <version>`.
- **CI failure**: The tag is already pushed. Fix CI, then resume from Step 2.
- **PyPI propagation timeout**: Re-run `punt release <version>`. If it fails because
  the version was already bumped or tagged, resume from Step 2.
- **CLI not installed or crashes**: Fall back to running each phase manually, using
  `punt release --dry-run` to see the phase structure.

### Cross-repo failure modes

- **Propagation PR has merge conflicts**: Rebase locally, force-push the branch, wait
  for CI, then merge.
- **Sibling repo not checked out**: Print manual instructions for the user.
- **Branch protection blocks merge**: Use `--admin` flag.

## Rules

1. **Stop on failure.** Every step is a gate.
2. **Confirm before pushing.** Ask the user before any `git push` in Steps 3-4.
3. **One project at a time.**
4. **Follow the project's CLAUDE.md** for overrides.
5. **Verification is mandatory.** The release is not complete until Step 5 passes.
