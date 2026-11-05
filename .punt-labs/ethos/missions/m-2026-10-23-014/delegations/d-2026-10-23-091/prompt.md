You are the worker on ethos mission m-2026-10-23-014 (bead pkit-ewox). Read the full contract first: `ethos mission show m-2026-10-23-014`. It has groups J, K, L, M, N and P with numbered items and leader RULINGs. Everything in it comes from the second final review round. Fix all of it.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths and one shell command per Bash call.

Work in this order, highest risk first:
1. J2: `punt init` can destroy a user's settings.json.
2. K1: any unexpected exception after publish must still print the recap and the resume hint.
3. K2: the real `gh` exits 1 on GraphQL errors.
4. P2: one currency predicate per pin kind; the writer resolves and compares.
5. The rest of J, K and L.
6. P: invariants made true and enforced by tests that fail on a violation.
7. M, then N.

Rules:
- Write the test first for every behavior fix, and note that it failed first.
- Escalate to me instead of deciding if a fix changes a CLI flag or exit code beyond K1's ruled non-zero exit, or if J3 changes what `punt init` writes for existing users.
- Do not edit CHANGELOG.md. List every user-visible change in the result.

Quality bar:
- `make check` green before every commit. Read the full output.
- The assertion count does not drop.
- No new suppressions.
- The OO score does not regress, and never by cutting docs.

Commits: one logical step each, `git add <file>` only, Conventional Commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r7.md and submit it via `ethos mission result`. It must include:
- each item ID with its commit and evidence
- the final read/write/json grep the contract asks for
- OO numbers
- user-visible changes
- the final `make check` output