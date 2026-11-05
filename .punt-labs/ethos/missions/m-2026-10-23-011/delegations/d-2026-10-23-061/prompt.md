You are the worker on ethos mission m-2026-10-23-011 (bead pkit-ewox). Read the full contract first: `ethos mission show m-2026-10-23-011`. It has groups A-H with numbered items, and leader RULINGs are marked. Everything in it comes from four review agents on the full branch diff. Fix all of it.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths, one shell command per Bash call.

Suggested order, highest risk first:
1. A3/A4/A5 (double stamp, empty notes, unclosed fence). These can publish a bad GitHub release.
2. C1-C4 (stop silent skips and the guessed slug).
3. D1/H1/H2 (one writer/reader rule per pin kind; owner-aware repo matching).
4. B (timeouts).
5. A1/A2/A6-A8.
6. C5-C7, E, F, G, H3-H6.

Write the test first for every behavior fix and note that it failed first. Escalate to me instead of deciding if a fix changes a CLI flag or an exit code, or if A4/A5/C2/C3 would block a release path in a way the contract doesn't describe. Do not edit CHANGELOG.md; list every user-visible change in the result.

Quality bar:
- `make check` green before every commit, and read the full output.
- The assertion count does not drop.
- No new suppressions; production suppressions are removed per F1.
- The OO score does not regress, and never by cutting docs.

Commits: one logical step each, `git add <file>` only, Conventional Commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r6.md and submit it via `ethos mission result`. It must include each item ID with its commit and evidence, OO numbers, user-visible changes, and the final `make check` output.