Small fix in ~/Coding/punt-labs/prfaq (repo punt-labs/prfaq).

First check the repo state: it must be on main with a clean tree (`git -C ~/Coding/punt-labs/prfaq status`); if dirty or not on main, stop and report instead of proceeding.

Problem: scripts/release-plugin.sh line ~67 commits with `chore: prepare plugin for release [skip ci]`. That commit becomes the HEAD of the release PR itself, so no CI runs on the release PR — the same class of deadlock/blind-merge defect observed on ethos#496 during the ethos v4.16.1 release (release tooling waits forever for checks that [skip ci] guarantees will never run, and any required-checks ruleset can never be satisfied).

Task:
1. `git -C ~/Coding/punt-labs/prfaq checkout -b fix/release-pr-ci main`
2. Edit scripts/release-plugin.sh: remove ` [skip ci]` from that commit message (keep everything else unchanged).
3. Add a CHANGELOG.md entry under `## [Unreleased]` / `### Fixed`: release-prep commits no longer carry [skip ci]; it suppressed all CI on the release PR head, so releases merged unverified and any required-checks rule deadlocks.
4. Run `shellcheck scripts/release-plugin.sh` and `npx --yes markdownlint-cli2 CHANGELOG.md` — both must pass (use repo lint targets if more appropriate; skip unrelated full test suites).
5. Commit (`fix(release): drop [skip ci] from the release-prep commit`), push, open a PR against main via `gh pr create` describing the defect class and "script+docs only — verified with shellcheck + markdownlint". Do NOT merge.
6. Report the PR number and the diff.