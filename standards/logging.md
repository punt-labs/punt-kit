# Logging Standards

**Updated:** 2026-11-19

Language-neutral diagnostic logging policy for Punt Labs tools. See the
[Python](../lang-rules/python/python-logging.md) and
[Go](../lang-rules/go/go-logging.md) implementation rules.
Stable clause IDs identify the policy enforced by language rules.

## LOG-1: Diagnostics, Not Usage

**Applies to:** python, go

Logs answer "what happened?" during diagnosis. Usage capture belongs in
[telemetry](telemetry.md), a separate pipeline, not diagnostic logs.

## LOG-2: PII and Content Safety

**Applies to:** python, go

Never log user text, prompts, queries, document or message bodies, speech
payloads, API keys, tokens, credentials, or full URLs containing user data.
Log metadata, counts and content-derived hashes instead. Operational metadata
such as document names, collection names, provider/voice identifiers and local
file paths is permitted only after redaction. Use hashes, request IDs or
timestamps for correlation, not raw content or a new per-project scheme.

## LOG-3: Coverage Without Noise

**Applies to:** python, go

Every decision, state change, outcome (success and failure) and boundary cross
must leave a diagnostic line. Log at the decision point, once, not at every
layer. Suppress pure no-ops, per-iteration chatter, progress-bar ticks and
redundant third-party output. Aggregate loop results rather than logging each
iteration. Cut routine successes already proved by another outcome, not the
only evidence of an operation. Transport framing, heartbeats and connection
bookkeeping belong at DEBUG. Absence of a line should mean nothing happened.

## LOG-4: Durable Sinks

**Applies to:** python, go

A durable file is the system of record; stderr alone never counts. MCP hosts
and hook runners can discard stderr. An attached terminal's stderr is only a
convenience. stdout is reserved for stdio transport in MCP servers. Do not
duplicate a daemon's diagnostics through service-manager stderr file redirects:
those create a second, often unbounded and unrotated file. Verify the running
system's bytes on disk, not merely that a logger was called.

## LOG-5: Configuration Ownership

**Applies to:** python, go

Each CLI, MCP server, hook dispatcher, daemon and detached-process entry point
configures its logging role. Libraries never configure global logging; they
use module-scoped loggers. Centralize configuration and reuse the shared
implementation rather than hand-rolling or vendoring copies. Suppress noisy
dependencies at configuration time.

## LOG-6: Final-Record Redaction

**Applies to:** python, go

Every file record MUST pass through a redactor after formatting, including
arguments, exception text and tracebacks. Mask URL credentials, URL paths,
query strings and fragments, and bare credentials. Escape control and
line-forging characters and cap record size (64 KiB reference limit).
Withhold a record whose redaction cannot settle. Redaction is defense in
depth, not permission to log content.

## LOG-7: Log Location

**Applies to:** python, go

Durable diagnostics are machine-scoped and repo-independent. Store them under
`~/.punt-labs/<tool>/logs/`, never in a repo: the primary file is `<tool>.log`,
with backups `<tool>.log.1` through `<tool>.log.5`. Repair and crash/hook-error
logs use the same root. See [filesystem.md](filesystem.md).

