Analyze test coverage for a release-engine bug fix in punt-kit. Report only high-confidence gaps.

Diff: `git diff main..fix/pkit-9n6q-verify-install-sha` — the new regression tests live in tests/test_release.py and cover Phase 11's new `git merge-base --is-ancestor` reachability checks (bead pkit-9n6q). Verify the tests actually exercise: (a) pin IS an ancestor of the tag → check passes; (b) pin is NOT an ancestor (resolves but unreachable) → check fails; for BOTH the install-all.sh check (#4, vs tag) and the profile-SHA check (#6, vs .github main). Confirm the not-ancestor test would actually fail on the pre-fix code (i.e., it genuinely guards the regression, not just the happy path).

Run the diff yourself. If coverage is adequate, say so explicitly.