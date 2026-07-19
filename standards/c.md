# C Standards

Standards for all Punt Labs C projects. This document is the canonical
reference — individual project CLAUDE.md files should reference it, not
duplicate it.

Current C project: xboing-c.

C is idiomatic in its own paradigm. It is a procedural systems language, and we
write it that way. It is not object-oriented, so it does not answer to
[oo.md](oo.md); nothing in this document asks C to imitate objects. Where a C
module hides its representation behind an opaque handle, it does so for
information hiding and a stable interface, not to become a class.

---

## Where C Fits the Architecture

The [Projection Model](architecture.md#the-projection-model-canonical) describes
a Punt Labs product as one engine fronted by thin library, CLI, MCP, and REST
clients. C usually enters that picture from a different angle than Python or Go
do. A Python or Go product is often the engine that sprouts four surfaces. A C
program is more often a whole engine on its own, or a performance-critical
component inside a larger engine, than a service designed to grow client
surfaces.

Read the invariants in architecture.md before deciding how they apply, because
much of what they govern — multiple client surfaces, a daemon that holds
per-client state — has no counterpart in a self-contained C binary. The parts
that always apply are the ones about internal structure: one implementation of a
capability, never duplicated, and a clean boundary between the core that holds
the logic and the thin edges that adapt it to a caller.

xboing-c is a standalone game binary, not an engine-with-surfaces, and it does
not pretend to be one. Its internal structure still honors the boundary the
model cares about. The game logic — ball physics, block state, scoring — lives
in pure C modules with no dependency on SDL2 or X11, and the rendering, audio,
and input layers are the thin edges that drive those modules. A logic module in
xboing-c communicates its side effects through an injected callback table rather
than calling the renderer directly, so the same physics runs unchanged whether a
real SDL2 frame or a test harness sits on the other side of the callbacks. That
is the engine-and-clients discipline expressed in C: one core, adapted at its
edges, never reaching outward through them.

When a C program genuinely is the engine behind a Punt Labs product with library
or network surfaces, the full model in architecture.md governs it exactly as it
governs a Go or Python engine. The point is to apply the model as it fits, not to
manufacture surfaces a program has no caller for.

## Idiomatic C Discipline

C gives the programmer full control of memory and the machine and withholds the
safety nets that other languages provide. The discipline below is what keeps that
control from turning into leaks, corruption, and undefined behavior. It is the
K&R lineage applied to a modern codebase, and xboing-c is the reference for how
it looks in practice.

### Memory Ownership and Lifetime

Every allocation has one owner, and ownership is stated in the interface, not
left for the reader to infer. A function that returns a pointer says in its
header comment whether the caller must free it. A module that hands out an object
through a `create` function reclaims it through a matching `destroy` function,
and nothing outside the module frees what the module allocated. xboing-c follows
this create/destroy lifecycle for every module that owns heap state.

Free each allocation exactly once, through its owner, and never touch a pointer
after it has been freed. Set a freed pointer to `NULL` when the surrounding code
may reach it again, so a stray use fails loudly instead of corrupting the heap.
Prefer `calloc` over `malloc`: zero-initialized memory removes a class of
undefined behavior that arises when a field is read before it is set, and
xboing-c uses `calloc` for exactly that reason.

The AddressSanitizer build described below exists to catch the mistakes this
discipline is meant to prevent — leaks, use-after-free, and out-of-bounds
access — so a slip that review misses still fails a gate before it ships.

### Error Handling

Check every call that can fail. A function that can fail reports it through a
return value — a status code, a count, or a `NULL` pointer — and the caller
inspects that value before proceeding. Ignoring a return value is not permitted;
if a call can fail and the code does not check it, the code is wrong. Public API
entry points guard their pointer arguments against `NULL` before dereferencing
them.

Where the standard library reports failure through `errno`, check it the way the
library specifies: set `errno` to zero before the call when the return value
alone cannot distinguish success from failure, then read it immediately after.
Prefer the checked conversion routines over the silent ones — `strtol` with its
end-pointer and range checks rather than `atoi`, which cannot report a bad input
at all. xboing-c uses `strtol` with error checking for user input and reserves
the unchecked path only for input a prior stage has already validated.

Report a failure through a named status code rather than a bare integer, so both
the compiler and the reader know what a value means. xboing-c defines a status
enum per module — a distinct constant for a null argument, a failed allocation,
a full container, an out-of-range index — and returns those constants instead of
scattering `-1` through the code.

### Header and Translation-Unit Organization

A header declares the interface; the translation unit defines it. Put in the
header only what a caller needs — the public types, the function declarations,
the constants that belong to the contract — and keep everything else in the `.c`
file. The representation of an opaque type is private: xboing-c declares
`typedef struct module module_t;` in the header and defines `struct module { … }`
only in the `.c` file, so no caller can reach a field and no field can change and
break a caller.

Guard every header against double inclusion with an include guard —
`#ifndef MODULE_H` / `#define MODULE_H` / `#endif` — named for the module.
xboing-c uses include guards rather than `#pragma once`. Order includes system
headers first, then project headers, each group alphabetized and separated by a
blank line, so the dependency of a file is legible at a glance.

Give a public function a name prefixed with its module — `ball_system_update`,
`sfx_system_get_enabled` — so its origin is unmistakable at the call site. A
function used only within one translation unit is `static` and needs no prefix.
The narrower the linkage, the smaller the name; the wider the linkage, the more
the name must carry.

### Const-Correctness

Say what a function will not modify. A pointer parameter that the function only
reads is `const`, and xboing-c marks every read-only pointer parameter and every
getter's context argument that way. `const` is a promise the compiler enforces:
it documents intent, it lets the compiler reject an accidental write, and it
lets a caller pass read-only data without a cast.

Never cast away `const` to get work done. A cast that discards `const` is a sign
the interface is wrong — a function is modifying something it declared it would
not — and the fix is to correct the interface, not to defeat the type system.

### Avoiding Undefined Behavior

Undefined behavior is the sharpest edge in C, because the program may appear to
work until a compiler upgrade or an optimization setting changes what "appear to
work" means. Do not rely on it. Do not read uninitialized memory, index past the
end of an array, signed-overflow an integer, dereference `NULL`, or alias a value
through an incompatible pointer type. The strict warning set and the
UndefinedBehaviorSanitizer build below are configured to surface these, and
xboing-c treats a warning from them as an error to fix, not a note to weigh.

Zero-initialize aggregates so no field is ever read before it is written, and
initialize a scalar at the point of declaration where the value is known. The
combination of `calloc`, `-Wuninitialized`, and the sanitizer build closes most
of the window in which uninitialized reads survive to runtime.

### Buffer and Bounds Discipline

Every buffer has a size, and every write to it respects that size. Carry the size
alongside the pointer and bound each copy, format, and index against it; a write
that assumes a buffer is large enough is a buffer overflow waiting for the input
that proves it wrong. Prefer the length-bounded library routines to the
unbounded ones, and compute the bound from the actual buffer rather than a
constant that a later change can leave stale.

xboing-c compiles with `-Wformat=2` and, on GCC, `-Wformat-overflow=2`, which
catch a mismatched format specifier and a format write that cannot fit its
destination. Bounds discipline and these warnings reinforce each other: the
warning flags what static analysis can see, and the sizing discipline covers
what it cannot.

### Minimal, Clear Interfaces

A module exposes the smallest interface that lets a caller do its job, and no
more. Each public function does one thing, and a function that does two things is
two functions. xboing-c keeps functions short and single-purpose and prefers a
pure function — one that computes from its arguments with no side effect —
because a pure function is the easiest kind to reason about and to test. Constants
carry names that state their meaning rather than appearing as bare numbers in an
expression, so the intent of a value survives without a comment.

Comment sparingly and only to explain why. A well-named function and a
well-named constant say what the code does; a comment earns its place only when a
constraint, a workaround, or a surprising interaction is not visible in the code
itself. A comment that restates the code adds a second thing to keep correct and
will rot.

## Build, Toolchain, and Testing

xboing-c is the reference for the C toolchain. It builds with CMake through a
thin `make` wrapper, so `make build`, `make test`, and `make check` work without
memorizing the underlying `cmake` and `ctest` invocations. `make check` runs
every CI gate locally and is the source of truth for whether a change is ready.

### Compiler Warnings

Every project source compiles under a strict warning set with `-Werror`, so a
warning stops the build. xboing-c applies this set to each of its targets:

```text
-Wall -Wextra -Wpedantic
-Wconversion -Wshadow -Wdouble-promotion
-Wformat=2
-Wnull-dereference -Wuninitialized
-Wstrict-prototypes -Wold-style-definition
```

`-Wconversion` and `-Wshadow` catch the silent narrowing conversions and shadowed
variables that hide real bugs; `-Wstrict-prototypes` and `-Wold-style-definition`
hold the code to modern function declarations. A GCC-only flag such as
`-Wformat-overflow=2` is added when the compiler is probed and found to support
it, so the build stays portable across GCC and Clang.

### Sanitizers

A dedicated build compiles with AddressSanitizer and UndefinedBehaviorSanitizer
enabled — `-fsanitize=address,undefined -fno-omit-frame-pointer` — and the full
test suite runs under it. In xboing-c this is the `asan` preset, exposed as
`make asan-test` and included in `make check`. The sanitizers catch at runtime
what the warning set cannot see statically: use-after-free, buffer overflow,
leaks, and undefined-behavior traps. Running the tests under them turns those
faults into test failures rather than field crashes.

### Static Analysis and Formatting

| Tool | Purpose | Command |
|------|---------|---------|
| clang-format | Canonical formatting, checked in CI | `make format-check` (apply with `make format`) |
| clang-tidy | Extended static analysis over the compile database | `make tidy` |
| cppcheck | Static analysis of `src/` and `tests/` | `make cppcheck` |

xboing-c pins its formatting with a `.clang-format` derived from the LLVM style —
four-space indent, Allman braces, a 100-column limit, no short blocks collapsed
onto one line — and CI rejects a diff that does not match it. Its `.clang-tidy`
enables the `bugprone-*`, `performance-*`, and selected `readability-*` checks,
disabling only the specific ones that conflict with a legitimate C idiom, each
disable annotated with the reason. A suppression is always explained, never
silent.

### Testing

Tests are written against the interface and run through `ctest`. xboing-c uses
the CMocka framework, links each test against the module under test, and
registers it so `make test` runs the whole suite. Because the logic modules take
their side effects through injected callbacks, a test drives real game logic
against stubbed sound, score, and rendering, and asserts on the observable state
change — no display and no audio device required. Tests run under the sanitizer
build as well, so a test that passes has also cleared ASan and UBSan.

A module ships with its tests. Untested logic is unfinished, and a change to a
module updates the tests that pin its behavior in the same change.

## Enforcement

C carries its coding rules as `.claude/rules/` files, the same mechanism the
other languages use, loaded by an ancestor walk when an agent touches a matching
file. xboing-c holds the reference set. Its `c-code.md` rule, scoped to
`**/*.c` and `**/*.h`, covers naming, include ordering and guards,
const-correctness, the no-magic-numbers rule, the opaque-context lifecycle,
error handling, function size, comment policy, and the ban on global mutable
state; its `tests.md` rule covers the test conventions. These rules are the C
analog of the Python rules under `.claude/rules/python-*.md`, and a change to C
must satisfy them the way a change to Python must satisfy its own.

C has no OO ratchet. The ratchet that scores object-oriented quality against a
committed baseline is a Python mechanism, described in [python.md](python.md),
and it exists because LLM-generated Python drifts toward procedural code that
only looks object-oriented. C is procedural by design, so there is nothing for
such a ratchet to measure. What holds C to its standard is the combination the
sections above describe: the strict warning set compiled with `-Werror`, the
sanitizer build, the static-analysis and formatting gates, the test suite, and
the `.claude/rules/` files — all run together by `make check` before a change
ships.
