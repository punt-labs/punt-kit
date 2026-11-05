Verify a claimed invariant in a punt-kit release change. Bead pkit-fesz, branch fix/pkit-fesz-verify-readme-website.

The new `ReadmeShaPin.find_pinned_shas` (src/punt_kit/phases/shared/readme_sha.py) claims (in its docstring) to use the "same URL shape `bump()` writes ... shared so Phase 11's verification never drifts from the pattern the landing PR actually writes." Phase 11 Check 7 relies on this to catch EVERY stale SHA pin in a README.

Verify the invariant actually holds:
1. Read `ReadmeShaPin.bump()` and confirm the EXACT install-URL string(s) it writes, then confirm `find_pinned_shas`'s regex (`raw\.githubusercontent\.com/<owner>/<repo>/([0-9a-fA-F]{7,40})/install\.sh`) matches every URL form `bump()` can produce. If `bump()` writes any URL variant (e.g. a `--no-plugin` install line, a `curl -o` form, a different host like `github.com/.../raw/`) that `find_pinned_shas` would NOT match, that's a completeness hole — Check 7 would silently miss those pins. Report any divergence between what bump() writes and what find_pinned_shas matches.
2. Confirm Check 7 iterates ALL matches (its claim "every pin ... rather than just the first"), not one.

Run `git diff main..fix/pkit-fesz-verify-readme-website` and read both files. State whether the invariant holds or is violated with specifics.