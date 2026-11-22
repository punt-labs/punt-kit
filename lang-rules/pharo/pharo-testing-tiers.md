---
paths:
  - "src/**/*.st"
  - "**/*.tonel"
---

# Pharo Testing Tiers

**Introduced:** 2026-11-22

Language rules for the [Testing standard](https://github.com/punt-labs/punt-kit/blob/main/standards/testing.md).

## PH-TST-1: Map suites to local and CI gates

**Implements:** TST-1, TST-2, TST-3 · **Gate:** SUnit result and headless CI exit status

Use SUnit `TestCase` subclasses. Select classes or named suites for Pre-commit, the fast suite and local boundary checks for Pre-push, and the complete credential-free suite plus applicable packaging and domain checks in PR CI and on main. Run the project suite runner in a headless image; propagate SUnit failures and errors to a nonzero exit status.

## PH-TST-2: Isolate runtime state

**Implements:** TST-4 · **Gate:** SUnit and the headless harness

Load a fresh copy of the pinned image with explicit paths and injected stubs. Use a test-owned server or child VM where needed, not a developer's running image. Tear down image processes and temporary state.

## PH-TST-3: Collect coverage from executed code

**Implements:** TST-5 · **Gate:** in-image coverage report

Use in-image SUnit coverage tooling, such as the Test Runner coverage facility where available in the pinned image. State the instrumented packages and reported metric. If testing a second image, instrument it before claiming coverage of its methods.

## PH-TST-4: Test live, candidate and published paths

**Implements:** TST-6, TST-7, TST-8 · **Gate:** Nightly and release workflows

Name separate SUnit suites for live and agent tests and run them with explicit trusted inputs. Test clean images loaded from the exact candidate and published package versions, or launch the shipped image itself if that is the artifact.

## PH-TST-5: Expose selection and conformance

**Implements:** TST-9, TST-10 · **Gate:** SUnit suite selection and review (code-reviewer)

Keep quarantined cases in a separately runnable named suite with issue references. Document the headless invocation, image and VM, baseline and suite selection by tier.