Repo-bound live audit/session streams are different: they belong in
`<repo>/.punt-labs/local/<tool>/` while live and are sealed into committed
history per [punt-labs-dir.md](punt-labs-dir.md#pld-6-live-streams-and-published-records-are-distinct-artifacts).
Do not pull repo-bound first-class data into the home tree or put durable
tool diagnostics in a repo. A log that reads identically regardless of the
triggering repo is home-tree; one meaningful only alongside a repo's work is
repo-bound.

## LOG-8: File Permissions

**Applies to:** python, go

Create the log directory owner-only (`0700`), and active files and every
rotated backup owner-only (`0600`). Create files privately and atomically;
an open-then-tighten window is forbidden. Tighten pre-existing directories,
active files and backups at startup and after rotation. A private directory
alone is insufficient defense in depth. Surface startup permission failures;
do not silently proceed with an insecure sink.

## LOG-9: Format

**Applies to:** python, go

Use local time at second precision, bracketed uppercase level, module or
component name and a human-readable sentence:

```text
2026-03-08 10:37:41 [INFO] vox.server: Starting vox MCP server (mic)
```

INFO is for a user diagnosing the tool, not just its developer. Translate
internal codes into plain language. Put structured field dumps and transport
bookkeeping at DEBUG, not INFO. Never include content at either level.

## LOG-10: Rotation

**Applies to:** python, go

Bound storage to a **5 MB (5,242,880-byte) active file × 5 backups**, approximately
30 MB total. Use UTF-8. Apply the same permissions and redaction to backups.

## LOG-11: Multi-Process Safety

**Applies to:** python, go

Any log file that can have more than one writer process MUST use
multi-process-safe rotation, not merely atomic appends. Single-process
rotating handlers are forbidden unless one process provably owns the file.
Acceptable designs are a single owner receiving records from other processes,
or atomic `O_APPEND` writes with lock-serialized rotation and inode-aware
reopening by writers. Serialize rotation across processes with a lock file;
do not rely on per-process locks. Reopen after replacement before writing to
avoid orphaned inodes. Test concurrent CLI, server and hook writers through
rollover for record loss, corruption, bounded storage and private backups.

## LOG-12: Levels

**Applies to:** python, go

Production files default to INFO; developer detail belongs at DEBUG.

| Level | Purpose | Examples |
|-------|---------|----------|
| INFO | State changes, decisions, boundary crosses | Startup, config changes, file writes, hook decisions, process spawns, API calls (metadata only), lock acquisition, background lifecycle |
| DEBUG | Implementation detail | Intermediate computations, cache hits/misses, retries/fallbacks, request/response shapes without content |
| WARNING | Degraded but functional; actionable | Optional dependency missing, timeout with fallback, non-fatal file failure |
| ERROR | Requested operation failed | Unexpected failures with enough context to diagnose |

Expected conditions such as user typos, missing inputs and invalid domain
values are not ERRORs. Warnings should be actionable.

## LOG-13: Symmetric Outcomes

**Applies to:** python, go

If a failure is logged, log the corresponding success at the same level
(usually INFO), or neither. One user-visible event gets one INFO sentence;
per-action transport traces belong at DEBUG.

## LOG-14: Log Injection

**Applies to:** python, go

Never interpolate an untrusted value raw, including eagerly formatted values.
Escape wire/RPC data, subprocess stderr, provider errors and user-controlled
filenames before they reach the record. For proof/audit lines, escape all C0
controls (`U+0000`–`U+001F`), DEL and C1 controls (`U+007F`–`U+009F`), and Unicode
line separators `U+0085`, `U+2028`, `U+2029`. Produce one physical line, without
terminal control sequences or forged follow-on records. Use shared escaping
across sinks rather than inventing per-call substitutions.

## LOG-15: Security Events

**Applies to:** python, go

Log security-relevant decisions at WARNING to the durable file: authentication
and authorization outcomes, rejected/malformed requests and permission-tightening
failures. Include diagnostic metadata (client address, request ID, reason),
never credentials or the content of rejected requests. This is bounded
diagnosis, not a SIEM. Escape untrusted values per LOG-14.

A tightening failure inside the log-write path cannot report through the same
sink without recursion; handle it best-effort there. This exception does not
apply to startup/directory preparation, where permission failures MUST surface.

## LOG-16: Detached Processes

**Applies to:** python, go

Detached children configure their own durable sink even when all standard
streams are discarded. Record spawn intent, child startup, completion and
failure with correlation metadata. A successful spawn is not proof of a
successful child operation. Never rely on inherited stderr or an attached
terminal to diagnose a hook, daemon or detached worker.
