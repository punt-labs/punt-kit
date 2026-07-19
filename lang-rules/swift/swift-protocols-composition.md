---
paths:
  - "**/*.swift"
---

# Protocol and Composition Standards

Swift is protocol-oriented: a family is defined by the behavior its members
answer to, not by a class they inherit from. These rules realize the stance in
[standards/oo.md](../../standards/oo.md) as described in
[standards/swift.md](../../standards/swift.md).

## SW-PC-1: Seams Are Protocols, Injected Through the Initializer

**Statement**: A type reaches its collaborators — audio, persistence,
networking, notifications, the system clock — through protocol-typed
parameters handed to its initializer, never by constructing a concrete
implementation inside. The protocol is the contract; the concrete type behind
it is beside the point. This is what makes the core testable without the
device: the same object that runs in production runs against a test double in
the suite.

**Example**:

```swift
@MainActor
final class TrainingViewModel: ObservableObject {
    init(audioEngine: AudioEngineProtocol? = nil) {
        self.audioEngine = audioEngine ?? AudioEngineFactory.makeEngine()
    }

    private let audioEngine: AudioEngineProtocol
}
```

The caller may supply an engine or accept the default, and neither path
constructs a concrete engine at the use site.

**Criterion**:

- Pass: side-effectful dependencies arrive as protocol-typed initializer
  parameters; production defaults resolve through a factory or `??` default
- Fail: a view model or service that instantiates its own concrete
  collaborator inside a method; a singleton reached directly from domain logic

**Tooling**:

- LLM review: each stored dependency of a class — is its type a protocol?
- Test suite: unit tests construct the type with doubles; needing the real
  dependency in a unit test is the failure surfacing

## SW-PC-2: Families Share by Protocol, Not Base Class

**Statement**: Define a family of related types by the protocol its members
conform to. Where the family needs shared code, put it in a protocol
extension — a default implementation for a requirement — rather than an
abstract base class every member must descend from. The extension gives shared
behavior without the single-inheritance lineage a base class forces on every
conformer, and it lets one type belong to several families at once.

**Criterion**:

- Pass: families are protocols; shared behavior lives in protocol extensions;
  unrelated types conform to the same contract
- Fail: an abstract-base-class pattern (a class existing only to be
  subclassed, with `fatalError("subclass must override")` bodies); shared code
  pushed into a superclass that members carry whether they need it or not

**Tooling**:

- Grep: `grep -rn "fatalError(\"" --include="*.swift" .` — "must override"
  bodies are the abstract-base smell
- LLM review: class hierarchies deeper than one level need justification

## SW-PC-3: Retroactive Conformance Folds Framework Types Into Families

**Statement**: When a framework or system type should satisfy an app-defined
contract, extend it to conform to the protocol rather than wrapping or
subclassing it. The system type then satisfies the app's contract without the
app owning it, and a test double conforms to the same protocol in its place.

**Example**:

```swift
protocol NotificationCenterProtocol: Sendable {
    func add(_ request: UNNotificationRequest) async throws
}

extension UNUserNotificationCenter: @unchecked Sendable, NotificationCenterProtocol {}
```

The system type does not declare `Sendable` itself, so the extension asserts
it `@unchecked` — an assertion that falls under SW-CC-5's documented-reason
discipline like any other.

**Criterion**:

- Pass: system types join app protocols by extension; tests substitute an
  in-memory conformer
- Fail: a hand-written wrapper class that only forwards calls to the system
  type; domain logic calling the system singleton directly

**Tooling**:

- LLM review: direct use of system singletons (`UNUserNotificationCenter
  .current()`, `URLSession.shared`) inside domain logic → propose the protocol
  seam

## SW-PC-4: Polymorphism Over Kind-Switching

**Statement**: An exhaustive `switch` over an enum you own is idiomatic Swift —
that is dispatch the compiler checks (SW-TY-3). What is not idiomatic is a
kind tag branched on at multiple sites, where every new kind means opening
every function that switches and adding a branch to each. When a family is
open — new kinds arrive as the program grows — each branch is a method that
belongs on the member, and the family is a protocol (SW-PC-2): new cases
arrive as new conforming types, and existing code dispatches to them without
being touched.

**Criterion**:

- Pass: closed, stable state sets are enums with exhaustive switches; open
  families are protocols whose members answer the message themselves
- Fail: the same kind tag switched on in three or more places; adding a
  variant requires editing every site that branches

**Tooling**:

- Grep: count `switch` statements over the same enum; three or more sites
  performing kind-specific *behavior* (not state display) → propose the
  protocol
- LLM review: "what happens when a new case arrives?" — new class good, new
  branch threaded through old code bad

## SW-PC-5: Composition Over Subclassing

**Statement**: Assemble behavior from small collaborating objects; do not
derive it through a class hierarchy. An object holds its collaborators and
delegates to them — an engine holds its tone generator and drives it, a
manager holds a store and coordinates it. Swift's grain runs this way: value
types cannot be subclassed and classes are `final` (SW-TY-2), so composition
is the path of least resistance. Hold the object you want to reuse and call
it; do not become it.

**Criterion**:

- Pass: shared behavior reached by holding and delegating; class hierarchies
  are shallow and justified by substitutability
- Fail: subclassing to reuse methods; a subclass that refuses part of the
  interface it inherited

**Tooling**:

- LLM review: every `class B: A` where `A` is not a framework requirement gets
  the "is a kind of" question

## SW-PC-6: Tell, Don't Ask

**Statement**: Ask an object to perform work; do not extract its data and
perform the work in the caller. A method talks to its own object, the objects
it was handed, and the objects it creates — not to the objects those objects
happen to hold. A chain of accessors walking two objects deep entangles the
caller with a structure it never should have known about.

**Criterion**:

- Pass: callers invoke behavior; objects check their own preconditions and
  derive their own values
- Fail: read a property, compute outside, write the property back; accessor
  chains like `session.progress.schedule.streak` in code that owns only
  `session`

**Tooling**:

- LLM review: multi-step property chains in callers → move the behavior to the
  owner
- Grep: `grep -rnE "\.[a-z]\w+\.[a-z]\w+\.[a-z]\w+" --include="*.swift" .` —
  audit deep chains (SwiftUI view builders exempt)

## SW-PC-7: Small, Focused Types

**Statement**: A type has one responsibility and therefore one reason to
change. When a type grows several unrelated concerns, extract each into its
own object and delegate. The SwiftLint thresholds are the enforcement floor —
60-line function bodies, 400-line type bodies, 750-line files, cyclomatic
complexity 15 at warning level (SW-TL-2) — but the design test is
responsibility, not line count: the right number of types is usually more
than you first think.

**Criterion**:

- Pass: each type names one job; lint length and complexity thresholds report
  zero findings
- Fail: a "God object" coordinating unrelated concerns; a threshold raised in
  configuration to accommodate a growing type

**Tooling**:

- SwiftLint: `function_body_length`, `type_body_length`, `file_length`,
  `cyclomatic_complexity` at the canonical thresholds (SW-TL-2)
- LLM review: state each type's responsibility in one sentence; needing "and"
  is the smell
