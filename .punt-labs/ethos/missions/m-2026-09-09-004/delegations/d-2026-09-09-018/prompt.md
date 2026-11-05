Review two small bug-fix branches in punt-kit against the project's CLAUDE.md and .claude/rules/python-*.md standards. Report only high-confidence findings.

Diff 1 (bead pkit-8r6): `git diff main..fix/pkit-8r6-doctor-optional` — files src/punt_kit/doctor.py and tests/test_doctor.py. Fix removes a doubled "(optional)" in `punt doctor` output by making a new module-level `_status_suffix(result: CheckResult)` the single owner of the (required)/(optional) annotation. NOTE specifically: is `_status_suffix` a PY-OO-7 "method in disguise" (it takes CheckResult and reads its fields) that should instead be a method/property on the CheckResult dataclass? Weigh that against the module already being all free functions.

Diff 2 (bead pkit-mjcb): `git diff main..fix/pkit-mjcb-preflight-make-check` — files src/punt_kit/phases/phase01_preflight.py and tests/test_release.py. Fix makes the Python quality-gate branch prefer `make check` when a Makefile exists, mirroring the Go branch, falling back to the hardcoded gate list otherwise.

Run the diffs yourself. Report findings per file with severity and a concrete fix. If a diff is clean, say so explicitly.