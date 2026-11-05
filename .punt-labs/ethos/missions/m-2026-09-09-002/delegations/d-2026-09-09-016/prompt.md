You have an ethos mission to execute: m-2026-09-09-004 (bead pkit-8r6).

First run `ethos mission show m-2026-09-09-004` and `ethos mission claim m-2026-09-09-004` to load the contract and enable commit trailers. Then implement it to the letter.

Summary: `punt doctor` prints "optional" twice for a not-found optional binary: `✗ pyright: not found (optional) (optional)`. In `src/punt_kit/doctor.py`, `_check_binary` (lines ~29–35) bakes the label into the message as `f"not found ({label})"`, and the print loop in `run_doctor` (line ~55) ALSO appends `" (optional)"` for non-required checks. The doubling happens only on not-found + optional. Fix it so a not-found optional binary prints exactly `✗ pyright: not found (optional)` (one occurrence), WITHOUT losing the required/optional distinction on other lines — give the "(optional)" annotation a single owner (either the message builder or the print-loop suffix, not both). Think about whether a not-found *required* binary should still be distinguishable; keep the behavior sensible and consistent.

There is no `tests/test_doctor.py` — create it (authorized in your write-set) with pytest regression coverage for all four cases: not-found-optional (assert exactly one `(optional)`), not-found-required, found-optional, found-required. Monkeypatch `shutil.which`; use `capsys` to assert the rendered line.

`make check` must exit 0 before every commit. No suppressions. OO score must not regress on `doctor.py`. Do NOT touch CHANGELOG.md (the leader owns it). 

You are working in an isolated git worktree. Do NOT push and do NOT open a PR — the leader (Claude) will review your branch and create the PR. When done, report: the branch name, the commit SHAs, the exact make-check result, and the rendered doctor output for a not-found optional binary. If the write-set blocks creating tests/test_doctor.py, stop and report.