You have an ethos mission: m-2026-09-13-002 (bead pkit-17qo). Run `ethos mission show m-2026-09-13-002` and `ethos mission claim m-2026-09-13-002`, then implement it.

Bug: `test_display_path_falls_back_to_absolute_outside_the_repo` in `tests/test_record_gh_fixtures.py` fails only when `TMPDIR` points inside the repo — which this project's `.envrc` does (exports `TMPDIR` into `.tmp/` at the repo root). The test uses pytest's `tmp_path` as its "outside the repo" path, but with `TMPDIR` inside the repo, `tmp_path` resolves *under* the repo root, so the outside-the-repo premise collapses and the assertion fails. Pre-existing on main; CI stays green (no such TMPDIR there).

Fix: make the test's "outside the repo" path genuinely outside the repo regardless of `TMPDIR` — construct it independent of `tmp_path`/`TMPDIR` (e.g. create a temp dir under the real system temp root computed without `TMPDIR`, or otherwise assert-not-under-repo-root). Keep the test's intent intact (display-path falls back to an absolute path when the path is outside the repo). Clean up any temp dir you create.

Verify by running the test BOTH with `TMPDIR` set inside the repo (mimicking `.envrc`, e.g. `TMPDIR=$PWD/.tmp`) AND with it unset — must pass both ways. Paste the exact commands + results in your report.

`make check` must exit 0 before every commit; no suppressions. Do NOT touch CHANGELOG.md. You're in an isolated worktree — do NOT push, do NOT open a PR. Branch `fix/pkit-17qo-tmpdir-test` off main. Report branch, commit SHA, and the two-way verification output.