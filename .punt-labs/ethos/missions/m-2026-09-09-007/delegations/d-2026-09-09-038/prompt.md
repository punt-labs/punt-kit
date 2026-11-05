Review a release-engine bug fix in punt-kit for silent failures and inadequate error handling. Report only high-confidence findings.

Diff: `git diff main..fix/pkit-9n6q-verify-install-sha` — src/punt_kit/phases/phase11_verify.py, tests/test_release.py.

The change adds `git merge-base --is-ancestor <sha> <tag>` (check #4) and `git merge-base --is-ancestor <profile_sha> main` (check #6) to Phase 11, marking the VerificationCheck failed when the SHA is not reachable. Focus on: does a not-ancestor or an errored git call correctly FAIL the verification (fail-loud), or could either be swallowed / treated as pass? Does the new logic preserve the existing fail paths for the "does not resolve" case? Any path where a stale pin could still slip through as a pass?

Run the diff yourself. If clean, say so explicitly.