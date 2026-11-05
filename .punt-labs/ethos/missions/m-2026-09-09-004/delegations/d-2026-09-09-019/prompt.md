Review two small bug-fix branches in punt-kit for silent failures, swallowed errors, and inadequate error handling. Report only high-confidence findings.

Diff 1: `git diff main..fix/pkit-8r6-doctor-optional` — src/punt_kit/doctor.py, tests/test_doctor.py.
Diff 2: `git diff main..fix/pkit-mjcb-preflight-make-check` — src/punt_kit/phases/phase01_preflight.py, tests/test_release.py. Pay attention to whether the new `make check` branch correctly fails the release (ops.fail) on non-zero exit, matching the Go branch, and doesn't swallow a gate failure.

Run the diffs yourself. If clean, say so explicitly.