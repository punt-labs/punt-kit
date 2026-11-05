Analyze test coverage for two small bug-fix branches in punt-kit. Report only high-confidence gaps.

Diff 1 (pkit-8r6): `git diff main..fix/pkit-8r6-doctor-optional` — new tests/test_doctor.py should cover all four cases: not-found-optional (exactly one "(optional)"), not-found-required, found-optional, found-required. Verify the rendered-line assertions actually catch the doubling regression.

Diff 2 (pkit-mjcb): `git diff main..fix/pkit-mjcb-preflight-make-check` — new tests in tests/test_release.py should prove the Python branch invokes `make check` when a Makefile exists and falls back to the hardcoded gates when it doesn't.

Run the diffs yourself. If coverage is adequate, say so explicitly.