You are rmh, evaluator on ethos mission m-2026-09-11-020 in <repo> — the last child of the pkit-f85t epic. Worker adb submitted a passing round-1 result: PR #361 (feat/preflight-stash-hint) — Phase 1's stash-hint message for daemon-mutable dirt, plus a bonus off-by-one fix in the existing dirty-tree path parsing. No merges, no deletes; under 30 minutes.

Read: `ethos mission show m-2026-09-11-020`, `ethos mission results m-2026-09-11-020`, `gh pr diff 361`, `direnv exec . bd show pkit-f85t.9`, and the daemon-rewritten note in standards/punt-labs-dir.md.

Evaluate:
1. The three message shapes per the contract: daemon-only dirt → exact `git stash push -- <paths>` command + post-release pop step; mixed dirt → existing failure shape plus the daemon-path listing; clean tree → unchanged. Read the tests; verify each asserts the actual message content, then run one revert experiment (revert the src fix, confirm the daemon-only test fails, restore).
2. The daemon-mutable identification: conservative and documented? Check it can't misclassify (e.g. a local-convention file, a source file under a similarly-named dir); the standard's convention is the reference.
3. THE BONUS FIX (off-by-one in dirty-tree path parsing): verify it's real (what did the old parsing do wrong — porcelain format offset?), correctly scoped, and tested. If it fixed a genuine pre-existing bug, note whether any existing behavior relied on the wrong parse.
4. make check once (pkit-17qo TMPDIR red pre-existing, excluded); bead pkit-f85t.9 closed with accurate text including the auto-stash future note.
If defects: findings + `ethos mission reflect m-2026-09-11-020 --file <path>`. Otherwise no reflect. Report PASS/FAIL per item with evidence and a merge recommendation. Return checkout to main if clean.