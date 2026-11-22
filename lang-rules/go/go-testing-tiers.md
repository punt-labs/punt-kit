---
paths:
  - "**/*.go"
  - "go.mod"
---

# Go Testing Tiers

**Introduced:** 2026-11-22

Language rules for the [Testing standard](https://github.com/punt-labs/punt-kit/blob/main/standards/testing.md).

## GO-TST-1: Map suites to local and CI gates

**Implements:** TST-1, TST-2, TST-3 · **Gate:** `make test` and the PR test workflow

Use `go test -race -count=1` for the local and CI Go suites. Select affected packages or use `-run` for Pre-commit; run the default package suite and fast local process checks for Pre-push. Select subprocess, installed-binary and domain checks by package, `-short` or build tag, and run the required selections in PR CI and on main.

## GO-TST-2: Isolate runtime state

**Implements:** TST-4 · **Gate:** `go test -race -count=1` and subprocess tests

Use `t.TempDir`, explicit test environments, loopback listeners on allocated ports and `t.Cleanup`. Prefer `httptest` for provider boundaries; set `exec.Cmd.Env` explicitly for children that could read ambient credentials or Git configuration.

## GO-TST-3: Collect coverage from executed code

**Implements:** TST-5 · **Gate:** CI coverage report

Use `go test -coverprofile` for package tests. For separately exercised binaries use `go build -cover` and `GOCOVERDIR`, then aggregate with `go tool covdata`. Label Go's statement coverage as such, not branch coverage.

## GO-TST-4: Test live, candidate and published paths

**Implements:** TST-6, TST-7, TST-8 · **Gate:** Nightly and release workflows

Select live and agent suites with explicit package, tag or harness commands in trusted workflows. Install or unpack the candidate outside the checkout. For Post-release use the pinned module version or exact production binary according to the supported distribution path.

## GO-TST-5: Expose selection and conformance

**Implements:** TST-9, TST-10 · **Gate:** test selection and review (code-reviewer)

Expose quarantined tests with a separate selection (for example a `quarantine` build tag) and an issue reference at each excluded test. Document package and flag selections for local hooks and CI.
