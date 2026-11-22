# Telemetry Standards

**Introduced:** 2026-11-19 · **Updated:** 2026-11-19

Language-neutral usage capture across Punt Labs tools. See the
[Python](../lang-rules/python/python-logging.md) and
[Go](../lang-rules/go/go-logging.md) implementation rules.

## TEL-1: Separate Usage Capture

**Applies to:** python, go

Telemetry answers which operations are used, how often, and with what latency
and outcome. [Logs](logging.md) are
diagnostics; telemetry is a separate pipeline, schema and store, not parsed logs.

## TEL-2: Instrumentation and Exporter Independence

**Applies to:** python, go

Tools instrument only through a shared observation API wrapping the
**OpenTelemetry API** for spans, events and metrics. Tools MUST NOT import
exporters or write telemetry tables directly. Use names `<tool>.<surface>.<action>` (for example,
`quarry.cli.find`), following OTel semantic conventions where one exists.

Exporter selection belongs to shared configuration. Switching from the local
exporter to OTLP/HTTP MUST require no re-instrumentation, new call sites or
tool-level exporter imports. The local exporter preserves the OTel signal
identity, schema version, timestamps and typed attributes.

## TEL-3: Versioned Schemas

**Applies to:** python, go

Every event type MUST declare a versioned schema. Attributes are an allowlist
of typed values: closed enums, booleans, integers, durations, counts and sizes.
Units and allowed enum values are part of the schema; unknown attributes,
wrong types and unknown schema versions are rejected at the API boundary,
before enqueueing. Rejection drops the event, never fails the operation.

## TEL-4: Privacy Boundary

**Applies to:** python, go

Free text and content — prompts, queries, paths, document or message bodies,
user names and emails — are forbidden, including in span names, status text,
resource attributes and automatically recorded exceptions. Tools MUST NOT
enable automatic instrumentation that bypasses this boundary. Content may
appear only as a length or a salted hash in a schema-declared derived field.
Do not accept arbitrary strings disguised as enums or hashes.

## TEL-5: Salted Identifiers

**Applies to:** python, go

Identifiers MUST be hashed with a per-install random salt stored at mode
`0600` under `~/.punt-labs/` (for example, `~/.punt-labs/telemetry.salt`).
The shared API owns derivation; raw identifiers and the salt never enter the
queue, database or network payload. Create the salt privately and atomically;
never use a public or cross-install salt.

## TEL-6: Private Local Store

**Applies to:** python, go

Local capture is **on by default**. The default exporter writes SQLite at
`~/.punt-labs/<tool>/telemetry.db`, separate from diagnostic log files.

Directory mode MUST be `0700`; the database and SQLite sidecars MUST be
`0600`. Secure the directory first, atomically pre-create the database
privately before SQLite opens it, and tighten existing files. An
open-then-tighten window is forbidden.

## TEL-7: Bounded Retention

**Applies to:** python, go

Storage MUST be retention-bounded: default **90 days**. Prune periodically
in long-lived processes as well as at startup; reclaim expired storage so the
database does not grow indefinitely. Retention is configurable, never unlimited.

## TEL-8: Export Consent

**Applies to:** python, go

An OTLP/HTTP exporter is a configuration change only. Network export MUST be
explicit and opt-in; local capture does not imply consent to send. The same
schema and privacy checks apply to every exporter.

## TEL-9: Off Switches

**Applies to:** python, go

`PUNT_TELEMETRY=off` disables all capture and export globally and overrides
per-tool settings. Each tool MUST also expose a config switch and a
`<TOOL>_TELEMETRY=off` environment switch. Any off switch wins. Disabled
telemetry opens no store and starts no exporter or background worker.

## TEL-10: Failure Isolation

**Applies to:** python, go

Telemetry MUST never block or fail a tool. Use a bounded, non-blocking queue;
drop events on saturation. Bound exporter I/O and shutdown flush time. Swallow
exporter errors and report them through diagnostic logging (rate-limited,
metadata only), never through the failing telemetry pipeline. Invalid events,
an unwritable database, a full disk or an unavailable backend cannot change
the operation's result.
