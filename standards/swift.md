# Swift Standards

Standards for all Punt Labs Swift projects. This document is the canonical
reference — individual project CLAUDE.md files should reference it, not
duplicate it.

Current Swift project: koch-trainer-swift.

Swift is object-oriented, so unlike C and Go it answers to the shared stance in
[oo.md](oo.md). It is also protocol-oriented, which is Swift's own sharpening of
that stance: the language pushes you to define a family by the behavior its
members answer to rather than by a class they inherit from, and it gives value
types first-class standing so that most of an object's data carries value
semantics instead of shared identity. This document does not restate the
object-oriented philosophy. It shows how the six principles land in Swift
idioms, how the type system turns much of the discipline into something the
compiler checks for you, and how a Swift project is built and held to standard.
koch-trainer-swift is the reference for how we actually write Swift.

---

## Where Swift Fits the Architecture

The [Projection Model](architecture.md#the-projection-model-canonical) describes
a Punt Labs product as one engine fronted by thin library, CLI, MCP, and REST
clients. Swift enters that picture from an angle none of the other languages do,
because Swift's home is the Apple platforms and its most common output is a
native application. A native app is a distribution channel for a
platform-native front end — App Store, TestFlight — and architecture.md places
it outside the four client surfaces of an engine, not as a fifth surface. Read
the invariants in architecture.md before deciding how they apply, because the
ones about multiple client surfaces and a daemon holding per-client state have
no counterpart in a single-user app that keeps its state on the device.

koch-trainer-swift is a standalone native iOS app, not an engine that grows
client surfaces, and it does not pretend to be one. What still governs it is the
internal-structure half of the model: one implementation of each capability,
never duplicated, and a clean boundary between the core that holds the logic and
the thin edges that adapt it to a caller. The app honors that boundary. Its
domain logic — the Koch character ordering and Farnsworth timing in `MorseCode`,
the half-duplex radio state machine in `Radio`, the QSO phase machine in
`QSOState`, and the spaced-repetition, streak, and interval calculators under
`Services/` — lives in pure Swift value types and services with no dependency on
SwiftUI. The SwiftUI views are the thin rendering edge, and the view models
between them are the humble object that adapts the core to the screen. A view
model reaches the audio core through the `AudioEngineProtocol` it was handed
rather than by constructing a concrete engine, so the same domain logic runs
unchanged whether a real `MorseAudioEngine` or a test double sits behind the
protocol. That is the engine-and-clients discipline expressed in an app: one
core, adapted at its edges, never reaching outward through them — the same shape
C keeps in xboing-c with its injected callback table.

When a Swift program genuinely is the engine behind a Punt Labs product — a
Swift package that exports a library surface, or a service with a network front
door — the full model in architecture.md governs it exactly as it governs a Go
or Python engine, and a pure Swift package that exports only types and protocols
is the stateless-leaf carve-out the model already names. The point is to apply
the model as it fits the shape of the project, not to manufacture surfaces a
program has no caller for.

## The Object-Oriented and Protocol-Oriented Stance in Swift

The six principles are stated once, for every language, in [oo.md](oo.md):
behavior lives with its data, an object is told rather than asked for its parts,
dispatch is on the object instead of a conditional, objects are composed rather
than derived through a deep hierarchy, a family is defined by protocol rather
than a base class, and objects are kept small enough that their illegal states
cannot be represented. This section does not re-argue them. It shows the Swift
idiom each one becomes, and where the Swift type system makes the principle
something the compiler enforces rather than something review has to catch.

### Value Types by Default, Reference Types for Identity

Swift gives the choice between a `struct` and a `class` real weight, and the
default is the `struct`. A value type is copied on assignment and has no shared
identity, so two holders of the same value cannot surprise each other by mutating
it out from under one another. Reach for a `class` only when an object needs
identity — when several holders must observe and mutate one shared thing, or when
the object owns a resource whose lifetime matters. A `struct` is not a lighter
`class`; it is a different design decision, and choosing value semantics for data
removes a whole category of aliasing bug before it can be written.

koch-trainer-swift makes the split deliberately. Its data is value-typed:
`QSOState`, `QSOMessage`, `SessionResult`, and the `Timing` parameters are
`struct`s that carry their data by value and expose behavior on themselves —
`QSOState` owns `addMessage(from:text:)` and the `duration` it derives from its
own start time, so the state serializes and advances itself rather than being
manipulated by an outside procedure. Its objects with identity are classes:
`Radio` holds mutable radio state that an audio callback and the UI both read;
`MorseAudioEngine` owns the audio session; the view models own live session
state the SwiftUI runtime observes. Each of those is a `final class` — `final` by
default, because a class that is not designed for inheritance should not admit
it, and Swift lets you say so and lets the compiler devirtualize the calls once
you have.

### Protocols and Protocol Extensions Define a Family by Behavior

This is oo.md's "families share by protocol, not base class," and it is the
principle Swift was built around. A protocol names the messages a family answers;
a type joins the family by implementing them, with no base class to inherit and
no ancestry to share. koch-trainer-swift defines its seams this way.
`AudioEngineProtocol` is the family of things that can play Morse and drive the
radio; `MorseAudioEngine` conforms with the real AVAudioEngine implementation and
a test engine conforms with a silent one, so a view model that holds an
`AudioEngineProtocol` neither knows nor cares which it was given. `ProgressStore`
persists through `ProgressStoreProtocol`, and `NotificationManager` reaches the
system through `NotificationCenterProtocol` and `NotificationSettingsProtocol`,
so a test drives the real notification logic against an in-memory center. The
protocol is the contract; the concrete class behind it is beside the point, which
is exactly what makes the core testable without the device.

Swift adds a move Pharo and Python express differently: a protocol extension can
supply a default implementation for a requirement, so behavior shared across a
family lives on the protocol itself rather than in a base class every member must
descend from. Where a family needs shared code, prefer a protocol extension to an
abstract base — it gives you the shared behavior without the single-inheritance
lineage that a base class forces on every conformer. koch-trainer-swift also uses
Swift's retroactive conformance to fold a framework type into a family it was not
written for: it extends `UNUserNotificationCenter` to conform to
`NotificationCenterProtocol`, so the system type satisfies the app's contract
without the app owning or subclassing it.

### Enumerations Make Illegal States Unrepresentable

oo.md's sharpest form of a focused object is one whose type cannot express an
illegal state, and Swift's enumeration with associated values is the tool that
carries this furthest. An enum is a closed set of cases, each of which may carry
its own data, so a value that can be one of several shapes — each shape with
different fields — becomes a single type in which no invalid shape can be
constructed, and a `switch` over it that misses a case does not compile.

koch-trainer-swift leans on this throughout. `RadioMode` is exactly `off`,
`receiving`, or `transmitting` and nothing else, so the half-duplex invariant
that the radio is never in two states at once is carried by the type rather than
checked at runtime. `Radio.RadioError` names each way a transition can fail and
attaches the offending mode to the case — `mustBeOff(current: RadioMode)`,
`mustBeTransmitting(current: RadioMode)` — so a caller that catches the error
learns why without parsing a string. A view model's `SessionPhase` uses
associated values to bind data to the state it belongs to —
`introduction(characterIndex: Int)`, `completed(didAdvance: Bool, newCharacter:
Character?)` — so the character index exists only while introducing and the
advance result exists only once complete, and no code path can read a field that
the current phase does not have. Every state made unrepresentable this way is a
class of bug that can no longer be written and a runtime check no one has to
remember.

Where a case set is a fixed vocabulary rather than a carrier of data, a
`String`-backed enum replaces the `str`-with-a-comment that oo.md warns against.
`QSOStyle` and `QSOPhase` are `String, Codable, CaseIterable` enums, so the valid
values are the type, the wire form is derived, and the compiler enumerates them
for the UI. There is never a bare string whose comment lists the values it is
allowed to hold.

### Optionals Without the Habit of Force-Unwrapping

Swift's `Optional` is the type system refusing to let absence hide. A value that
may be missing has an optional type, and the compiler will not let you use it as
if it were present until you have handled the missing case. Force-unwrapping with
`!` throws that guarantee away — it asserts an invariant the compiler cannot see,
and it crashes the program when the assertion is wrong. Force-unwrap is therefore
not a habit; it is a rare, documented assertion of an invariant that genuinely
cannot fail, and everywhere else absence is handled with `guard let`, `if let`,
optional chaining, or a `??` default.

koch-trainer-swift enforces this rather than trusting it: its SwiftLint
configuration opts in to the `force_unwrapping` and `implicitly_unwrapped_optional`
rules, so an `!` in production code is a lint failure the build rejects, not a
style note. The code is written to match — `GracefulDecoder` recovers a corrupt
progress file by pulling each field with `as?` and a default and decoding each
history item under its own `do/catch`, keeping the valid ones and dropping the
rest, so a single bad record degrades to partial data instead of a force-unwrap
crash. Optional injection follows the same grain: a view model takes
`audioEngine: AudioEngineProtocol? = nil` and resolves it with `?? AudioEngineFactory.makeEngine()`,
so a caller may supply an engine or accept the default, and neither path unwraps.

### Composition Over Subclassing

oo.md prefers assembling behavior from small collaborating objects to deriving it
through a class hierarchy, and Swift's grain runs the same way — value types
cannot be subclassed at all, and classes are `final` by default here, so
composition is the path of least resistance rather than the disciplined
exception. An object holds its collaborators and delegates to them instead of
inheriting their code.

koch-trainer-swift composes rather than derives. A view model holds an
`AudioEngineProtocol` and an `AccessibilityAnnouncer` passed to its initializer
and delegates the sound and the spoken feedback to them; it does not subclass an
engine to reuse its playback. `MorseAudioEngine` holds a `ToneGenerator` and a
band-conditions processor and drives them; `NotificationManager` holds a
notification center and a `UserDefaults` and coordinates them. The dependencies
arrive through the initializer as protocol-typed parameters, which is why the
same objects that run the app in production run against test doubles in the
suite. There is no deep class tree to read top to bottom; there are small objects
that hold the objects they need.

## Error Handling and Concurrency

### Throwing Functions and Typed Errors

Swift's primary error channel is the throwing function: a method marked `throws`
reports failure by throwing a value, and the compiler forces every caller to
handle it with `try` inside a `do/catch` or to propagate it. Model a fallible
operation as a `throws` function whose error is a typed `enum` conforming to
`Error`, so each failure mode is a named case and a caller can distinguish them.
koch-trainer-swift models its radio state machine exactly this way: every
transition on `Radio` — `startReceiving()`, `startTransmitting()`, `key()`,
`unkey()`, `stop()` — guards its precondition and throws a specific
`RadioError` case when the precondition does not hold, so an invalid transition
is a caught, named error rather than a corrupted state. `Result` is Swift's other
error carrier, for when an outcome must be stored or passed rather than handled
at the throw site; koch-trainer-swift's fallible paths are handled where they
occur, so they use `throws` and `do/catch` — as `GracefulDecoder` does when it
catches a decode failure and falls back — rather than threading a `Result`
through.

### Structured Concurrency and Actor Isolation

Concurrency in Swift is a property the compiler can check, and the standard is to
let it. Use `async`/`await` for asynchronous work rather than nesting completion
handlers, and pin code that touches the UI to the main actor so the compiler
proves it runs there. koch-trainer-swift marks its view models,
`MorseAudioEngine`, and `NotificationManager` `@MainActor`, so their UI-adjacent
state is main-actor-isolated by the compiler rather than by convention. Its audio
playback is `async` — `playCharacter(_:)` and `playGroup(_:)` suspend rather than
block — and it bridges the callback-based system notification API into structured
concurrency with `withCheckedContinuation`, turning `getNotificationSettings`
into an `async` call that reads naturally in sequence.

`Sendable` is the compiler's proof that a value may cross an isolation boundary
safely, and anything that crosses one carries the conformance: koch-trainer-swift
declares `NotificationCenterProtocol` and `NotificationSettingsProtocol` as
`Sendable` and marks the completion closures `@Sendable`, so the checker verifies
the hand-off. The `@unchecked Sendable` escape hatch, which tells the compiler to
trust rather than verify, is used exactly once and with its reason written down:
`Radio` is a `final class` marked `@unchecked Sendable` because it is read from a
real-time audio render callback where actor isolation is not permitted, and its
mutable state is value-typed and guarded by an `NSLock` on every access. That is
the standard for the escape hatch — never reach for `@unchecked Sendable` to
silence the checker without a documented reason that explains why the safety it
would otherwise prove is guaranteed some other way.

## Build and Toolchain

koch-trainer-swift is the reference for the Swift toolchain, and its build is an
Apple-platform app build rather than a SwiftPM package build. The project
structure is declared in `project.yml` and the `.xcodeproj` is generated from it
by XcodeGen, so the checked-in source of truth is the small YAML file and not the
large, merge-hostile Xcode project — the project is regenerated, never
hand-edited. `xcodebuild` compiles and tests the generated project against an iOS
simulator, and a `make` wrapper hides the invocation so the underlying flags need
not be memorized. A Swift package that exports a library instead would build with
SwiftPM and a `Package.swift`, and `swift build` and `swift test` would be its
gate; an app targets the simulator through `xcodebuild`, which is the path
koch-trainer-swift takes.

The Makefile targets are the lifecycle:

| Target | What it does |
|--------|--------------|
| `make generate` | Regenerate the `.xcodeproj` from `project.yml` via XcodeGen |
| `make format` | Apply SwiftFormat across the tree |
| `make lint` | Run SwiftLint with no mutations; a violation fails the target |
| `make build` | Generate, format, lint, then compile the app on the simulator |
| `make test` | Run the unit-test suite through `xcodebuild test` |
| `make ui-test` | Run the UI-test suite (slower; nightly in CI) |
| `make coverage` | Run the unit tests with coverage and report the line percentage |
| `make check` | Build and test — the full quality gate for a change |

The formatter and the linter are two different tools with two different jobs, and
koch-trainer-swift uses both. **SwiftFormat**, configured in `.swiftformat`,
owns canonical formatting — four-space indent, a 120-column width, import
grouping, and the declaration organization that files the members of a type under
`MARK` sections — and `make format` rewrites the source to match. **SwiftLint**,
configured in `.swiftlint.yml`, owns the rules that are about correctness and
smell rather than layout: alongside its default rules it opts in to
`force_unwrapping`, `implicitly_unwrapped_optional`, `empty_count`,
`fatal_error_message`, and others, and sets body-length and complexity
thresholds. `make lint` runs it without mutating, and a violation stops the
build. Because `make build` runs `generate`, `format`, and `lint` before it
compiles, a change cannot reach the compiler without first passing the formatter
and the linter.

Tests are XCTest cases run through `xcodebuild test` against the simulator, split
into a fast unit suite (`KochTrainerTests`) that `make test` and `make check`
run and a slower UI suite (`KochTrainerUITests`) reserved for `make ui-test`.
Because the domain core takes its dependencies through protocols, a unit test
drives real logic — the radio state machine, the interval and streak
calculators, the QSO phase machine — against test doubles for audio,
persistence, and notifications, and asserts on the observable state change with
no device and no audio hardware required. A type ships with its tests, and a
change to a type updates the tests that pin its behavior in the same change.

## Enforcement

Swift carries its coding rules as `.claude/rules/swift-*.md` files, the same
mechanism the other languages use, loaded by an ancestor walk when an agent
touches a matching file. These rules are the Swift analog of the Python rules
under `.claude/rules/python-*.md`, the C rules xboing-c holds under its own
`.claude/rules/`, and the Go rules under `.claude/rules/go-*.md`. They are the
intended home for the value-versus-reference choice, the protocol-family seams,
the enum-for-illegal-states discipline, the ban on habitual force-unwrapping, the
`@MainActor` and `Sendable` conventions, and the documented-reason rule for
`@unchecked Sendable` that the sections above describe — and, like the other
languages' rules, they are to be authored as the Swift codebase grows. A change
to Swift must satisfy them the way a change to Python must satisfy its own.

Swift has no OO ratchet. The ratchet that scores object-oriented quality against
a committed baseline is a Python mechanism, described in [python.md](python.md),
and it exists because model-generated Python drifts toward procedural code that
only looks object-oriented — a dataclass of fields with the behavior scattered
into free functions that reach into it. Swift resists that drift in the type
system itself, which is why it needs no ratchet to measure the drift back out.
Value types with methods keep behavior on the data because there is no separate
record to pull apart; an enum with associated values makes an illegal state a
compile error rather than a metric to be scored; a protocol defines a family the
compiler checks conformance to; `Optional`, `Sendable`, and actor isolation turn
what a Python ratchet can only measure after the fact into something the compiler
proves before the code runs. What holds Swift to its standard is that
compile-time checking combined with the tools the build already runs: SwiftFormat
and SwiftLint reporting zero findings, the XCTest suites passing against the
protocol-injected core, and the `.claude/rules/swift-*.md` files — all run
together by `make check` before a change ships.
