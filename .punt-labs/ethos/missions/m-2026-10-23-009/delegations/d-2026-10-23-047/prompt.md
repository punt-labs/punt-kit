You are the worker on ethos mission m-2026-10-23-009 (bead pkit-ewox). It is a re-scoped successor to m-2026-10-23-004, which closed failed at its round cap. Read the full contract first: `ethos mission show m-2026-10-23-009`. It covers R1-R4.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths, and one shell command per Bash call.

The core of this mission is R1, a structural change. The AST hook-timeout audit has leaked in two straight rounds because it guesses runtime argv from source. Replace it with runtime enforcement:
- Add a typed classifier in src that works on the concrete argv. It must handle git global options, the gh subcommands that run local git (including clustered short flags such as -sd), and env/sh -c wrappers. When in doubt, classify as hook-firing.
- At the single ops choke point that every phase command passes through, apply a timeout floor of GIT_HOOK to anything the classifier marks hook-firing.
- Then delete the AST audit, which this supersedes.
- Find and report every process spawn that bypasses the choke point. If no single choke point exists, stop and escalate to me.

Then do R2 (delete GithubRepo.resolve), R3 (punt audit's malformed-remote message), and R4 (the design-doc path fix; docs is now in your write set).

Do not edit CHANGELOG.md; list user-visible changes in the result. Escalate instead of deciding if a fix would change a CLI flag, an exit code, or an operator-scripted message.

Quality bar:
- Behavior fixes are test-first.
- `make check` is green before every commit. Read the full output.
- The assertion count drops only by the deleted AST-audit tests; list them.
- No new suppressions.
- The OO score doesn't regress, and never by cutting docs.

Commits: one logical step per commit, `git add <file>` only, Conventional Commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r5.md and submit it via `ethos mission result`. Include:
- each item, with its commit and evidence
- the choke-point grep evidence
- the deleted tests
- OO numbers
- the user-visible changes
- the final `make check`