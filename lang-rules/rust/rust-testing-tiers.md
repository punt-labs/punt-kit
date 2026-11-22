---
paths:
  - "**/*.rs"
  - "Cargo.toml"
---

# Rust Testing Tiers

**Introduced:** 2026-11-22

Language rules for the [Testing standard](https://github.com/punt-labs/punt-kit/blob/main/standards/testing.md).

## RUST-TST-1: Map suites to local and CI gates

**Implements:** TST-1, TST-2, TST-3 · **Gate:** `cargo test` and the PR test workflow

Use Cargo's harness with inline unit tests and integration targets in `tests/`. Select packages or names for Pre-commit, and run the default workspace suite and fast local boundary checks for Pre-push. In PR CI and on main run the full default suite and applicable built-artifact and domain checks. Use separate test targets or feature sets for heavier cases.

## RUST-TST-2: Isolate runtime state

**Implements:** TST-4 · **Gate:** Cargo integration tests

Use temporary directories, injected configuration and test-owned fakes on allocated ports. Set an explicit environment on `std::process::Command` and shut down child processes after the case.

## RUST-TST-3: Collect coverage from executed code

**Implements:** TST-5 · **Gate:** CI coverage report

Use `cargo llvm-cov` for instrumented tests. For process coverage, instrument the launched binaries, collect distinct LLVM profile files and merge before reporting. State compiler, selection and available metrics.

## RUST-TST-4: Test live, candidate and published paths

**Implements:** TST-6, TST-7, TST-8 · **Gate:** Nightly and release workflows

Select live and agent test targets or features explicitly in trusted CI. Install the candidate from the packaged crate or run the shipped binary, not a new build from the working tree. For Post-release use the pinned production crate version or the production binary.

## RUST-TST-5: Expose selection and conformance

**Implements:** TST-9, TST-10 · **Gate:** Cargo selection and review (code-reviewer)

Keep quarantines in a separate target or use `#[ignore = "issue and reason"]` with a command to list and run the ignored cases. Document Cargo targets and feature sets by tier.
