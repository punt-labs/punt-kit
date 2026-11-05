You are the worker on ethos mission m-2026-10-23-004 (bead pkit-ewox). It is a re-scoped successor to m-2026-10-23-001, which closed failed at its round cap. Read the full contract first: `ethos mission show m-2026-10-23-004`. It covers G1-G7. gvr's round-2 reflection and probe inputs are in <repo>/.claude/worktrees/release-legacy-helpers/.tmp/ (reflect-r2.yaml, probe*.py, test_p.py).

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths, and one shell command per Bash call.

Order of work:
1. G1 first. It is a real production timeout exposure: `gh pr merge --delete-branch` runs local git, which fires the bd hooks, on the 60s default.
2. G2-G4: replace the hand-rolled fence and comment scanner with markdown-it-py tokens. The rationale is in the contract. Keep ChangelogDocument's API and BOM/CRLF preservation. Delete the old scan code.
3. G5 and G6: fix slug normalization at the root, in GithubRepo.resolve.
4. G7: the audit hardening.

Write the test first for every behavior fix. Escalate to me instead of deciding if markdown-it-py cannot express a needed case, or if a fix would change a CLI flag, an exit code, or an operator-facing message. Do not edit CHANGELOG.md; list user-visible behavior changes in the result.

Quality bar:
- `make check` green before every commit. Read the full output.
- The assertion count does not drop.
- No new suppressions.
- The OO score does not regress, and never by cutting docs.

Commit one logical step at a time with `git add <file>` only. Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r4.md and submit it via `ethos mission result`. It must include:
- each item with its commit and evidence
- the grep evidence the contract asks for
- OO numbers
- the user-visible changes
- the final `make check`