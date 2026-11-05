You are the worker on ethos mission m-2026-10-23-018 (bead pkit-ewox). Read the full contract first: `ethos mission show m-2026-10-23-018` (items Y1-Y8 plus one RULING). It comes from the fourth final-review round. Fix all of it. The reviewer probes are in the worktree's .tmp/sfh4/.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths and one shell command per Bash call. Never chain a commit after a gate. Read the FULL `make check` output.

Suggested order:
1. Y1: `bd init` has no timeout.
2. Y5: CalledProcessError loses its stderr.
3. Y6: errors are lost on the interrupt path.
4. Y7: rewrite every plain VERSION assignment.
5. The rest.

Write the test first for every behavior fix, and note that it failed first.

Bar:
- `make check` green before every commit.
- The assertion count does not drop.
- Zero new suppressions.
- No source module that was over 300 lines at 035fb7e grows past that size.
- OO does not regress, and never by cutting docs.
- Do not edit CHANGELOG.md; list user-visible changes in the result.

Commit one logical step at a time, staging with `git add <file>` only. Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r11.md and submit it via `ethos mission result`. Include:
- each item, with its commit and evidence
- the subprocess.run timeout grep
- user-visible changes
- the final `make check` output