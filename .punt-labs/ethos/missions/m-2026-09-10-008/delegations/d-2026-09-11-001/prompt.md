Small revert PR in <repo>. Operator ruling (2026-09-10): in .punt-labs/, the `local` naming convention (`*.local.md`, `local/`) is the ONLY not-in-git flag — everything else is designed to be tracked. PR #350 untracked `.punt-labs/vox/vox.md` and added a gitignore entry for it; that was wrong per this ruling and must be reverted.

IMPORTANT constraint: the punt-kit checkout is occupied by another worker on branch design/release-failure-harness. Do NOT git checkout in the main tree. Create an isolated worktree: `git -C <repo> worktree add ~/Coding/punt-labs/punt-kit-voxmd-revert -b fix/retrack-vox-md origin/main` and work only there.

Steps in the worktree:
1. Remove the `.punt-labs/vox/vox.md` entry from .gitignore (find the exact line #350 added; leave every other line, including any vox.local.md/ephemeral entries, untouched).
2. Restore tracking of .punt-labs/vox/vox.md. NOTE: do NOT read or open that file's contents (vox daemon owns it — racing it is forbidden); the copy in the main checkout at <repo>/.punt-labs/vox/vox.md exists on disk untracked. Copy it into the worktree with `cp` (a byte copy is fine; just don't parse or edit it), then `git add` both files.
3. CHANGELOG.md entry under [Unreleased] / Fixed: vox.md is tracked again — the `local` naming convention is the only not-in-git flag in .punt-labs/ (operator ruling); #350's untrack was the divergence, vox/lux had it right.
4. `npx --yes markdownlint-cli2 CHANGELOG.md` from the worktree root must pass. Run `make check` from the worktree if it runs cleanly there; if the worktree lacks a venv and make check can't run, say so in the PR body and rely on CI.
5. Commit (`fix: re-track .punt-labs/vox/vox.md — local naming is the only not-in-git flag`), push, open PR against main via gh CLI (not draft). Do NOT merge.
6. Report the PR number and the diff.