---
paths:
  - "**/*.st"
---

# Pharo Logging & Telemetry

**Introduced:** 2026-11-22

Implement the language-neutral [Logging policy](https://github.com/punt-labs/punt-kit/blob/main/standards/logging.md)
and [Telemetry policy](https://github.com/punt-labs/punt-kit/blob/main/standards/telemetry.md)
in Pharo images. Diagnostics use Beacon, which ships in the Pharo image;
telemetry uses the OpenTelemetry API from `opentelemetry-pharo` behind a shared
facade. The SUnit gates below are acceptance tests for the shared package and
consuming projects, not tests executed by punt-kit.

## PHARO-LOG-1: Beacon Signals and Shared Configuration

**Implements:** LOG-1, LOG-4, LOG-5

**Statement**: Emit diagnostics as typed `BeaconSignal` subclasses whose
instance variables hold the record's fields. One shared Punt Labs Pharo
package owns the durable `SignalLogger`, its configuration and the signal
base class. Each image entry point (headless startup script, server start,
CLI command, `SessionManager` startup handler) selects its role and starts
the shared logger. Library packages only emit signals: they never start a
`SignalLogger`, subscribe to `Beacon instance` or `ZnLogEvent announcer`,
or configure sinks from a class-side `initialize` or a baseline post-load
action.

Keep usage measurement out of diagnostics. The durable file is the system
of record. `TranscriptLogger`, `MemoryLogger` and `CircularMemoryLogger` are
for interactive and test use only, and `Transcript show:`, `Stdio stdout`
and `Stdio stderr` are never a diagnostic sink. An image serving MCP over
stdio keeps stdout for transport.

**Gate:** SUnit tests in the consuming project check that its production
packages reference no `SignalLogger` subclass, `Transcript`, `Stdio` or
`ZnLogEvent announcer` outside the entry point, and that starting each
entry point headless writes durable records with stdout transport-only.

## PHARO-LOG-2: One Logger per Image Session

**Implements:** LOG-4, LOG-5, LOG-11

**Statement**: The shared package holds the image's durable logger in a
class-side variable. Starting it is idempotent and leaves one subscription
per announcer; stopping it unsubscribes every subscription. A tool, window
or server that bridges an announcer such as `ZnLogEvent announcer` owns
that subscription and stops it when it closes. Never create a logger per
request, per window or per test without stopping it.

An image snapshot preserves running loggers, open file handles, cached
paths and process IDs. Register the shared package with `SessionManager`
so that on image startup it discards handles inherited from the snapshot,
re-resolves the home directory, rechecks modes and reopens the active file
before the first write, and on shutdown flushes and closes the file.

**Gate:** SUnit tests start the logger repeatedly and check that exactly one
running instance and one subscription per announcer exist, that stop leaves
none, and that a simulated session startup reopens the file at the current
path.

## PHARO-LOG-3: Private, Machine-Scoped Diagnostic Files

**Implements:** LOG-7, LOG-8

**Statement**: Resolve the tool's home from `FileLocator home` through the
shared package, never from `FileSystem workingDirectory`, the image
directory or the repository. Use `~/.punt-labs/<tool>/logs/<tool>.log` with
backups `<tool>.log.1` through `<tool>.log.5`, and the same root for repair,
crash and hook-error diagnostics. Do not fall back to another location on
a home resolution or permission failure.

`FileReference` write streams and `File open:writable:` create files with
the process umask, and `File class>>file:posixPermissions:` changes the
mode afterward, so neither may create a log file. Create the logs directory
with `mkdir(2)` at `0700` and active, backup and lock files with `open(2)`
using `O_CREAT|O_EXCL` and mode `0600`, through uFFI bindings in the shared
package. Use `file:posixPermissions:` only to tighten existing files and
directories at startup and on rollover, before further writes. Surface a
startup permission failure to the entry point rather than writing to an
insecure sink.

**Gate:** SUnit tests with an isolated home and distinct working directories
check exact paths and modes for new and pre-existing files and directories,
including backups and the lock, and exercise a denied permission change.

## PHARO-LOG-4: Bounded Rotation Across Images

**Implements:** LOG-8, LOG-10, LOG-11

**Statement**: More than one image can write the same file (for example, a
development image and headless agents on other `EVAL_PORT`s). A `Mutex`
serializes Pharo processes within one image only. Use it, plus `flock(2)`
on a stable private lock file through uFFI, across the identity and size
checks, rollover and append. Request the lock with `LOCK_NB` and retry
after a `Delay`. A blocking FFI call stalls every Pharo process in the
image. Compare the open descriptor's inode with the active path's
`FileReference>>inode` under the lock, and reopen when the descriptor is
stale or the path was replaced or removed. Do not rotate or unlink the lock
file.

Write each complete UTF-8 record with `O_APPEND`. Rotate before the next
encoded record would exceed 5,242,880 bytes, keeping at most five backups
with the same privacy and redaction guarantees as the active file. A single
owner image receiving records from other images is also valid; only that
image opens and rotates the file.

**Gate:** An SUnit harness launches at least two independent headless images
writing uniquely tagged records through rollover and checks for loss (within
the retained window), corruption and stale-descriptor writes. A retention
case exceeds five rollovers and checks file counts, byte bounds and modes.

## PHARO-LOG-5: Redact the Complete Record

**Implements:** LOG-2, LOG-6, LOG-14, LOG-15

**Statement**: Signal instance variables carry metadata, counts and approved
content-derived hashes or correlation IDs, never user content or secrets.
Do not send `emit` to an arbitrary object: Beacon wraps it in a
`WrapperSignal` and records its `printString`, which can carry content. Do
not log a raw `printString`, exception `messageText` or `description`, or a
`signalerContext` stack, since they include receivers, arguments and URLs.
For an error, log its class and safe fields. Escape untrusted values such as
wire data, provider errors, subprocess output and filenames with the shared
escaper.

The shared logger renders the whole record in memory, including the signal's
`printOneLineContentsOn:` output and any error detail. A final-record
redactor masks bare credentials and URL credentials, paths, queries and
fragments. It escapes C0, DEL, C1, and `U+0085`, `U+2028`, `U+2029`, then
appends one line feed, and caps the UTF-8 encoded record at 64 KiB including
the terminator. Withhold a record that is oversized or whose redaction does
not settle; never fall back to raw output.

Log security decisions at WARNING in the durable file, such as rejected eval
tokens, malformed requests and permission failures, with safe metadata such
as the request ID and reason, never the rejected content. A failure inside the
logger's write path is handled there on a best-effort basis, never by
emitting another signal, which would re-enter the logger.

**Gate:** SUnit tests inspect sink bytes for secrets in fields, wrapped
objects, error text and stacks, and check forged lines, Unicode controls,
byte caps, redactor failure and non-recursive sink errors.

## PHARO-LOG-6: Levels, Format and Background Work

**Implements:** LOG-3, LOG-9, LOG-12, LOG-13, LOG-16

**Statement**: Beacon signals carry no level. Each shared signal class
declares one of the shared levels, and the durable logger records INFO and
above by default. Render each record from the signal's `timestamp` in local
time at second precision (`2026-03-08 10:37:41`), followed by a bracketed
uppercase level, the component name and a plain-language sentence. Log
decisions, state changes, boundary crosses and outcomes once, at the decision
point. Omit no-ops and aggregate loops. Bridge Zinc events by type: put
transport traffic and connection housekeeping at DEBUG, and never record a
`ZnLogEvent`'s `printString`. Give success and failure outcomes symmetric
coverage at the same level, or log neither.

A Pharo `Process` forked for work that outlives the request, and each child
image or subprocess, is detached work. Wrap a forked block's body in an
error handler that records its failure. An unhandled error in a headless
background process leaves no durable trace. A child image starts the shared
logger at its own entry point even with all standard streams discarded.
Record spawn intent, startup, completion and failure with the same safe
correlation ID. A successful `fork` or spawn proves only that it started.

**Gate:** SUnit tests validate file format and levels and run forked-process
and child-image success and failure cases with no standard streams,
checking the correlated records.

## PHARO-TEL-1: Shared OpenTelemetry API

**Implements:** TEL-1, TEL-2

**Statement**: Route usage spans, events and metrics through the shared
Pharo facade over the `opentelemetry-pharo` API. Name operations
`<tool>.<surface>.<action>` with applicable OTel semantic conventions. Tool
packages call only the facade. They never reference `OT*` exporter,
processor or provider classes, never write telemetry tables, and never
derive usage from diagnostics, for example by attaching
`OTBeaconSignalLogger` to Beacon. The facade selects the exporter and
preserves signal identity, schema version, timestamps and typed attributes
in the SQLite representation.

**Gate:** SUnit tests check that consuming packages reference no `OT*` class
outside the facade, and exercise spans, events and metrics through the
facade to the local store.

## PHARO-TEL-2: Typed Schemas and Private Identifiers

**Implements:** TEL-3, TEL-4, TEL-5

**Statement**: Define each operation's versioned schema as a class with typed
instance variables, closed `Symbol` enums and explicit units. Validate
attributes before enqueueing, reject unknown versions, wrong classes and
arbitrary strings, and drop an invalid event without failing the operation.
Do not pass `Dictionary` attribute bags or raw OTel attributes from tool
call sites. Apply the allowlist to span names, events, metrics, resources
and status. Never record an exception's text or stack on a span, and never
enable method-proxy or other automatic instrumentation that bypasses
validation. Only schema-declared lengths or derived hashes may represent
content.

Generate the per-install salt from the operating system's cryptographic
generator (`/dev/urandom` on Unix), never from `Random`, which is a PCG
generator and not cryptographic. Derive identifiers with HMAC-SHA256
(`SHA256 new hmac`) in the facade. Write the salt privately to
`~/.punt-labs/telemetry.salt` at `0600` (see PHARO-LOG-3) and publish it
atomically without overwriting a concurrent installer's file. All images
use the winning file. Read the salt from disk at session startup and clear
it on shutdown so that an image snapshot never carries it. Never put a raw
identifier or the salt in the queue, store or network payload.

**Gate:** SUnit tests check valid and rejected attributes, unknown versions,
content exclusion across OTel signals, concurrent salt creation, modes,
salt absence from a saved image, same-install consistency and
cross-install separation.

## PHARO-TEL-3: Private SQLite and Retention

**Implements:** TEL-6, TEL-7

**Statement**: Default to local capture through a SQLite exporter in the
shared package, built on the Pharo-SQLite3 binding. Store telemetry at
`~/.punt-labs/<tool>/telemetry.db`, separate from logs. Secure the tool
directory at `0700` and pre-create the database with `O_CREAT|O_EXCL` at
`0600` (see PHARO-LOG-3) before SQLite opens it. Validate and tighten
existing database, journal, WAL and SHM files; never open insecurely and fix
modes afterward. Bound SQLite busy waits and use transactions so that
concurrent images can share the store. SQLite calls run through FFI and can
stall every Pharo process in the image, so keep them off the operation's
process and short.

Retain 90 days by default and accept only finite, positive retention periods.
Prune at startup and periodically from a background process, even when no
new events arrive. Reclaim expired storage with vacuuming or incremental
auto-vacuum, and checkpoint and bound WAL growth if WAL is enabled.

**Gate:** SUnit tests use real SQLite files in an isolated home and verify
initial and existing modes, sidecars, concurrent images, startup and idle
pruning, and reclamation after expiry.

## PHARO-TEL-4: Exporter-Only Migration and Consent

**Implements:** TEL-2, TEL-8, TEL-9

**Statement**: Keep the SQLite exporter and the `opentelemetry-pharo` OTLP/HTTP
exporter inside the shared package. Enable network export only by explicit
opt-in. Selecting a backend requires only shared configuration, not different
call sites, schemas or tool package dependencies. Apply identical privacy
and schema validation regardless of exporter. Treat `PUNT_TELEMETRY=off`,
the tool's config switch and `<TOOL>_TELEMETRY=off` as independent vetoes.
Read them through `OSEnvironment current` at every image startup, because a
resumed snapshot keeps the previous session's state. Resolve them before
opening the store, configuring an exporter or forking a worker process. A
disabled facade is a no-op.

**Gate:** SUnit tests run the same instrumentation with SQLite and a test
OTLP HTTP receiver through configuration only. They assert no network export
without consent, and no store, exporter or worker process with any off
switch set, including after a simulated image restart.

## PHARO-TEL-5: Isolate Telemetry Failures

**Implements:** TEL-10

**Statement**: Beacon announcements and `Announcer` subscribers run
synchronously in the emitting process, so telemetry never exports from a
subscriber on the operation's path. Hand validated observations to a worker
process through a queue with a fixed capacity enforced by the facade, and
drop on saturation. `SharedQueue` and `WaitfreeQueue` are unbounded. Run
the worker below user priority, handle every exporter error inside it, and
bound exporter I/O, SQLite contention and the shutdown flush registered with
`SessionManager`. Report errors through rate-limited, metadata-only
diagnostic signals, never through telemetry itself.

**Gate:** SUnit tests inject invalid events, a saturated queue, an unwritable
or full store and a stalled exporter. They check that operation outcomes are
unchanged, that the worker survives, that shutdown is bounded and that
diagnostics are rate-limited without recursion.

## Policy Traceability

`make check-standards` verifies citations and required language coverage,
not Pharo runtime behavior. Each rule above names its implementation gate.

| Policy clauses | Pharo rules |
|----------------|-------------|
| LOG-1, LOG-4, LOG-5 | PHARO-LOG-1 |
| LOG-4, LOG-5, LOG-11 | PHARO-LOG-2 |
| LOG-7, LOG-8 | PHARO-LOG-3 |
| LOG-8, LOG-10, LOG-11 | PHARO-LOG-4 |
| LOG-2, LOG-6, LOG-14, LOG-15 | PHARO-LOG-5 |
| LOG-3, LOG-9, LOG-12, LOG-13, LOG-16 | PHARO-LOG-6 |
| TEL-1, TEL-2 | PHARO-TEL-1 |
| TEL-3, TEL-4, TEL-5 | PHARO-TEL-2 |
| TEL-6, TEL-7 | PHARO-TEL-3 |
| TEL-2, TEL-8, TEL-9 | PHARO-TEL-4 |
| TEL-10 | PHARO-TEL-5 |
