# Telemetry Standards

**Introduced:** 2026-11-19

Usage capture across Punt Labs tools. Telemetry answers which operations are
used, how often, and with what latency and outcome. [Logs](logging.md) are
diagnostics; telemetry is a separate pipeline, schema and store, not parsed logs.

## Instrumentation

Tools instrument only through `punt_observe.telemetry` in the shared package
(provisionally `punt-observe`). It wraps the **OpenTelemetry API** for spans,
events and metrics. Tools MUST NOT import exporters or write telemetry tables
directly. Use names `<tool>.<surface>.<action>` (for example,
`quarry.cli.find`), following OTel semantic conventions where one exists.

Exporter selection belongs to shared configuration. Switching from the local
exporter to OTLP/HTTP MUST require no re-instrumentation, new call sites or
tool-level exporter imports. The local exporter preserves the OTel signal
identity, schema version, timestamps and typed attributes.

## Schemas and Privacy

Every event type MUST declare a versioned schema. Attributes are an allowlist
of typed values: closed enums, booleans, integers, durations, counts and sizes.
Units and allowed enum values are part of the schema; unknown attributes,
wrong types and unknown schema versions are rejected at the API boundary,
before enqueueing. Rejection drops the event, never fails the operation.

Free text and content — prompts, queries, paths, document or message bodies,
user names and emails — are forbidden, including in span names, status text,
resource attributes and automatically recorded exceptions. Tools MUST NOT
enable automatic instrumentation that bypasses this boundary. Content may
appear only as a length or a salted hash in a schema-declared derived field.
Do not accept arbitrary strings disguised as enums or hashes.

Identifiers MUST be hashed with a per-install random salt stored at mode
`0600` under `~/.punt-labs/` (for example, `~/.punt-labs/telemetry.salt`).
The shared API owns derivation; raw identifiers and the salt never enter the
queue, database or network payload. Create the salt privately and atomically;
never use a public or cross-install salt.

## Storage and Export

Local capture is **on by default**. The default exporter writes SQLite at
`~/.punt-labs/<tool>/telemetry.db`, separate from diagnostic log files.

- Directory mode MUST be `0700`; the database and SQLite sidecars MUST be
  `0600`. Follow quarry's `telemetry_perms.TelemetryPathGuard`: pre-create
  the leaf with `os.open(..., O_CREAT | O_EXCL, 0o600)` before SQLite opens it,
  tighten existing files, and secure the directory first. An
  open-then-chmod window is forbidden.
- Storage MUST be retention-bounded: default **90 days**, matching quarry's
  `Settings.telemetry_retention_days`. Prune periodically in long-lived
  processes as well as at startup; reclaim expired storage so the database
  does not grow indefinitely. Retention is configurable, never unlimited.
- A future OTLP/HTTP exporter is a configuration change only. Network export
  MUST be explicit and opt-in; local capture does not imply consent to send.
  The same schema and privacy checks apply to every exporter.

## Controls and Failure Isolation

`PUNT_TELEMETRY=off` disables all capture and export globally and overrides
per-tool settings. Each tool MUST also expose a config switch and a
`<TOOL>_TELEMETRY=off` environment switch. Any off switch wins. Disabled
telemetry opens no store and starts no exporter or background worker.

Telemetry MUST never block or fail a tool. Use a bounded, non-blocking queue;
drop events on saturation. Bound exporter I/O and shutdown flush time. Swallow
exporter errors and report them through diagnostic logging (rate-limited,
metadata only), never through the failing telemetry pipeline. Invalid events,
an unwritable database, a full disk or an unavailable backend cannot change
the operation's result.

## Adoption Checklist

- [ ] Use the shared package once shipped; do not hand-roll copies or exporters
- [ ] Declare versioned event schemas, names, units and attribute allowlists
- [ ] Test valid, empty, unknown and wrong-type attributes and content rejection
- [ ] Keep raw content and identifiers out of every OTel signal and resource
- [ ] Create the database, sidecars and per-install salt with private permissions
- [ ] Enforce retention during long-running operation and reclaim expired space
- [ ] Test global and per-tool off switches, including no store creation
- [ ] Test queue saturation, exporter errors and bounded shutdown
- [ ] Keep network export explicit and opt-in; verify exporter-only migration
