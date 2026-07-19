---
paths:
  - "**/*Tests/**"
  - "**/*UITests/**"
  - "**/*Tests.swift"
---

# Testing Standards

Tests are XCTest cases. Because the domain core takes its dependencies
through protocols (SW-PC-1), a unit test drives real logic against test
doubles and asserts on the observable state change — no device, no hardware.
These rules follow [standards/swift.md](../../standards/swift.md).

## SW-TT-1: Fast Unit Suite, Separate UI Suite

**Statement**: Tests are split into a fast unit-test target that `make test`
and `make check` run on every change, and a slower UI-test target reserved
for its own target (`make ui-test`, nightly in CI). The unit suite must stay
fast enough to run before every commit; anything that boots the full app UI
belongs in the UI suite.

**Criterion**:

- Pass: unit and UI tests live in separate targets; `make check` runs only
  the unit suite; the UI suite has its own target and schedule
- Fail: UI tests mixed into the unit target; a unit suite slow enough that it
  gets skipped

**Tooling**:

- XcodeGen: one `bundle.unit-test` and one `bundle.ui-testing` target in
  `project.yml` (SW-PJ-1)
- Makefile: `test` runs `-only-testing:` the unit target; `ui-test` the UI
  target (SW-PJ-3)

## SW-TT-2: Test Names State Subject, Condition, and Outcome

**Statement**: A test method's name carries the subject, the condition, and
the expected outcome. Two shapes are in use — underscore-separated
(`testStartReceiving_fromOff_succeeds`) and camelCase sentence
(`testSearchWithEmptyQueryStaysIdle`) — and either is acceptable; pick one
per test target and hold to it. The name is the specification line: a
failure report should read as a sentence about the behavior that broke,
without opening the test body.

**Criterion**:

- Pass: test names carry the scenario and the expected outcome, in one
  consistent shape per target
- Fail: `testRadio2`, `testItWorks`, names that repeat the type name and
  nothing else; both naming shapes mixed within one target

**Tooling**:

- LLM review: read the failure list aloud; each line should describe a
  behavior

## SW-TT-3: Drive Real Logic Against Protocol Doubles

**Statement**: Construct the type under test with in-memory conformers of its
protocol seams — a silent audio engine, an in-memory store, a fake
notification center — call its methods, and assert on observable state.
Doubles are hand-written conformances living in a shared test-helpers
location, not ad-hoc copies per test file. Do not test a mock: the logic
exercised must be the production type's own.

**Criterion**:

- Pass: unit tests instantiate production types with doubles injected through
  the initializer; shared doubles live in one helpers file or directory
- Fail: tests requiring the simulator's audio, network, or notification
  permissions to pass; the same fake re-declared in three test files

**Tooling**:

- Test runtime: unit tests complete without device capabilities
- Grep: duplicate double declarations across test files → consolidate into
  helpers

## SW-TT-4: `throws` Tests and `XCTUnwrap`, Never Force-Unwrap

**Statement**: A test that unwraps or decodes declares `throws` and uses
`try XCTUnwrap(...)` to convert absence into a test failure with a location —
never `!`, which converts absence into a crash that takes the suite's
diagnostics with it. The force-unwrapping lint rules apply to test targets
exactly as to production code.

**Criterion**:

- Pass: optional-handling tests are `func test...() throws` with `XCTUnwrap`;
  zero `!` unwraps in test code
- Fail: `value!` in a test body; decoding chained through `try!`

**Tooling**:

- SwiftLint: test targets are not in the `excluded` list, so
  `force_unwrapping` covers them (SW-TL-2)
- Grep: `grep -rn "XCTUnwrap" <test-target>/` — present wherever optionals
  are asserted

## SW-TT-5: Error Paths Are Tested by Case

**Statement**: The suite is the executable specification, and failure is part
of the specification. For each throwing operation, tests cover the failure
modes: assert the thrown error equals the expected typed case — associated
values included — with `XCTAssertThrowsError` and an `Equatable` comparison,
and assert that failed operations leave state unchanged. Happy-path-only
suites are incomplete.

**Example**:

```swift
func testStart_whileRunning_throws() throws {
    let machine = Machine()
    try machine.start()

    XCTAssertThrowsError(try machine.start()) { error in
        XCTAssertEqual(error as? TransitionError, .mustBeIdle(current: .running))
    }
}
```

**Criterion**:

- Pass: each `throws` API has tests per failure case, asserting the specific
  error and the preserved state
- Fail: error handling untested; a test asserting only "some error was
  thrown"

**Tooling**:

- LLM review: for each `enum ...: Error`, is every case constructed by some
  test?

## SW-TT-6: A Type Ships With Its Tests, and the Trees Mirror

**Statement**: A change to a type updates the tests that pin its behavior in
the same change; a new type arrives with its tests. The test target mirrors
the source layout — tests for `Models/` under the test target's `Models/`,
services under `Services/`, view models under `ViewModels/` — so the tests
for a type are found by path.

**Criterion**:

- Pass: diffs touching a type touch its tests; the test tree's directories
  mirror the source tree's
- Fail: a behavior change with no test change; test files piled flat while
  the source tree is structured

**Tooling**:

- LLM review: diff includes test changes proportional to source changes
- Grep: for each source directory, a matching test directory exists once the
  target is large enough to structure
