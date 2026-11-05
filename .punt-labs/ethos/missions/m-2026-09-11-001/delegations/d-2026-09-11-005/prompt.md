You are rmh, evaluator on ethos mission m-2026-09-11-001 in <repo>. Worker adb submitted a passing result: PR #355 (branch feat/harness-wave0) — the Wave 0 harness primitives (tests/harness/fault_ops.py + 22 unit tests). No code edits, no merges, no deletes (scratch under .tmp/ only); keep it under 40 minutes.

Read: `ethos mission show m-2026-09-11-001`, `ethos mission results m-2026-09-11-001` (including the worker's five declared design deviations), `gh pr diff 355`, and the merged design's mechanism sections (docs/design-release-failure-harness.md §2a, §2c, and the Wave 0 acceptance list — the design is the mechanism authority, it superseded parts of the contract).

Evaluate:
1. Contract criteria as amended by the design: FaultRule semantics (basename argv[0] matching, skip/times/responses with _UNSET derivation, exactly-one-of validation), deny-by-default with prefix-scoped passthrough (the negative test: ["gh","--version"] must not admit ["gh","pr","merge"]), interrupt mechanisms per the FINAL design (raises=KeyboardInterrupt + rule-anchored interrupt_after; no blocking primitive), from_fixture stub.
2. Thread-safety: read the lock discipline in fault_ops.py and the ThreadPoolExecutor test — is consumption of times-bounded rules genuinely exactly-once under concurrency, and does the test actually race (not just run serially by accident)?
3. Test quality: the 22 tests are meaningful, not tautological; happy/invalid/boundary per criterion; run `make check` yourself on the branch (checkout feat/harness-wave0 — the main checkout is on main and free; switch back to main when done).
4. The five declared deviations: judge each (sound / needs change), especially #2 (interrupt_after as a FaultRule method) and #4 (constructor validation) — do they preserve the design's semantics?
5. No src/ changes, no existing-test modifications, CHANGELOG present, no unauthorized suppressions.

If defects require another round: findings to .tmp/missions/results/, `ethos mission reflect m-2026-09-11-001 --file <path>`. Otherwise no reflect. Report: PASS/FAIL per item with file:line evidence, deviation verdicts, and merge / another-round recommendation.