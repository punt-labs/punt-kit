# Pharo Standards

Standards for all Punt Labs Pharo and Smalltalk projects. This document is the
canonical reference — individual project CLAUDE.md files should reference it, not
duplicate it.

Current Pharo projects: anthropic-sdk-pharo, lux-pharo.

Pharo is object-oriented, so unlike C and Go it answers to the shared stance in
[oo.md](oo.md). It answers to it more directly than any other language we write,
because Pharo is the reference model that document already points to: everything
is an object and every computation is a message send, so there is nowhere to hide
a procedure that only looks like an object. This document does not restate that
philosophy. It shows how the stance lands in Smalltalk idioms, how an image-based
project is organized and loaded, and — the part that differs most from the other
languages — how its quality is enforced from inside the image rather than by an
external rules file.

---

## Where Pharo Fits the Architecture

The [Projection Model](architecture.md#the-projection-model-canonical) describes a
Punt Labs product as one engine fronted by thin library, CLI, MCP, and REST
clients. A Pharo project usually enters that picture at one of two positions, and
our two projects show one each. Read the invariants in architecture.md before
deciding how they apply, because much of what they govern assumes a service that
grows client surfaces, and a Pharo library or a live image occupies the model
differently.

anthropic-sdk-pharo is a **client library**. Its engine is the remote Anthropic
Messages API, which it does not own; the SDK is the library-import surface a Pharo
caller uses to reach that engine. `ClaudeClient` is the single front door — it
holds the authentication and connection configuration and constructs a fresh
`ZnClient` per request — and every other class in the SDK is reached through the
work it does. The SDK has no CLI, MCP, or REST surface of its own, because it
fronts someone else's engine rather than exposing one. What still governs it is
the internal-structure half of the model: one implementation of each capability,
never duplicated, and a clean boundary between the core that holds the logic and
the thin edge that adapts it. The Metacello baseline lays those layers out
explicitly — the wire types in `Claude-Messaging-Types`, the error hierarchy and
streaming above them, the API client above those — with the dependency arrow
pointing inward from the client to the types, never the reverse.

lux-pharo is an **engine that lives in the image**. A Pharo image is a live object
memory: the classes, the objects, and their state all sit in RAM, and there is no
separate program text that the image merely runs. lux-pharo puts an engine's
authority in that memory — `BootstrapEvalServer` is the front door onto it, an
HTTP endpoint built on `ZnReadEvalPrintDelegate`, and Morphic is the render
surface the way the Display is for lux itself. It hosts a headless agent runtime,
`PharoAgent`, inside the same image. A Pharo program that wants to reach the lux
engine proper is a client of it over lux's socket, exactly like any other lux
client; lux-pharo is the case where the image is itself the engine, standing up
its own authority and its own rendering in one process. The point in both cases is
to apply the model as it fits the shape of the project, not to manufacture
surfaces the project has no caller for.

## The Object-Oriented Stance in Pharo

The six principles are stated once, for every language, in [oo.md](oo.md):
behavior lives with its data, an object is told rather than asked for its parts,
dispatch is on the object instead of a conditional, objects are composed rather
than derived through a deep hierarchy, a family is defined by protocol rather than
a base class, and objects are kept small enough that their illegal states cannot
be represented. This section does not re-argue them. It shows the Smalltalk idiom
each one becomes, using the two projects as proof.

### Everything Is a Message Send

Pharo has no syntax that is not a message. `3 + 4` sends `+` to an integer;
`aBoolean ifTrue: [ … ] ifFalse: [ … ]` sends a message to a boolean and lets the
receiver choose the branch; a class is created by sending `subclass:…` to its
superclass. Because control flow is message sending, the object always has the
opening to decide, and idiomatic Pharo takes it. In lux-pharo, `PharoAgent`
selects its next step by sending messages to collections rather than by walking a
loop with an index — `contentBlocks do: [ :block | … ]`, `blocks select: [ :b |
… ]`, `models detect: [ :m | … ] ifNone: [ … ]`. The message-send discipline is
not an aesthetic; it is what keeps a decision on the object that owns the data
instead of in a caller reaching over the fence.

### Behavior Lives With Its Data

An object that must serialize itself implements the serialization; an object that
must print itself implements `printOn:`. In anthropic-sdk-pharo, `ClaudeTextBlock`
carries `asJson` as an instance method and `fromJson:` as a class method, so the
block turns itself into the wire shape and reconstructs itself from it — the
knowledge of the block's JSON lives on the block. `ClaudeClient` implements
`printOn:` to write `ClaudeClient(https://api.anthropic.com)`, so the object
describes itself rather than leaving a caller to assemble a description from its
slots. This is the exact correction oo.md draws from Lux, where each element was a
dataclass and a module-level `_kind_to_dict` reached in from outside; the Pharo
form never separates the two, because there is nowhere to put the loose function.

### Polymorphism Replaces the Type Switch

anthropic-sdk-pharo renders many kinds of content block — text, tool use, tool
result, thinking, image, and more. Each kind is its own class under
`ClaudeContentBlock`, and each answers the same messages in its own way:
`asJson` serializes, `applyDelta:` folds in a streaming delta, `isTextBlock` and
its siblings answer the polymorphic predicate. Adding a block kind is writing one
new subclass that answers those messages, not editing an `if`-ladder threaded
through the codebase. There is one place a wire tag is read: the class-side
`fromJson:` consults a `TypeRegistry` that maps the JSON `type` string to the
right subclass, because a block arrives from the network as an untyped dictionary
and something has to choose the class at the boundary. That single lookup at the
edge is the price of a foreign wire format; once the object exists, every further
decision is a message to it, and an unknown tag degrades to a raw block that
preserves its JSON rather than crashing.

### Composition and Many Small Objects

`ClaudeMessageRequest` in anthropic-sdk-pharo is assembled from small value
objects rather than inflated into one class — sampling parameters, tool
parameters, thinking parameters, and per-request options each live in their own
object and are composed into the request, and the request delegates to them. The
builder is written with cascades ending in `yourself`, so a caller configures a
request by sending it a series of messages and receives the configured object
back. `ClaudeClient` holds no connection pool; it composes a fresh `ZnClient` for
each request and delegates the transport to it. The wire-types package holds more
than fifty small classes, one per API concept, which is the many-small-classes
design oo.md describes — the right number of classes for a working design is
larger than first instinct suggests, and the SDK reaches it.

### Families Share by Protocol

In Pharo a family is defined by the messages its members answer. Any object that
implements `do:` can be iterated, whether or not it descends from a collection
class, and the collection protocol — `collect:`, `select:`, `reject:`,
`detect:ifNone:`, `inject:into:` — is a contract about behavior, not ancestry.
lux-pharo relies on this: `PharoAgent` treats API content as ordinary collections
and speaks the collection protocol to them without caring what concrete class
carries the data. Where anthropic-sdk-pharo does use a base class,
`ClaudeContentBlock`, it does so for the reason oo.md reserves inheritance —
genuinely shared implementation that every member needs, here the raw-JSON
fallback that keeps an unrecognized block intact — and not merely to reuse code.

### Class-Side, Instance-Side, Packages, and Protocols

Pharo splits behavior between the instance side and the class side, and the split
is a design decision. Instance-creation and factory messages live on the class
side — `ClaudeTextBlock text:`, `ClaudeClient apiKey:` — while the behavior of a
constructed object lives on the instance side. Methods are short and grouped into
protocols that name their role; anthropic-sdk-pharo files its block methods under
`json`, `accessing`, `streaming`, and `testing`, so the System Browser reads as an
outline of responsibilities. Packages carry a consistent prefix and a layered
name — `Claude-Messaging-Types`, `Claude-Messaging-Client` in anthropic-sdk-pharo;
`Claude-Bootstrap-Server`, `Claude-Bootstrap-Agent` in lux-pharo — so the layer a
class belongs to is legible from its package. A class earns its keep only with a
runnable example in its comment: anthropic-sdk-pharo writes each class comment with
an evaluable expression and its `>>>` result, and a class without one is treated as
incomplete.

## Image-Based Development

A Pharo project is developed in a live image but is not stored as one. The image
is a convenience that can be thrown away and rebuilt; the source on disk is what a
project is. This section covers how the two stay in agreement.

### Source on Disk: Tonel and Chunk Format

Two on-disk formats appear across our projects. anthropic-sdk-pharo uses **Tonel**,
the modern format: one directory per package containing a `package.st` and one
`.class.st` file per class, which reads and diffs cleanly under git.
lux-pharo uses the older **chunk format**, a single `.st` file per class written in
bang-separated method chunks and loaded with `CodeImporter evaluateFileNamed:`.
Chunk format requires carriage-return line endings — a linefeed produces a "Method
source contains linefeeds" warning — so lux-pharo pins `eol=cr` for `*.st` files in
`.gitattributes` and converts on write. Prefer Tonel for new work; it is the format
the tools and the baseline machinery expect.

### Loading Into a Fresh Image

anthropic-sdk-pharo declares its structure in a Metacello baseline,
`BaselineOfClaudeSDK`, which lists every package and the dependencies among them.
A fresh image loads the whole project with one expression:

```smalltalk
Metacello new
    baseline: 'ClaudeSDK';
    repository: 'github://punt-labs/anthropic-sdk-pharo:main/src';
    load.
```

The baseline is the record of what loads and in what order — types before the
error hierarchy, the client above both, the tool definitions after the client
whose classes they extend. The `<baseline>` pragma and the `projectClass` method
must sit on the instance side, and anthropic-sdk-pharo guards this with a
`check-baseline` target that performs a cold Metacello load in a throwaway image
where the SDK is not already present, so a broken baseline cannot pass unnoticed.
`make rebuild` in both projects tears the image down and rebuilds it from disk,
which is the standing proof that the source is self-contained: if a rebuilt image
is missing something, the source was incomplete.

### Test-Driven Development in the Image

Tests are SUnit `TestCase` subclasses, developed red-to-green in the live image
where a failing test can be inspected and fixed in place. anthropic-sdk-pharo runs
a single class's tests with `ClaudeTextOutputFormatTest buildSuite run` and the
whole SDK suite with `ClaudeMessagingTestSuite suite run`; a `make test` target
drives the suite through the eval server from the command line. Run only the
project's own suites — never the full image test suite. A class ships with its
tests, and the class comment's runnable example is a second, lighter test that a
reader can evaluate to see the class work.

### Version Control Outside the Image

Source is version-controlled outside the image through Iceberg, the git bridge
inside Pharo, which exports the in-image code to the on-disk Tonel packages that
git tracks. The risk this creates is drift: a method edited in the image but not
written to disk, or a git operation that moves `HEAD` while the image's working
copy stays attached to a stale commit. anthropic-sdk-pharo closes that gap with
tooling. `make drift` compares the selectors in the image against the selectors in
the on-disk Tonel and fails on any difference; `make sync-ref` reattaches the
Iceberg working copy to the current `HEAD`; and `make check` requires the Iceberg
working copy to be clean before it passes. The rule underneath all three is that
the image and the source must agree, and the source is the authority.

## Build and Toolchain

Both projects drive the image through a `make` wrapper so the underlying Pharo
invocations need not be memorized. The lifecycle is consistent across them.

| Target | What it does |
|--------|--------------|
| `make setup` | Download the Pharo VM and image, load every package |
| `make start` | Launch the image with the eval server on its port |
| `make stop` | Save and stop the running image |
| `make filein` | Reload the on-disk source into the running image |
| `make rebuild` | Tear down and rebuild a fresh image from disk |
| `make test` | Run the project's SUnit suites |
| `make lint` | Run the in-image linter over the project's classes |
| `make check` | The full gate: packages loaded, lint clean, image and disk in agreement |

The eval server is how a headless image is driven from the shell: a program POSTs
Smalltalk to an HTTP endpoint and reads the result. anthropic-sdk-pharo serves it
with Postern, and lux-pharo with `BootstrapEvalServer`. Development from the
command line — filing in source, running a suite, linting — flows through that
endpoint into the live image.

## Enforcement

Here is where Pharo differs most from the other languages we write. C, Go, and
Python carry their coding rules as `.claude/rules/` files loaded by an ancestor
walk when an agent touches a matching file. **Pharo carries no such file, by
design.** Its quality is enforced by the linting engine that lives inside the
Pharo image — the Code Critics engine, reached through `ReCriticEngine` and
surfaced in the Quality Assistant panel, running the Renraku and SmallLint rule
set against the code in place. The rules operate on live compiled methods and
class definitions, not on text, so they see things a file-based linter cannot:
that an instance variable is declared but never read, that a class has an
excessive number of methods, that a message send is directed at a superclass the
sender does not descend from. `make lint` runs the full rule set — both the
per-method rules and the class-level and package-level rules — and a project is
lint-clean only when it reports zero findings. Where a finding is a considered
exception, the declaration lives in the image too: a `PackageManifest` class holds
the false-positive declarations with their justification, as
`ManifestClaudeMessagingTypes` does in anthropic-sdk-pharo for the two value
objects whose slot counts track the API surface one-to-one.

Do not add a `.claude/rules/pharo-*.md` file to close a perceived gap. There is no
gap. The linter already lives where the code lives, and it is the authority. An
external rules file would be a second, weaker copy of a rule set the image checks
directly, and it would drift from the version the tools actually run.

There is no OO ratchet for Pharo either. The ratchet that scores object-oriented
quality against a committed baseline is a Python mechanism, described in
[python.md](python.md), and it exists because model-generated Python drifts toward
procedural code that only looks object-oriented. Pharo cannot drift that way:
there is no primitive outside the object model, no free function to scatter
behavior into, no record to pull apart with a procedure — the reasons oo.md names
Pharo its reference model. The discipline is native to the language, so there is
nothing for a ratchet to measure. What holds Pharo to the standard is the
combination the sections above describe: the in-image linter run by `make lint`,
the SUnit suites, the baseline and drift gates that keep the image and the source
in agreement, and the `make check` target that runs them together before a change
ships.
