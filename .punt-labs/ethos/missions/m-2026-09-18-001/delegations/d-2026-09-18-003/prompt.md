Review a release-engine change in punt-kit against CLAUDE.md and .claude/rules/python-*.md. High-confidence findings only.

Diff: `git diff main..fix/pkit-fesz-verify-readme-website` — src/punt_kit/phases/phase11_verify.py, src/punt_kit/phases/shared/readme_sha.py, tests/test_release.py (bead pkit-fesz).

Adds Phase 11 Check 7 (every SHA pin in the released repo's own README must be an ancestor of the release tag) and Check 8 (website projects.json installCommand SHA must be an ancestor of the tag; the version check pre-existed). New `ReadmeShaPin.find_pinned_shas` staticmethod and `VerificationCheck.pinned_ancestor` classmethod.

Focus: correctness of the new checks; the gating conditions (`install_sh.exists()`, `f"/{project_name}/" in install_cmd`); whether `pinned_ancestor`'s exit-code handling (0/1/≥128) is right; style/standards. Note `readme_sha.py` gained a staticmethod — assess whether that's the right home for it. Run the diff. If clean, say so.