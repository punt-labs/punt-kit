---
paths:
  - "**/*.swift"
---

# Type Design Standards

Swift realizes the shared object-oriented stance in
[standards/oo.md](../../standards/oo.md); the mechanics here follow
[standards/swift.md](../../standards/swift.md).

## SW-TY-1: Struct by Default, Class Only for Identity

**Statement**: Model data as a `struct`. Reach for a `class` only when the
object needs identity — several holders must observe and mutate one shared
thing, or the object owns a resource whose lifetime matters (an audio session,
a network connection, live state a UI framework observes). A `struct` is not a
lighter `class`; it is a different design decision, and value semantics remove
a whole category of aliasing bug before it can be written.

**Criterion**:

- Pass: domain data, configuration, and state snapshots are `struct`s; classes
  hold shared mutable state or owned resources
- Fail: a `class` whose instances are never shared and own no resource; a
  `struct` copied around when callers need to observe one shared instance

**Tooling**:

- LLM review: for each `class`, name the identity or resource that justifies it

## SW-TY-2: Classes Are `final`; Inheritance Only for Substitutability

**Statement**: Declare every class `final` unless it is explicitly designed for
inheritance. A subclass must be usable everywhere its superclass is expected
and must genuinely be a kind of what its parent is; inheriting purely to reuse
code is composition misfiled as inheritance (SW-PC-5). `final` also lets the
compiler devirtualize the calls.

**Criterion**:

- Pass: every class is `final`, or documents the inheritance contract it is
  designed for
- Fail: a non-`final` class with no subclasses and no documented design for
  them; a subclass that overrides a method to mean something the parent never
  meant

**Tooling**:

- Grep: `grep -rn "^class \|^public class " --include="*.swift" .` — audit each
  non-`final` hit
- LLM review: each subclass passes the "is a kind of" test

## SW-TY-3: Enums Make Illegal States Unrepresentable

**Statement**: When a value can be one of several shapes, each with its own
data, model it as an `enum` with associated values — one type in which no
invalid shape can be constructed, and a `switch` that misses a case does not
compile. Bind data to the case it belongs to, so no code path can read a field
the current state does not have. Do not model a closed state set as a struct of
booleans and optionals whose valid combinations live in a comment.

**Example**:

```swift
enum SessionPhase: Equatable {
    case introduction(characterIndex: Int)
    case training
    case paused
    case completed(didAdvance: Bool)
}
```

The index exists only while introducing; the advance result exists only once
complete. Every state made unrepresentable is a class of bug that can no
longer be written and a runtime check no one has to remember.

**Criterion**:

- Pass: mutually exclusive states are enum cases; per-state data rides in
  associated values; `switch` statements over owned enums are exhaustive
  without `default`
- Fail: a struct with `isLoading: Bool` and `error: Error?` where both can be
  set at once; an invariant between fields enforced only by a runtime check

**Tooling**:

- LLM review: optional fields valid only in certain combinations → propose the
  enum
- Compiler: exhaustive `switch` without `default` turns a new case into a
  compile error at every use site

## SW-TY-4: String-Backed Enums for Fixed Vocabularies

**Statement**: Where a case set is a fixed vocabulary rather than a carrier of
data, use a `String`-backed enum (typically `Codable` and `CaseIterable`) —
never a bare `String` whose comment lists the values it may hold. The valid
values are the type, the wire form is derived, and the compiler enumerates
them for the UI.

**Criterion**:

- Pass: fixed vocabularies are `enum X: String, Codable, CaseIterable`
- Fail: a `String` property with a comment naming its allowed values; string
  comparison against inline literals to branch on kind

**Tooling**:

- Grep: `grep -rn "// one of\|// valid values\|// allowed:" --include="*.swift" .`
  — zero hits
- LLM review: repeated comparison of one property against string literals →
  propose the enum

## SW-TY-5: `let` by Default

**Statement**: Declare bindings and properties with `let`. `var` is a
deliberate choice signaling that mutation is part of the contract — a
`@Published`/observed property the UI tracks, a mutable accumulator, genuinely
changing state. A `var` that is never mutated is a wider contract than the
type needs.

**Criterion**:

- Pass: `var` appears only where mutation occurs or observation requires it
- Fail: `var` on a property assigned only in the initializer

**Tooling**:

- Compiler: "variable was never mutated" warnings are fixed, not ignored
- SwiftFormat: `--self remove` plus lint keep the remainder visible

## SW-TY-6: Behavior Lives With Its Data

**Statement**: A type owns the operations on its state. Derived values are
computed properties or methods on the type; serialization is the type's own
`Codable` conformance or method; state transitions are methods that guard
their own preconditions. A free function that takes a value, reads several of
its properties, and returns something derived from them is a method that has
escaped its type — put it back.

**Criterion**:

- Pass: logic that reads a type's stored properties lives on that type (or an
  extension of it)
- Fail: file-scope functions taking the type as a first parameter and reaching
  into its properties; a "manager" that computes what the value could compute
  itself

**Tooling**:

- Grep: `grep -rn "^func \|^private func " --include="*.swift" .` — audit
  file-scope functions whose first parameter is an owned type
- LLM review: ask what the Pharo equivalent would be; "a message to the object
  that owns the state" passes, "a function reading its parts" fails
