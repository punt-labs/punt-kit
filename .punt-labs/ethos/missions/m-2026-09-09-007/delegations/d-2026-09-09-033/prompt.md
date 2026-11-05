You have an ethos mission to execute: m-2026-09-09-007 (bead pkit-9n6q).

First run `ethos mission show m-2026-09-09-007` and `ethos mission claim m-2026-09-09-007` to load the full contract, then implement it to the letter.

Core task (NARROW scope, operator-ruled): Phase 10 (`src/punt_kit/phases/phase10_propagate.py`) writes two SHA pins during release — (a) the released project's entry in `../.github/install-all.sh`, and (b) the org profile README's pin to the install-all.sh commit. Nothing verifies these pins resolve to the RELEASE TAG's commit, so they can rot silently. Make Phase 11 (`src/punt_kit/phases/phase11_verify.py`) FAIL the release when either pin does not resolve to the release tag's commit for the project being released.

CRITICAL FIRST STEP: read `phase11_verify.py` and report exactly what it already verifies about these two pins relative to the tag (pkit-f85t.3 added a profile-SHA → install-all.sh → marketplace-pin chain check — determine whether that already covers this, partially or fully). Extend to close the SPECIFIC gap; do NOT duplicate existing checks. If Phase 11 already fully verifies both pins against the tag, STOP and report that with code citations — we will close the bead as already-covered rather than add redundant logic. This is a real possibility (several sibling beads in this batch turned out already-fixed); an honest "already covered, here's the proof" is a fully acceptable outcome.

STRICTLY OUT OF SCOPE — do NOT implement and do NOT add a (repo,file,pattern) registry for: product README curl|sh lines, public-website projects.json. Those are a deferred follow-up. If you find yourself building a registry, you've exceeded scope — stop.

Add regression tests in `tests/test_release.py` following the existing phase-11 test patterns: pin-matches-tag passes; pin-stale fails. `make check` must exit 0 before every commit; no suppressions. Do NOT touch CHANGELOG.md (leader owns it).

You are in an isolated git worktree. Do NOT push, do NOT open a PR. Work on branch `fix/pkit-9n6q-verify-install-sha` off main. When done report: the branch name, commit SHAs, your findings on current phase-11 coverage, and the exact make-check result. If a write-set block stops you (e.g. you need a shared helper outside phase11_verify.py/test_release.py), stop and report rather than working around it.