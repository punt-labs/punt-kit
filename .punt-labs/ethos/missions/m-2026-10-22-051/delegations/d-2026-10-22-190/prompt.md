You are the worker on ethos mission m-2026-10-22-051 (bead pkit-ewox). Read the full contract first: `ethos mission show m-2026-10-22-051`. It is the authoritative spec; this message only summarizes it.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers (branch refactor/release-legacy-helpers, from main 035fb7e). Do all work and run all commands there, using absolute paths. One shell command per Bash call — no &&, ||, ;, or pipes.

Task: src/punt_kit/release.py has 14 private helpers, each marked `# pyright: ignore[reportUnusedFunction]`. They look like leftovers from the extraction of release into src/punt_kit/phases/. Classify each one before touching it:
(a) It has a live equivalent in phases/. Repoint the tests and callers to that equivalent, then delete the old copy.
(b) It is a real live dependency of audit.py or phases/shared/readme_sha.py. Move it to its proper home and delete the copy in release.py.
(c) Only tests reference it and production never calls it. Delete the helper and those tests, and list each deleted test with the reason.
Never delete the phases/ code to resolve duplication: phases/ is the target architecture (PY-RF-6). Do not change release behavior.

Stop and report to me without deciding yourself if either of these happens:
- A live equivalent behaves differently from the old copy in a way a test encodes. That may be a real regression.
- A move would create a circular import or an inner-layer-to-presentation import.

Quality bar:
- `make check` is green on every commit.
- Zero `reportUnusedFunction` left in release.py and no new suppressions anywhere.
- The assertion count goes down only for category (c) deletions.
- The OO score does not regress on any touched file. Record before and after numbers.

Commit one logical step at a time, staging only the files you changed (`git add <file>`). Use Conventional Commits messages ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge — the leader does that. If a command is denied, stop and report it.

When done, write your result to <repo>/.tmp/missions/results/release-legacy-helpers.md and submit it via `ethos mission result`. The result must include:
- the classification table for all 14 helpers: helper, category, live equivalent or new home, tests touched
- any deleted tests, each with its reason
- the OO scores before and after
- the commit list
- the final `make check` output