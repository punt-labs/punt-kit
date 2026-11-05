You have an ethos mission to execute: m-2026-09-09-002 (bead pkit-mjcb).

First run `ethos mission show m-2026-09-09-002` and `ethos mission claim m-2026-09-09-002` to load the contract and enable commit trailers. Then implement it to the letter.

Summary: In `src/punt_kit/phases/phase01_preflight.py`, the Python quality-gate branch (around lines 151–170) runs a HARDCODED gate list (`uv run ruff check`, `ruff format --check`, `mypy`, `pyright`, `pytest`) and ignores the project's Makefile. The Go branch (around lines 171–195) already prefers `make check` when a Makefile exists and only falls back to hardcoded gates otherwise. Make the Python branch mirror the Go branch: prefer `make check` when `info.root / "Makefile"` exists (same `timeout=QUALITY_GATE`, `check=False`, `capture=False`, `ops.fail("Quality gate failed: make check")` on non-zero), and fall back to the existing hardcoded gate list ONLY when no Makefile is present.

Add regression tests in `tests/test_release.py` following the existing patterns there: one proving the Python branch invokes `make check` when a Makefile exists, one proving it falls back to the hardcoded gate list when no Makefile exists.

`make check` must exit 0 before every commit. No suppressions. OO score must not regress on touched files (use `python tools/oo_score.py <file>` before/after). Add a CHANGELOG.md entry under `## [Unreleased]` (Fixed). Commit incrementally, one logical step per commit.

You are working in an isolated git worktree. Do NOT push and do NOT open a PR — the leader (Claude) will review your branch and create the PR. When done, report: the branch name, the commit SHAs, the exact make-check result, and a one-line summary of what changed. If you hit a write-set block or anything ambiguous, stop and report rather than working around it.