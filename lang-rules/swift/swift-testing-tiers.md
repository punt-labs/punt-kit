---
paths:
  - "**/*.swift"
  - "**/Package.swift"
  - "project.yml"
---

# Swift Testing Tiers

**Introduced:** 2026-11-22

Language rules for the [Testing standard](https://github.com/punt-labs/punt-kit/blob/main/standards/testing.md).
These gates use the unit and UI suite split in SW-TT-1; the
Pre-commit gate can select just the affected unit cases.

## SW-TST-1: Map suites to local and CI gates

**Implements:** TST-1, TST-2, TST-3 · **Gate:** `make test` and the PR test workflow

Select the fast Pre-commit subset with `xcodebuild test -only-testing:…` for Xcode or `swift test --filter` for SwiftPM. Run the default unit target and fast local boundary checks for Pre-push; run the required simulator or installed-app and domain checks in PR CI and on main. Put broader UI cases in a separate target or test plan for Nightly.

## SW-TST-2: Isolate runtime state

**Implements:** TST-4 · **Gate:** Xcode test plan or SwiftPM tests

Use temporary directories, injected configuration and protocol doubles. Pin the destination and isolate simulator or app state. Preserve the test command's exit status when filtering console output.

## SW-TST-3: Collect coverage from executed code

**Implements:** TST-5 · **Gate:** CI coverage report

For Xcode, use `-enableCodeCoverage YES` and read the result bundle with `xccov`. For SwiftPM, enable coverage with `swift test --enable-code-coverage` and report using the Swift toolchain's LLVM tools. Say whether the report includes the app or only the test host.

## SW-TST-4: Test live, candidate and published paths

**Implements:** TST-6, TST-7, TST-8 · **Gate:** Nightly and release workflows

Select live and agent cases through named targets or plans in trusted workflows. Test the actual candidate app or binary on a supported destination, not a debug rebuild from the checkout. Exercise the exact version fetched through the supported production channel for Post-release.

## SW-TST-5: Expose selection and conformance

**Implements:** TST-9, TST-10 · **Gate:** test plan and review (code-reviewer)

Keep quarantined cases separately runnable, for example in an alternate test plan, with tracked reasons. Document the target, plan and destination for each tier.
