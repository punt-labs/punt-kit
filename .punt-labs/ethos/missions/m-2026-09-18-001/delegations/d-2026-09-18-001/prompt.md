You have an ethos mission: m-2026-09-18-001 (bead pkit-fesz — extend release-time SHA-pin verification). Run `ethos mission show m-2026-09-18-001` and `ethos mission claim m-2026-09-18-001`, then implement it to the letter.

Context: Phase 11 (`src/punt_kit/phases/phase11_verify.py`) currently verifies the git tag, plugin.json version, the `.github/install-all.sh` entry (check #4, ancestor-of-tag), and the org profile README SHA (check #6, ancestor-of-.github-main). It does NOT yet verify two other places a release SHA gets pinned, which rot silently (a stale pin still "works" — it just installs the previous release):
(a) the released repo's OWN README curl|sh install lines (e.g. a product README pinned several times; the release lands them via ReadmeShaPin/`_land_readme_sha_pin` — reuse the regex/pattern from `src/punt_kit/phases/shared/readme_sha.py`);
(b) the public-website `projects.json` (installCommand pinned SHA + a `version` field), propagated by Phase 10 but never verified. public-website is an OPTIONAL sibling.

FIRST: read phase11_verify.py and readme_sha.py and report what's verified today for each of these two, citing code. If either is already fully verified against the release tag/version, say so and skip it (don't duplicate) — like several sibling checks turned out already-covered in prior work.

Then add Phase 11 checks, failing loud (VerificationCheck False → the phase fails), matching the existing checks #4/#6 style:
- Every pinned install SHA in the released repo's own README must be an ancestor of the release tag's commit (cover ALL curl|sh pins, not just the first).
- The public-website projects.json installCommand SHA must be an ancestor of the release tag AND its `version` field must equal the release version. An absent public-website sibling is the existing tolerated skip (as install-all.sh/profile checks already handle absent siblings), NOT a failure.

You may create a small (repo,file,pattern) consumer registry under `src/punt_kit/phases/shared/` if it makes the checks cleaner (authorized) — but don't over-engineer; inline is fine.

Add regression tests in `tests/test_release.py` (existing phase-11 patterns): pass; stale README pin fails; website SHA-not-ancestor fails; website version-mismatch fails; absent website sibling skips cleanly.

`make check` must exit 0 before every commit; no suppressions. Do NOT touch CHANGELOG.md (leader owns it). You're in an isolated worktree — do NOT push, do NOT open a PR. Branch `fix/pkit-fesz-verify-readme-website` off main. Report: branch, commit SHAs, your current-coverage findings, and the make-check result. If you need a write-set path beyond phase11_verify.py / tests/test_release.py / new files under phases/shared/, stop and report.