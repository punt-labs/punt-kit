You are the worker on ethos mission m-2026-10-23-016 (bead pkit-ewox). Read the full contract first: `ethos mission show m-2026-10-23-016`. It has groups S, T, U, V and W, with numbered items and leader RULINGs. All of it comes from the third final review round. Fix everything.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths and one shell command per Bash call. Never chain a commit after `make check` with `;` or `&&`. Read the FULL `make check` output, not the tail.

Work in this order:
1. S1: punt release prints nothing for a file error. The repro is in .tmp/rv3.
2. S2: audit and seed lose all findings on one unreadable file.
3. T1: an install.sh version no-op.
4. S3: a worker-thread bug loses its type.
5. The rest.

Write the test first for every behavior fix, and note in each case that it failed first. Escalate to me instead of deciding if a fix would change a CLI flag, or an exit code beyond U3 (ruled). Do not edit CHANGELOG.md; list user-visible changes in the result.

Quality bar:
- `make check` is green before every commit.
- The assertion count does not drop.
- No new suppressions.
- No file that was over 300 lines at 035fb7e grows past that size.
- The OO score does not regress, and never by cutting docs.

Commit one logical step at a time with `git add <file>` only. Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r9.md and submit it via `ethos mission result`. Include:
- each item ID with its commit and evidence
- OO numbers
- user-visible changes
- the final `make check` output