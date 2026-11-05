Review a release-engine bug fix in punt-kit against CLAUDE.md and .claude/rules/python-*.md. Report only high-confidence findings.

Diff: `git diff main..fix/pkit-9n6q-verify-install-sha` — files src/punt_kit/phases/phase11_verify.py and tests/test_release.py (bead pkit-9n6q).

The change adds `git merge-base --is-ancestor` reachability checks to Phase 11 verification: (check #4) the project's install-all.sh pinned SHA must be an ancestor of the release tag; (check #6) the org profile README's pinned SHA must be an ancestor of `.github`'s main. Both fail-loud via the existing VerificationCheck/ops.fail pattern.

Review focus:
1. Exit-code handling of `git merge-base --is-ancestor`: it returns 0 (ancestor), 1 (not ancestor), or 128 (bad ref / error). The code treats any non-zero as "not an ancestor." Is conflating error with not-ancestor acceptable here (fail-closed), or does it mislead/misbehave?
2. CRITICAL correctness assumption: check #6 compares profile_sha against `.github` sibling's `main`. Is profile_sha guaranteed to be reachable from `.github` main at the time Phase 11 runs — i.e., does Phase 10 MERGE the sibling .github PR before Phase 11? If Phase 10 leaves the PR open, this check would falsely fail. Verify by reading phase10_propagate.py and how the release orchestrates phases 10→11.
3. Style/standards compliance of the changed code.

Run the diff yourself and read phase10/phase11 as needed. If clean, say so explicitly.