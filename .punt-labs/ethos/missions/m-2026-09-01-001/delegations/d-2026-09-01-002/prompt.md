Small fix in ~/Coding/punt-labs/ethos (repo punt-labs/ethos, currently on clean main).

Problem: scripts/restore-dev-plugin.sh commits with the message `chore: restore dev plugin state [skip ci]`. That commit becomes the head of the post-release PR, so zero workflows run on it — while the repo's ruleset requires 2 status checks. Result: the release tool's wait-for-checks loop deadlocked on PR #496 during the v4.16.1 release (2026-08-31) until a later commit without [skip ci] was pushed.

Task:
1. `git -C ~/Coding/punt-labs/ethos checkout -b fix/post-release-ci main`
2. Edit scripts/restore-dev-plugin.sh: remove ` [skip ci]` from the commit message (keep the rest of the message and script unchanged).
3. Add a CHANGELOG.md entry under `## [Unreleased]` / `### Fixed` explaining: post-release restore commits no longer carry [skip ci]; it suppressed all workflows on the post-release PR head, which deadlocks against the ruleset's required status checks (observed on PR #496).
4. Run `shellcheck scripts/restore-dev-plugin.sh` and `npx --yes markdownlint-cli2 CHANGELOG.md` — both must pass. If the repo Makefile has a quicker docs/lint target covering these, that is fine too, but do not run the full Go test suite.
5. Commit (message: `fix(release): drop [skip ci] from the post-release restore commit`), push the branch, open a PR against main via `gh pr create` with a description that includes the PR #496 deadlock evidence and "docs/script-only — verified with shellcheck + markdownlint". Do NOT merge.
6. Report the PR number and the diff.