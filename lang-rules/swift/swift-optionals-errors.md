---
paths:
  - "**/*.swift"
---

# Optionals and Error Handling Standards

`Optional` is the type system refusing to let absence hide; `throws` is the
compiler forcing every caller to face failure. These rules follow
[standards/swift.md](../../standards/swift.md).

## SW-OE-1: No Force-Unwrapping

**Statement**: Force-unwrapping with `!` asserts an invariant the compiler
cannot see, and it crashes the program when the assertion is wrong. It is not
a habit; it is a rare, documented assertion of an invariant that genuinely
cannot fail. Everywhere else, absence is handled with `guard let`, `if let`,
optional chaining, or a `??` default. The lint configuration opts in to
`force_unwrapping`, so an undocumented `!` is a build failure, not a style
note. The same discipline covers `try!` and force-casting with `as!`.

**Criterion**:

- Pass: zero `!` unwraps, `try!`, or `as!` in production code; any exception
  carries an adjacent comment stating the invariant that makes it safe, and
  the lint finding is resolved rather than suppressed
- Fail: `!` used for convenience; an optional unwrapped because "it can't be
  nil here" with nothing enforcing that

**Tooling**:

- SwiftLint: `force_unwrapping` (opt-in, required — SW-TL-2); `force_try` and
  `force_cast` are default rules
- Grep: `grep -rn "try!" --include="*.swift" .` — zero hits outside tests of
  the invariant itself

## SW-OE-2: No Implicitly Unwrapped Optionals

**Statement**: An implicitly unwrapped optional (`T!`) is a force-unwrap
deferred to every use site. Do not declare them. Restructure initialization
so the property is either non-optional and set in `init`, or a real `Optional`
whose absence every reader handles.

**Criterion**:

- Pass: zero `T!` declarations
- Fail: `var engine: AudioEngine!` set "later" by a lifecycle method

**Tooling**:

- SwiftLint: `implicitly_unwrapped_optional` (opt-in, required — SW-TL-2)

## SW-OE-3: Handle Absence at the Edge, Default at Injection

**Statement**: Unwrap early with `guard let` at the top of a scope so the rest
of the function works with non-optional values; use optional chaining for
reads whose absence is benign; use `??` to collapse an optional into a default
where a default is the contract. Optional injection follows the same grain:
a dependency parameter typed `Protocol? = nil` resolves once in the
initializer with `?? Factory.makeDefault()`, and neither path unwraps.

**Criterion**:

- Pass: optionals are unwrapped once, near where absence is decided; deep
  code paths take non-optional parameters
- Fail: the same optional checked at every level of a call chain; `if x != nil`
  followed by `x!`

**Tooling**:

- SwiftLint: `redundant_nil_coalescing` (opt-in) keeps `??` honest
- LLM review: functions taking optionals they immediately require → move the
  unwrap to the caller and make the parameter non-optional

## SW-OE-4: Fallible Operations Throw Typed Errors

**Statement**: Model a fallible operation as a `throws` function whose error
is a typed `enum` conforming to `Error`. Each failure mode is a named case,
and a case carries the context a caller needs as associated values — the
state that made the transition invalid, the field that failed to parse — so
the caller learns why without parsing a string. Guard the precondition and
throw the specific case; do not corrupt state, return a sentinel, or
`fatalError` on input the caller can get wrong.

**Example**:

```swift
enum TransitionError: Error, Equatable {
    case mustBeIdle(current: Mode)
    case alreadyStopped
}

func start() throws {
    guard mode == .idle else {
        throw TransitionError.mustBeIdle(current: mode)
    }
    mode = .running
}
```

**Criterion**:

- Pass: failure modes are enum cases with contextual associated values;
  invalid transitions throw and leave state unchanged
- Fail: throwing a `String`-flavored `NSError`; returning `nil` to mean "the
  operation failed" from a function whose job is to produce a value;
  `fatalError` on reachable input

**Tooling**:

- SwiftLint: `fatal_error_message` (opt-in) — the remaining `fatalError` calls
  say why
- LLM review: `-> T?` returns where `nil` signals failure rather than
  documented absence → convert to `throws`

## SW-OE-5: `do`/`catch` at the Handling Site; `Result` Only When Stored

**Statement**: Handle errors where they occur with `try` inside `do`/`catch`,
or propagate with a `throws` signature — that is the primary error channel.
`Result` is for the narrower case where an outcome must be stored or passed
as a value rather than handled at the throw site. Do not thread `Result`
through code that could simply throw, and never discard an error with
`try?` unless absence-on-failure is genuinely the contract and the discard is
commented.

**Criterion**:

- Pass: `throws`/`do`/`catch` for control flow; `Result` only where the
  outcome is a stored or passed value
- Fail: `Result` returns forcing every caller to `switch` where `throws`
  reads naturally; bare `try?` silently swallowing a failure the caller
  should see

**Tooling**:

- Grep: `grep -rn "try? " --include="*.swift" .` — each hit is either a
  documented absence contract or a finding
- LLM review: `Result`-returning functions whose callers immediately unwrap →
  convert to `throws`

## SW-OE-6: Degrade Gracefully at Persistence Boundaries

**Statement**: Data read from disk or the network is input, not an invariant.
Decode it defensively: pull fields with `as?` and a default where a default
is safe, decode collection elements under their own `do`/`catch` so one
corrupt record degrades to partial data instead of discarding the set —
and never force-unwrap the result of decoding. Internal state already
validated at construction is trusted (SW-OE-4 guards the boundary); external
bytes are not.

**Criterion**:

- Pass: decode failures recover per field or per record with the loss
  contained and observable (logged or surfaced); valid data survives a
  corrupt neighbor
- Fail: one bad record throws away the user's entire store; a decode chained
  through `!`

**Tooling**:

- Test suite: a corrupt-fixture test per persisted type — truncated, missing
  field, wrong type — asserting partial recovery
- LLM review: `JSONDecoder().decode` call sites — what happens to the rest of
  the data when one element fails?
