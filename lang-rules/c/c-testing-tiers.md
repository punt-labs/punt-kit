---
paths:
  - "**/*.c"
  - "**/*.h"
  - "**/CMakeLists.txt"
---

# C Testing Tiers

**Introduced:** 2026-11-22

Language rules for the [Testing standard](https://github.com/punt-labs/punt-kit/blob/main/standards/testing.md).
Apply these gates to the CTest conventions in the [C test rules](tests.md).

## C-TST-1: Map suites to local and CI gates

**Implements:** TST-1, TST-2, TST-3 · **Gate:** `make test` and the PR test workflow

Select CTest tests by regex or label for Pre-commit; run the default suite and fast local boundary tests for Pre-push. Use labels for subprocess, installed-artifact, domain and heavier checks, and include the required sanitizer, installed and domain cases in PR CI and on main. Use `ctest --no-tests=error` for required selections.

## C-TST-2: Isolate runtime state

**Implements:** TST-4 · **Gate:** CTest including sanitizer runs

Use temporary directories, injected callbacks and controlled child environments. Use headless drivers where compatible with the assertion. Ensure the harness cleans up test-owned resources on failures and timeouts.

## C-TST-3: Collect coverage from executed code

**Implements:** TST-5 · **Gate:** CI coverage report

Use compiler coverage instrumentation and report with gcov or LLVM coverage tools. Instrument product binaries started by CTest or an external driver when claiming their coverage.

## C-TST-4: Test live, candidate and published paths

**Implements:** TST-6, TST-7, TST-8 · **Gate:** Nightly and release workflows

Select applicable live and agent suites by explicit CTest labels or harness commands in trusted CI. Stage and run the packaged candidate outside the build tree. Use the exact binary or package from the production distribution path for the published smoke.

## C-TST-5: Expose selection and conformance

**Implements:** TST-9, TST-10 · **Gate:** CTest selection and review (code-reviewer)

Use a separately selectable CTest label or target for quarantine, with an issue reference per case. Document the CMake preset, CTest selectors and commands for each tier.
