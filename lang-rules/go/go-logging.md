---
paths:
  - "**/*.go"
---

# Go Logging & Telemetry

**Introduced:** 2026-11-22

Implement the language-neutral [Logging policy](https://github.com/punt-labs/punt-kit/blob/main/standards/logging.md)
and [Telemetry policy](https://github.com/punt-labs/punt-kit/blob/main/standards/telemetry.md).
The `go test` gates below are acceptance tests for the shared package and
consuming tools, not runtime tests executed by punt-kit.

## GO-LOG-1: Shared Configuration and Sink Ownership

**Implements:** LOG-1, LOG-4, LOG-5

**Statement**: Use `log/slog` for diagnostics. One shared Punt Labs Go
package owns the durable `slog.Handler` and configuration. Each CLI, MCP server,
hook dispatcher and daemon selects its role and configures the shared handler
at its entry point. Pass a `*slog.Logger` to packages, with a fixed component
attribute added via `Logger.With`. Libraries never call `slog.SetDefault`,
set up sinks in `init`, or write diagnostics directly to standard streams.
Suppress noisy dependency logs at configuration time.

Keep usage measurement out of diagnostics. The durable file is the system of
record; interactive stderr is optional and MCP stdout is transport only.
Do not redirect daemon stderr to a second diagnostic file in the service
manager.

**Gate:** `golangci-lint` (`govet`'s `slog` analyzer checks key/value calls);
`go test` entry-point subprocess tests inspect actual durable records and
verify MCP stdout is transport-only even when stderr is discarded.

## GO-LOG-2: Private, Machine-Scoped Diagnostic Files

**Implements:** LOG-7, LOG-8

**Statement**: Resolve the tool's home with `os.UserHomeDir` or its canonical
home resolver and construct paths with `filepath.Join`. Use
`~/.punt-labs/<tool>/logs/<tool>.log` and backups `<tool>.log.1` through
`<tool>.log.5`. Use the same root for repair, crash and hook-error diagnostics;
keep repo-bound audit and session streams in their separate repo-local zone.
Do not fall back to the checkout on home resolution or permission failure.

Create the logs directory at `0700` and active, backup and lock files at
`0600` from the start. Use `os.OpenFile` with `0600` for creation, not a
public file tightened afterward. Check and tighten existing modes at startup
and on rollover before further writes. Surface startup permission failures
through an independent error path rather than proceeding with an insecure sink.

**Gate:** `go test` with an isolated home and distinct working directories
checks exact paths and modes for new and pre-existing files and directories,
including backups and the lock, and exercises denied permission changes.

## GO-LOG-3: Bounded Rotation Across Processes

**Implements:** LOG-8, LOG-10, LOG-11

**Statement**: Write complete UTF-8 records to an `os.O_APPEND` file.
For a shared file on Unix, use a stable private lock file with
`golang.org/x/sys/unix.Flock` on a filesystem that supports it. Hold an
in-process mutex as well as the process-shared lock across identity and size
checks, rollover and append. Use `os.SameFile` to compare the open descriptor
with the active pathname under lock; reopen the active pathname when the
descriptor is stale or the pathname has been replaced or removed. Do not
rotate or unlink the lock file. Rotate before the next encoded record would
exceed 5,242,880 bytes and keep at most five backups, with the same privacy
and redaction guarantees as the active file.

A single owner receiving records over IPC is also valid; only that process
opens and rotates the file. Use equivalent process-shared coordination or
the single-owner design where `Flock` is unavailable. A mutex, atomic append
alone, or a single-process rotator such as Lumberjack cannot coordinate
multiple writers.

**Gate:** `go test` launches independent CLI, server and hook writer processes
through rollover and checks uniquely tagged records for loss (within the
retained window), corruption and stale-descriptor writes. A retention case
exceeds five rollovers and checks file counts, byte bounds and modes.

## GO-LOG-4: Redact the Complete Record

**Implements:** LOG-2, LOG-6, LOG-14, LOG-15

**Statement**: Emit only metadata, counts and approved content-derived hashes
or correlation IDs; never emit user content or secrets. Do not interpolate
untrusted values raw, even with `fmt.Sprintf` before logging. Use shared
escaping for untrusted attributes such as wire values, provider errors,
subprocess stderr and filenames. Log security decisions at WARNING in the
durable file: auth outcomes, rejected or malformed requests and permission
failures, with safe metadata (e.g., request ID and reason), not rejected
content. Handle write-path permission failures best effort without logging
through the same handler; startup failures must surface.

The shared handler formats the entire record in memory, including attributes
added by `WithAttrs` and `WithGroup`, resolved `slog.LogValuer` values, errors
and stack traces. Mask bare credentials and URL credentials, paths, queries
and fragments in that final record before any file write. A
`slog.HandlerOptions.ReplaceAttr` hook is not a final-record redactor.
Escape C0, DEL, C1, and `U+0085`, `U+2028`, `U+2029`; then append one
physical line terminator. Enforce the 64 KiB reference cap on encoded bytes
including the terminator. Withhold oversized or unsettled records; never
fall back to raw output.

**Gate:** `go test` inspects sink bytes for secrets in messages, nested and
bound attributes, errors and stacks; checks forged lines, Unicode controls,
byte caps, redactor failure and non-recursive sink errors.

## GO-LOG-5: Diagnostic Semantics and Detached Children

**Implements:** LOG-3, LOG-9, LOG-12, LOG-13, LOG-16

**Statement**: Default the durable handler to `slog.LevelInfo`. Format local
time at second precision (`2006-01-02 15:04:05`), a bracketed uppercase level
(render Warn as `[WARNING]`), a component name and a plain-language sentence.
Log decisions, state changes, boundary crosses and outcomes once at the
decision point. Omit no-ops and duplicate outcomes; aggregate loops. Use
DEBUG for transport housekeeping and field dumps, actionable WARNING for
degradation, and ERROR for unexpected failure of the requested operation,
not invalid domain input. Give success and failure outcomes symmetric
coverage at the same level or log neither; a separate unexpected error
diagnostic does not replace an outcome.

For each detached Go child launched via `os/exec` or a service manager, configure
the shared sink at the child's own entry point even with all standard streams
discarded. Record parent spawn intent, child startup, completion and failure
using the same safe correlation ID; a successful `cmd.Start` proves only spawn.

**Gate:** `go test` validates file format and levels and runs detached-child
success and failure cases with no standard streams, checking correlated records.

## GO-TEL-1: Shared OpenTelemetry API

**Implements:** TEL-1, TEL-2

**Statement**: Route usage spans, events and metrics through the shared Go
package wrapping `go.opentelemetry.io/otel` and the OpenTelemetry Go SDK.
Name operations `<tool>.<surface>.<action>` with applicable OTel semantic
conventions. Tool instrumentation calls only the shared API, never imports
exporters or writes telemetry tables, and does not derive usage from logs.
The shared package selects exporters and preserves signal identity, schema
version, timestamps and typed attributes in the SQLite representation.

**Gate:** `go test` checks the import boundary of consuming packages and
exercises spans, events and metrics through the shared API to the local store.

## GO-TEL-2: Typed Schemas and Private Identifiers

**Implements:** TEL-3, TEL-4, TEL-5

**Statement**: Define versioned operation schemas in the shared API using
typed Go structs, validated named enums and explicit units (e.g., a
`time.Duration` converted to the schema's unit). Validate even typed enums
and reject unknown fields or versions, wrong types and arbitrary strings
before enqueueing; drop invalid events without failing the operation. Do
not expose `map[string]any` or raw OTel attribute lists to tool call sites.
Apply the allowlist to span names, events, metrics, resources and status;
never pass raw errors to `Span.RecordError` or enable auto-instrumentation
that bypasses validation. Only schema-declared lengths or derived hashes
may represent content.

Generate a per-install secret with `crypto/rand` and use a keyed SHA-256
digest (`crypto/hmac`) in the shared API for identifiers. Store the secret at
`0600` under `~/.punt-labs/` (e.g., `telemetry.salt`). Publish a complete
private file atomically without overwriting a concurrent installer's salt;
all processes use the winning file. Never put a raw identifier or the
salt in the queue, store or network payload.

**Gate:** `go test` checks valid and rejected attributes, unknown versions,
content exclusion across OTel signals, concurrent salt creation, permissions,
same-install consistency and cross-install separation.

## GO-TEL-3: Private SQLite and Retention

**Implements:** TEL-6, TEL-7

**Statement**: Default to local capture. Use `database/sql` with the pure-Go
`modernc.org/sqlite` driver in the shared exporter. Store telemetry at
`~/.punt-labs/<tool>/telemetry.db`, separate from logs. Secure the tool
directory at `0700` before opening SQLite. Pre-create the database with
`os.OpenFile` using `O_CREATE|O_EXCL` and `0600`; validate and tighten
existing files before use. Ensure the driver's SQLite VFS creates journal,
WAL and SHM sidecars at `0600` and tighten pre-existing sidecars. Do not
open insecurely and fix modes afterward. Bound SQLite lock waits and use
transactions so concurrent processes can share the store.

Retain 90 days by default; accept only finite, positive retention periods.
Prune at startup and periodically even when no new events arrive. Reclaim
expired storage with SQLite vacuuming or incremental auto-vacuum, and
checkpoint and bound WAL growth if WAL is enabled. Run maintenance off the
operation's path.

**Gate:** `go test` uses real SQLite files in an isolated home and verifies
initial and existing modes, sidecars, concurrent writers, startup and idle
pruning, and reclamation after expiry.

## GO-TEL-4: Exporter-Only Migration and Consent

**Implements:** TEL-2, TEL-8, TEL-9

**Statement**: Keep SQLite and the Go SDK OTLP/HTTP exporters inside the
shared package. Enable network export only by explicit opt-in; selecting a
backend must require only shared configuration, not different call sites,
schemas or tool imports. Apply identical privacy and schema validation
regardless of exporter. Treat `PUNT_TELEMETRY=off`, the tool's config switch
and `<TOOL>_TELEMETRY=off` as independent vetoes. Resolve them before
initializing the store, exporter or workers; a disabled API is a no-op.

**Gate:** `go test` runs the same instrumentation with SQLite and a test OTLP
HTTP receiver via configuration only. Assert no network export without
consent and no store, worker or exporter with any off switch set.

## GO-TEL-5: Isolate Telemetry Failures

**Implements:** TEL-10

**Statement**: Send validated observations over a bounded Go channel using
`select` with `default`; drop on saturation rather than applying backpressure.
Bound exporter I/O, including SQLite contention, and SDK flush and shutdown
with context deadlines. Keep exporter initialization and maintenance failure
off the operation's result path; do not wait on network or storage from the
operation. Report errors through rate-limited metadata-only diagnostic logs,
never through telemetry itself.

**Gate:** `go test` injects invalid events, a saturated queue, an unwritable or
full store and a stalled exporter; checks unchanged operation outcomes,
bounded shutdown and rate-limited diagnostics without recursion.

## Policy Traceability

`make check-standards` verifies citations and required language coverage,
not Go runtime behavior. Each rule above names its implementation gate.

| Policy clauses | Go rules |
|----------------|----------|
| LOG-1, LOG-4, LOG-5 | GO-LOG-1 |
| LOG-7, LOG-8 | GO-LOG-2 |
| LOG-8, LOG-10, LOG-11 | GO-LOG-3 |
| LOG-2, LOG-6, LOG-14, LOG-15 | GO-LOG-4 |
| LOG-3, LOG-9, LOG-12, LOG-13, LOG-16 | GO-LOG-5 |
| TEL-1, TEL-2 | GO-TEL-1 |
| TEL-3, TEL-4, TEL-5 | GO-TEL-2 |
| TEL-6, TEL-7 | GO-TEL-3 |
| TEL-2, TEL-8, TEL-9 | GO-TEL-4 |
| TEL-10 | GO-TEL-5 |
