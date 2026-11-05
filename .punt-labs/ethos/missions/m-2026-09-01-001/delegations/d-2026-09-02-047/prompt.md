You are rmh, evaluator on ethos mission m-2026-09-01-001 in <repo>. The previous evaluator run was terminated after wedging on a prohibited rm -rf, so you are a fresh start. HARD CONSTRAINTS: never run rm, rm -rf, git clean, git reset --hard, or any delete; if something seems to need clearing, move it under .tmp/ or report it as a finding instead. Keep the total evaluation under 30 minutes of work.

Subject: PR #336 (branch fix/release-hardening), the worker's fix for three release-engine defects plus regression tests for a fourth already fixed upstream. Note the branch was just updated with a merge from main (commit #337, test-fixture alignment) — fetch first (`git -C . fetch origin`) and evaluate the CURRENT remote branch state (`gh pr diff 336` is authoritative for the diff; do not be confused if the local checkout is stale).

Do, in order:
1. Read `ethos mission show m-2026-09-01-001` and `ethos mission results m-2026-09-01-001` for the contract and the worker's claims.
2. Read `gh pr view 336 --json title,body` and `gh pr diff 336`.
3. Judge each contract item against the diff:
   - pkit-dlv6: preflight warns (not fails) on prior tag with -dev name or version≠tag; tests for clean/dev-name/mismatch/no-tags.
   - pkit-plxh: bounded no-checks grace window (~5 min) failing loudly (names skip-ci markers, gives --resume-from); never merges on zero checks; ruleset detection replaces the misleading legacy-only branch-protection warning; poll loop interrupt-aware; tests for expiry/late-checks/ruleset/legacy.
   - pkit-d7mz: non-success exit prints incomplete-release report (stopped phase, unconfirmed phases, --resume-from); Phase 11 runs after caught Phase 9/10 failure; leg failures reach the recap; DES-029 in DESIGN.md is coherent; regression tests present.
   - pkit-d8ij: the added regression tests genuinely exercise url-with/without-.git and name≠repo paths against the upstream pkit-p328 matcher; endorse or reject closing pkit-d8ij as duplicate of pkit-p328.
   - Tests are meaningful (not tautological), no unauthorized suppressions in the diff, CHANGELOG [Unreleased] entries present.
4. Checkout the PR branch (`git checkout fix/release-hardening` + `git pull`) and run `make check` once. Then run `uv run punt release 99.0.0 --dry-run` and confirm sane output. Do not run anything else long.
5. Report back (no mission reflect unless you find defects requiring another round; if you do, write findings to .tmp/missions/results/ and run `ethos mission reflect m-2026-09-01-001 --file <path>`): PASS/FAIL per criterion, findings with file:line, overall recommendation merge / another round.