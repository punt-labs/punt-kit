You are the worker on ethos mission m-2026-10-23-001 (bead pkit-ewox). Read the full contract first with `ethos mission show m-2026-10-23-001`. It is the spec, and it lists items A-H.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Do all work there with absolute paths. One shell command per Bash call.

Two items are structural rewrites, not patches. Two areas have now produced defects in three review rounds, so patching them again is not acceptable.
- A: one pinned-install-URL recognizer, shared by ReadmeShaPin.bump and Phase 11. bump verifies its own output with it.
- B: one changelog section parser that every changelog reader uses.

Work rules:
- Do A, B and C test-first. Write a test that fails on the current code, then fix it.
- For B, survey the sibling repos' CHANGELOG.md breaking-change markers before you pick one.
- Escalate to me, without deciding yourself, if the survey shows no consistent convention, or if any fix would change a CLI flag, an exit code, or a message an operator scripts against.
- Do not edit CHANGELOG.md. List every user-visible behavior change in your result instead.

Quality bar:
- `make check` green before every commit, and read the full output.
- The assertion count does not drop, and the suppression count in the two test files strictly drops. Every suppression that survives is justified.
- The OO score does not regress (~/Coding/punt-labs/vox/tools/oo_score.py). Never cut documentation to hit a number.

Commits: one logical step per commit, `git add <file>` only, Conventional Commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r3.md and submit it with `ethos mission result`. The result must cover:
- each item, with the commit and evidence
- the grep evidence for "exactly one recognizer" and "exactly one parser"
- the fleet survey
- the TDD-failing-first note for each test
- suppression counts before and after, with the survivors
- OO numbers
- user-visible behavior changes
- the final `make check`