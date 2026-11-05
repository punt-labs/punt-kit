You are the worker on ethos mission m-2026-10-23-022 (bead pkit-ewox). Read the full contract first with `ethos mission show m-2026-10-23-022`: items Z1-Z7, with leader RULINGs on Z4 and Z5. The reviewer probes are in the worktree's .tmp/sfh5/.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths and one shell command per Bash call. Never chain a commit after a gate. Read the FULL `make check` output.

Order of work:
1. Z4: a stale unquoted VERSION currently passes verify.
2. Z1/Z2: credential redaction for `bd` stderr and `print_timeout`.
3. Z5, Z6, Z7, then Z3.

Every behavior fix is test-first; note that each test failed before the fix. Do not edit CHANGELOG.md; list user-visible changes in the result.

Bar:
- `make check` green before every commit.
- The assertion count does not drop.
- Zero new suppressions.
- No source module that was over 300 lines at 035fb7e grows past that size.

Commit one logical step at a time, staging with `git add <file>` only. Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r13.md and submit it via `ethos mission result`. Include each item with its commit and evidence, the user-visible changes, and the final `make check` output.