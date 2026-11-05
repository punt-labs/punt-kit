You are the worker on ethos mission m-2026-10-22-054 (bead pkit-ewox). It follows your closed mission m-2026-10-22-051 on the same branch. Read the full contract first: `ethos mission show m-2026-10-22-054`. It lists eleven findings by ID: T1-T6 for tests and S1-S5 for source. Fix all of them.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers (branch refactor/release-legacy-helpers). Do all work there, using absolute paths. One shell command per Bash call.

Two findings change behavior:
- S1: ReadmeShaPin.land's dry-run branch should call bump(dry_run=True), so `--dry-run` shows the real README rewrite.
- S2: ReadmeShaPin.bump should warn when the repo slug can't be resolved, and when zero substitutions are made against install URLs that are present.
If S1 would change dry-run output beyond swapping the placeholder for the real rewrite, stop and escalate to me. The same applies if any fix would touch a CLI flag or an exit code.

For S3 (aliases) and S5 (the docs drift), verify against the code before acting. Do not trust the reviewer's list blindly.

Quality bar:
- `make check` is green on every commit. Read the full output.
- No suppressions remain on PrMerger._select_existing or release._skips, and none are added anywhere.
- The assertion count goes down only for tests dropped under T2, each one justified by the test that covers it.
- The OO score does not regress on any touched source file. Measure with ~/Coding/punt-labs/vox/tools/oo_score.py and record before and after.

Commit one logical step at a time with `git add <file>` only. Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on the branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r2.md and submit it via `ethos mission result`. For each finding ID, give what was done and the commit. Also include the OO numbers, the commit list, and the final `make check` output.