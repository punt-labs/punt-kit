---
paths:
  - "**/*.swift"
---

# Concurrency Standards

Concurrency in Swift is a property the compiler can check, and the standard is
to let it. These rules follow [standards/swift.md](../../standards/swift.md).

## SW-CC-1: `async`/`await` Over Completion Handlers

**Statement**: Asynchronous work is written with `async`/`await` and
structured concurrency — `Task`, `TaskGroup`, cancellation — not with nested
completion handlers or new Combine pipelines. Suspend rather than block: an
operation that waits is `async`, and its callers read in sequence. Reach for
Combine only where a framework hands you a publisher; do not build new
callback pyramids the language has a construct for.

**Criterion**:

- Pass: new asynchronous APIs are `async` functions; long operations suspend
- Fail: new code taking `completion: @escaping (T) -> Void` where the caller
  could `await`; blocking a thread to wait for a result

**Tooling**:

- Grep: `grep -rn "@escaping" --include="*.swift" .` — new completion-handler
  APIs are findings; bridges to callback frameworks are the exception
- LLM review: nested closures expressing sequence → rewrite as sequential
  `await`s

## SW-CC-2: `@MainActor` on UI-Touching Code

**Statement**: Pin code that touches the UI to the main actor so the compiler
proves it runs there. View models, and services whose state SwiftUI observes
or that call UI-facing frameworks, are declared `@MainActor`. Isolation by
annotation replaces isolation by convention — no `DispatchQueue.main.async`
sprinkled where the type should simply be main-actor-isolated.

**Criterion**:

- Pass: every observable view model is `@MainActor final class`; UI-adjacent
  services are `@MainActor`; the compiler, not a comment, guarantees the thread
- Fail: a view model mutated from a background task without isolation;
  `DispatchQueue.main.async` inside a type that should be `@MainActor`

**Tooling**:

- Grep: `grep -rn "DispatchQueue.main" --include="*.swift" .` — each hit is a
  candidate for actor isolation instead
- Compiler: strict concurrency checking surfaces the violations; fix them, do
  not downgrade the checking level

## SW-CC-3: Bridge Callback APIs With Checked Continuations

**Statement**: When a system API only speaks completion handlers, wrap it once
with `withCheckedContinuation` or `withCheckedThrowingContinuation` so the
rest of the codebase sees an `async` function. The bridge lives at the seam
(SW-PC-1, SW-PC-3), resumes exactly once, and keeps the callback style from
leaking inward.

**Example**:

```swift
func notificationSettings() async -> NotificationSettings {
    await withCheckedContinuation { continuation in
        center.getNotificationSettings { settings in
            continuation.resume(returning: NotificationSettings(settings))
        }
    }
}
```

**Criterion**:

- Pass: callback-based system APIs are bridged once at the boundary; domain
  code awaits
- Fail: completion handlers threaded through domain logic because a leaf API
  uses them; a continuation resumable zero or two times on some path

**Tooling**:

- LLM review: every continuation body — one `resume` on every path, no path
  with two

## SW-CC-4: `Sendable` Across Isolation Boundaries

**Statement**: `Sendable` is the compiler's proof that a value may cross an
isolation boundary safely, and anything that crosses one carries the
conformance. Value types crossing boundaries conform (usually for free);
protocols whose conformers cross declare `Sendable` as a requirement;
closures handed across are `@Sendable`. Let the checker verify the hand-off
instead of trusting it.

**Criterion**:

- Pass: types and closures crossing actor or task boundaries are checked
  `Sendable`; strict concurrency checking reports zero diagnostics
- Fail: a non-`Sendable` class shared across tasks; a warning silenced by
  lowering the checking level

**Tooling**:

- Compiler: build with strict concurrency checking; treat its diagnostics as
  errors to fix
- LLM review: protocol seams whose conformers are used from multiple
  isolation domains → add `Sendable` to the protocol

## SW-CC-5: `@unchecked Sendable` Requires a Written Reason

**Statement**: `@unchecked Sendable` tells the compiler to trust rather than
verify. It is permitted only when actor isolation genuinely cannot apply —
for example, state read from a real-time render callback where suspension is
not allowed — and only with the reason written down at the declaration: why
isolation cannot be used, and how the safety the compiler would otherwise
prove is guaranteed another way (value-typed state guarded by a lock on every
access). Never reach for it to silence the checker.

**Example**:

```swift
/// NOTE: `@unchecked Sendable` because instances are read from a real-time
/// audio render callback where actor isolation is not permitted. All mutable
/// state is value-typed and accessed only while holding `lock`.
final class ToneState: @unchecked Sendable {
    private let lock = NSLock()
    private var frequency: Double = 0
}
```

**Criterion**:

- Pass: each `@unchecked Sendable` has an adjacent comment naming the
  constraint that rules out an actor and the mechanism that guarantees
  safety; every mutable member is covered by that mechanism
- Fail: `@unchecked Sendable` with no comment; a "documented" one whose lock
  does not actually cover every access

**Tooling**:

- Grep: `grep -rn "@unchecked Sendable" --include="*.swift" .` — each hit has
  the reason and the mechanism in the adjacent doc comment
- LLM review: verify every mutable stored property of the type is accessed
  only under the documented guard
