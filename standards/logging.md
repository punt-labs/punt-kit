# Logging Standards

Standards for logging across all Punt Labs Python projects. Reference patterns: **vox**'s centralized `dictConfig` and its `vibe-trace` sink (atomic `O_APPEND`, `0600`, escaped) — the append/escape/permission model this standard generalizes — and **quarry**'s operational coverage. (The patterns are the reference, not a clean bill of health: the 2026-07-17 vox audit found the previous "role model" had `0644` files, a content leak, and a multi-writer race. This revision codifies the fixes; see [Current project status](#current-project-status).)

---

## Core Principles

1. **Logs are for diagnosis, not monitoring.** These are local-first CLI tools, not cloud services. Logs exist to answer "what happened?" after something goes wrong.
2. **Never log content.** User text, document bodies, speech payloads, and message content are PII. Log metadata, counts, and content-derived hashes instead.
3. **No silent gaps — but no noise.** Every **decision, state change, outcome (success *and* failure, symmetrically), and boundary cross** must leave a line, so an operator never has to *guess* what the system did. The corollary is the discipline: *absence of a line means nothing happened.* That only holds if you also **suppress noise** — pure no-ops, per-iteration chatter, and the same event logged at every layer. Log at the decision point, once. (See [Levels](#levels) and [What Not to Log](#what-not-to-log).)
4. **Readable by a user, not just a developer.** INFO is plain language a user can follow ("spoke 12 chars with say"), not internal codes or key=value dumps ("Direct-play ok: provider=say voice= elapsed=0.512s"). Developer detail lives at DEBUG. (See [User-Readable INFO](#user-readable-info-vs-developer-debug).)
5. **A durable file is the only sink that counts — never stderr alone.** For MCP servers and hook subprocesses the host (e.g. Claude Code) **discards stderr entirely.** Anything you need to prove happened — an outcome, a security event, a proof trail — must reach a file. stderr is a convenience for an attached terminal, never the system of record. (See [Where logs land](#where-logs-land).)
6. **One process owns each file.** Multiple processes appending one `RotatingFileHandler` corrupts it on rotation. Either one process owns the file, or writers use atomic single-line `O_APPEND`. (See [Multi-Process Safety](#multi-process-safety).)

---

## Configuration

Every project with a CLI or MCP server must have a `logging_config.py` module that owns all logging setup.

### Required pattern

```python
"""Logging configuration for punt-<name>."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

_LOG_DIR = Path.home() / ".punt-labs" / "<tool>" / "logs"
_LOG_FILE = _LOG_DIR / "<tool>.log"

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_MAX_BYTES = 5_242_880  # 5 MB
_BACKUP_COUNT = 5


def configure_logging(*, stderr_level: str = "WARNING") -> None:
    """Configure logging with rotating file and stderr handlers.

    File handler is always active at INFO level.
    Stderr handler level is controlled by the caller.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": _FORMAT,
                    "datefmt": _DATE_FORMAT,
                },
            },
            "handlers": {
                "file": {
                    # NOT plain RotatingFileHandler — that opens 0666 & ~umask
                    # (0644 in practice) and never re-tightens. Log files hold
                    # operational metadata and must be 0600. See File Permissions.
                    "()": _private_rotating_handler,
                    "filename": str(_LOG_FILE),
                    "maxBytes": _MAX_BYTES,
                    "backupCount": _BACKUP_COUNT,
                    "encoding": "utf-8",
                    "formatter": "standard",
                    "level": "INFO",
                },
                "stderr": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": "standard",
                    "level": stderr_level,
                },
            },
            "root": {
                "level": "DEBUG",
                "handlers": ["file", "stderr"],
            },
        }
    )
```

### File Permissions (0600) — required

Log files hold operational metadata (paths, config values, provider/voice ids, signal tokens) and must be owner-only. **The plain `RotatingFileHandler` is unsafe here:** `logging.FileHandler` opens with `open(path, "a")` → `0666 & ~umask` → **0644 in practice**, never re-tightens a pre-existing file, and **rotated backups inherit the loose mode.** A `0700` log *directory* is not enough — it is a single point of failure, and defense-in-depth requires the file bit too.

Use a handler that forces `0600` on the active file **and** every rotated backup, and re-tightens pre-existing files:

```python
import os
from logging.handlers import RotatingFileHandler

_FILE_MODE = 0o600


class PrivateRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that keeps the log (and its backups) 0600."""

    def _open(self):  # noqa: no wider mode ever reaches disk
        stream = super()._open()
        self._chmod(self.baseFilename)
        return stream

    def doRollover(self) -> None:
        super().doRollover()
        for path in (self.baseFilename, *self._backups()):
            self._chmod(path)

    def _backups(self) -> list[str]:
        return [f"{self.baseFilename}.{i}" for i in range(1, self.backupCount + 1)]

    def _chmod(self, path: str) -> None:
        try:  # best-effort — a chmod we cannot do must not block logging
            os.chmod(path, _FILE_MODE)
        except OSError:
            pass


def _private_rotating_handler(**kwargs: object) -> PrivateRotatingFileHandler:
    return PrivateRotatingFileHandler(**kwargs)  # dictConfig "()" factory
```

Rotated backups (`<tool>.log.1`–`.5`) **must** be `0600` too — this is the most common miss. The log *directory* is created `mode=0o700` (see [Log Location](#log-location)).

### Rules

1. **Use `dictConfig`, not `basicConfig`.** `basicConfig` is not idempotent and does not support handler-level granularity.
2. **One call site per entry point.** CLI `__main__.py` calls `configure_logging(stderr_level="WARNING")` (or `"DEBUG"` for `--verbose`). MCP `server.py` calls `configure_logging(stderr_level="INFO")`. Hook dispatchers call `configure_logging(stderr_level="WARNING")`.
3. **Never call `configure_logging` from library code.** Only entry points configure logging. Library modules declare `logger = logging.getLogger(__name__)` and use it.
4. **Suppress noisy third-party loggers** in the `dictConfig` block when needed:

```python
"loggers": {
    "boto3": {"level": "WARNING"},
    "botocore": {"level": "WARNING"},
    "urllib3": {"level": "WARNING"},
    "httpx": {"level": "WARNING"},
},
```

---

## Log Location

| Component | Path |
|-----------|------|
| Log directory | `~/.punt-labs/<tool>/logs/` |
| Primary log | `~/.punt-labs/<tool>/logs/<tool>.log` |
| Rotated backups | `<tool>.log.1` through `<tool>.log.5` |

The directory is created with `mode=0o700` (owner-only). Logs may contain operational metadata (file paths, config values, signal tokens) that should not be world-readable.

### Where logs land

**The file handler is the system of record. stderr is not.**

| Process | Durable sink | stderr |
|---------|--------------|--------|
| CLI (attached terminal) | file handler | visible to the user — a convenience |
| MCP server (stdio) | **file handler only** | **discarded by the host** (e.g. Claude Code) |
| Hook subprocess | **file handler only** | **discarded by the host** |
| Detached subprocess | **file handler only** | usually `DEVNULL` |
| Daemon (service) | file handler | may be captured by the service manager — but see below |

- **MCP stdio constraint.** Servers using stdio transport must never write to **stdout** (reserved for JSON-RPC). Configure a stderr handler if you like, but understand it is **discarded** for MCP and hook processes — never rely on it. The file handler is what survives.
- **Do not double-write the daemon's stderr to a file.** Routing a service manager's `StandardErrorPath` to a file *in addition to* the file handler duplicates every line into a second, usually unbounded and unrotated, world-readable file. Pick one durable sink (the file handler) and drop the redirect.
- **The vox-9po7 lesson, generalized:** a proof/observability trail written to MCP/hook stderr is written to `/dev/null`. If you need to `grep` for it later, it must be in a file. Verify by grepping the *running* system, not by trusting a unit test (a test can assert the logger was called without proving the bytes reached disk).

---

## Format

All projects use the same format string:

```text
2026-03-08 10:37:41 [INFO] punt_vox.server: Starting vox MCP server (mic)
```

Components: `timestamp [LEVEL] module.path: message`

- **Timestamp**: `%Y-%m-%d %H:%M:%S` (local time, second precision)
- **Level**: Bracketed, uppercase
- **Module**: Full dotted path from `__name__`
- **Message**: Free text, no structured fields

Do not add structured key-value formatting (e.g., `key=value` pairs). The log is human-read during diagnosis, not machine-parsed for aggregation.

---

## Rotation

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max file size | 5 MB | Keeps `tail -f` responsive; large enough for multi-day history |
| Backup count | 5 | 30 MB total cap; sufficient for investigation window |
| Encoding | UTF-8 | Unicode in voice names, file paths, error messages |

---

## Multi-Process Safety

**`RotatingFileHandler` is not safe when more than one process writes the file.** Python's own docs say so. `doRollover()` renames `<tool>.log → <tool>.log.1`; if two processes cross `maxBytes` near-simultaneously they both rename, and a writer can hold a file descriptor to a file that was renamed out from under it — lines are lost or land in the wrong file. This is not theoretical: a tool whose CLI, MCP server, and one-process-per-event hooks all write one log hits the race routinely (the rotation files sit pinned at exactly `maxBytes`).

**A `QueueHandler`/`QueueListener` does NOT fix this.** A queue decouples logging I/O from a hot thread *within one process* — separate processes have separate queues and separate address spaces. Reaching for it here is a category error.

Choose one of:

| Pattern | Use when | Tradeoff |
|---------|----------|----------|
| **Single owner** — one process (the daemon) owns the file; other processes ship records to it over the transport they already hold | there is a natural central process | needs a tiny local fallback for when the owner is down |
| **Atomic `O_APPEND` line-writer** — each process opens `O_WRONLY\|O_APPEND\|O_CREAT` and writes the whole line in one `os.write` | no central process; stdlib-only | lose automatic size-rotation — pair with `WatchedFileHandler` + external `logrotate` |
| **Cross-process locking handler** (`concurrent-log-handler`) | you must keep `RotatingFileHandler` semantics | adds a dependency; lock contention under bursty writers |

`RotatingFileHandler` is correct **only for a single-writer file** (e.g. a daemon's own log). The atomic-`O_APPEND` pattern is the stdlib reference: POSIX guarantees an `O_APPEND` write below the pipe-buffer size lands atomically at EOF, so concurrent single-line writes never tear or interleave.

---

## Levels

### INFO — the diagnostic backbone

INFO is the primary investigation level. Every log entry at INFO should answer one of:

- **What happened?** A state change, a file written, a process spawned.
- **What was decided?** A branch taken, a condition evaluated, a request skipped.
- **What crossed a boundary?** A subprocess spawned, an API called, a lock acquired.

Guidelines:

| Log this at INFO | Example |
|------------------|---------|
| Entry point startup | `Starting vox MCP server (mic)` |
| File writes | `Wrote .vox/a1b2c3d4.mp3` |
| Config changes | `Config: set voice = 'matilda'` |
| Hook decisions | `Stop hook: skip (no vibe_signals)` |
| Process spawns | `Enqueue playback: a1b2c3.mp3 → 12345_a1b2c3.mp3` |
| Lock acquisition | `Acquired playback lock, playing a1b2c3.mp3` |
| API calls (metadata only) | `API call: provider=elevenlabs, voice=XrExE9, chars=144` |
| Background task lifecycle | `Synthesis started: 1 segment(s)` |

### DEBUG — implementation details

DEBUG is for developers tracing through code. Not written to the file handler in production (file handler level is INFO).

| Log this at DEBUG | Example |
|-------------------|---------|
| Intermediate computation | `Split text into 3 chunks` |
| Cache hits/misses | `Voice metadata cached for elevenlabs` |
| Retry/fallback logic | `Provider fallback: elevenlabs → polly` |
| Detailed request/response shapes | `Batch: 5 requests, total 2340 chars` |

### WARNING — degraded but functional

Something is wrong but the operation can continue. Warnings should be actionable — if the user can't do anything about it, it's not a warning.

| Log this at WARNING | Example |
|---------------------|---------|
| Missing optional dependency | `vox binary not found, skipping audio` |
| Timeout with fallback | `Playback timed out after 120s` |
| File operation failure (non-fatal) | `Failed to copy audio for playback` |

### ERROR — operation failed

The requested operation could not complete. Errors should include enough context to diagnose without reading source code.

Never use ERROR for expected conditions (user typos, missing files, invalid input). Those are domain logic, not errors.

### Log outcomes symmetrically

If you log a failure, log the corresponding **success** at the same level. A path that logs "generation failed" but not "generation succeeded" tells an operator when music broke but never lets them confirm a track was produced — a silent gap. Success and failure of the same operation belong at the same level (usually INFO), or neither does.

### User-Readable INFO vs Developer DEBUG

INFO is read by a **user** diagnosing their own tool, not only by the author. Write INFO as a plain sentence describing *what happened*; push structured dumps, transport bookkeeping, counters, and intermediate computation to DEBUG.

| Developer INFO (wrong) | User-readable INFO (right) |
|------------------------|----------------------------|
| `cache MISS: id= provider=openai voice= size=566 chars_in=5 not cached` | `synthesized 5 chars with openai, cached` |
| `Direct-play ok: provider=say voice= elapsed=0.512s chars=12` | `spoke 12 chars with say (0.5s)` |
| `Session config: notify=c speak=n voice=roger provider=None vibe_mode=auto` | `ready — voice roger, chimes only, auto vibe` |
| `Playback spawn: cmd=[…] audio_env={…} timeout=120.0s` | `playing chime_done.mp3` *(the dump goes to DEBUG)* |

Translate internal codes the user can't read (`notify=c` → "chimes only"). One INFO line per user-visible event; the seven-lines-per-action transport trace belongs at DEBUG. Structured `key=value` formatting is a DEBUG affordance, not an INFO one.

---

## PII and Content Safety

### Never log

- Text content being synthesized, searched, ingested, or transmitted
- Message bodies (biff), document text (quarry), speech text (vox)
- API keys, tokens, or credentials
- Full URLs that may contain query parameters with user data

### Safe to log

- Content-derived hashes (MD5 filenames like `a1b2c3d4.mp3`)
- Character counts (`chars=144`)
- Document names and collection names (operational metadata, not content)
- Signal tokens (`tests-pass@10:25`)
- Provider and voice identifiers
- File paths within the user's home directory

### Correlation without content

Use content-derived hashes as natural correlation keys. Vox generates filenames via `hashlib.md5(text.encode()).hexdigest()[:12]` — the same text always produces the same hash, so duplicate operations are visible in logs without the text itself appearing.

When content hashing is not available, use request IDs or timestamps for correlation. Do not invent a new correlation scheme per project.

---

## Log Injection

A log line is data an incident responder (or root, or a later reader) trusts. An **untrusted value interpolated with `%s`** can smuggle a newline and forge a second, authentic-looking line — or emit terminal control sequences that corrupt a `cat`/`tail`.

**Untrusted** = anything from a wire/RPC message, a subprocess's stderr, a provider's error body, or a filename/path the user or a remote service controls.

Rules:

- **Never `%s`-interpolate an untrusted value.** Use `%r` (repr escapes quotes, backslashes, and newlines) or an explicit escape table.
- For a durable proof/audit line, escape a fixed set: all C0 control chars (`0x00`–`0x1F`) and `DEL`, **plus the Unicode line separators** `U+0085` (NEL), `U+2028`, `U+2029` — these break tools that split on Unicode line boundaries (e.g. Python `str.splitlines()`) even though the file holds a single `\n`.
- `repr()`-style interpolation (`VOXD_PORT=%r`) is the cheap correct default; a shared escape helper is worth it once more than one sink interpolates untrusted values.

```python
_SANITIZE = {c: f"\\x{c:02x}" for c in (*range(0x20), 0x7F)}
_SANITIZE.update({cp: f"\\u{cp:04x}" for cp in (0x85, 0x2028, 0x2029)})
safe = value.translate(_SANITIZE)   # exactly one physical line, no control bytes
```

---

## Security Events to Log

Some events must be logged **because** they are security-relevant — silence is the vulnerability. This is bounded diagnosis, **not a SIEM**: no alerting, no aggregation, metadata only.

Log at WARNING, to the durable file:

- **Authentication/authorization outcomes** — a rejected token, a failed permission check, a denied connection. Log the *decision* and *who* (client address, request id) — **never the credential, the token, or the expected value.** An auth boundary that closes a connection with no log means an attack leaves no trace.
- **Rejected or malformed requests** — a request dropped for bad shape, an unknown signal, a size/format violation. (Escape the offending value per [Log Injection](#log-injection).)
- **Permission-tightening failures** — a `chmod`/`fchmod` that could not enforce `0600`/`0700`. Best-effort tightening must still *say* it failed.

Do not log the *content* of a rejected request (that is still PII); log that it was rejected and why.

---

## Per-Module Logger Declaration

Every module that logs must declare its logger at module scope:

```python
logger = logging.getLogger(__name__)
```

Do not use the root logger directly. Do not pass logger instances between modules. The `__name__` convention ensures log entries show the originating module.

---

## What Not to Log

This is the other half of Principle 3. "No silent gaps" requires a line for every **decision, state change, and outcome**; "not noisy" forbids everything else. The test for a candidate log call: *would an operator, seeing this absent, have to guess whether something happened?* If yes, it is a gap — log it. If the thing it reports is already implied by a logged outcome, it is noise — cut it.

- **Success of routine operations *that another line already implies*.** Don't log "Config file loaded successfully" on every startup — but *do* log the outcome that depended on it. The rule is not "never log success" (that creates silent gaps); it is "don't log a success that a downstream outcome already proves." A success that is the *only* evidence an operation occurred is **required** (see [Log outcomes symmetrically](#log-outcomes-symmetrically)).
- **Loop iterations.** Don't log inside tight loops. Log the aggregate: "Processed 42 documents" not 42 individual "Processing document X" entries.
- **Unchanged state.** Don't log "No changes detected." Absence of a change log entry *is* the signal.
- **Redundant context / same event at every layer.** If a caller already logged the operation, the callee should not log it again. Log at the *decision point*, once — not at every layer of the call stack (the "seven lines per chime" smell).
- **Transport bookkeeping.** Connect/disconnect, per-request framing, and heartbeat lines are DEBUG, not INFO — they bury the user-visible events in a user-readable log.

---

## Detached Subprocesses

Subprocesses spawned with `start_new_session=True` (e.g., playback workers) inherit no logging configuration. They must call `configure_logging()` in their `__main__` block.

```python
if __name__ == "__main__":
    from <package>.logging_config import configure_logging
    configure_logging(stderr_level="WARNING")
    # ... do work ...
```

A detached subprocess's stderr typically goes to `DEVNULL`, and even when it doesn't the parent may not read it — so **stderr is not a sink for a detached subprocess.** What makes its logging durable is calling `configure_logging()` so its own **file handler** captures INFO+. Never leave anything you need to diagnose in a detached subprocess's stderr alone (see [Where logs land](#where-logs-land)).

---

## Adoption Checklist

For projects adopting this standard:

- [ ] Create `logging_config.py` with the `dictConfig` pattern above
- [ ] Log **files** are `0600` (active *and* rotated backups), pre-existing files re-tightened — not just the `0o700` dir
- [ ] No file written by more than one process via `RotatingFileHandler` (single owner or atomic `O_APPEND` — see [Multi-Process Safety](#multi-process-safety))
- [ ] Nothing security- or proof-relevant lives in MCP/hook/subprocess **stderr alone** — verify by grepping the running system
- [ ] Untrusted values are escaped (`%r` or the escape table) before interpolation — see [Log Injection](#log-injection)
- [ ] Auth/authz outcomes and rejected requests are logged (metadata only) — see [Security Events](#security-events-to-log)
- [ ] No silent gaps: state transitions, decisions, and **both** success and failure of each operation are logged
- [ ] INFO reads as plain sentences a user can follow; dumps/counters/transport are DEBUG
- [ ] Ensure every module uses `logger = logging.getLogger(__name__)`
- [ ] Call `configure_logging()` from each entry point (CLI, MCP, hooks, detached subprocess)
- [ ] Suppress noisy third-party loggers (including the MCP framework's request logger)
- [ ] Document the project's **sink map** — which processes write which file; prefer one durable file per tool, avoid split-brain
- [ ] Standardize log format to `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

### Current project status

| Project | dictConfig | files 0600 | multi-proc safe | no silent gaps | injection-safe | PII audit |
|---------|:-:|:-:|:-:|:-:|:-:|:-:|
| vox | Yes | **No** (0644 — vox-q637) | **No** (`tts.log` multi-writer) | **No** (state machine unlogged) | Partial (`vibe-trace` only) | **Leak** (music prompt — vox-q637) |
| quarry | No (manual) | ? | ? | ? | ? | Needed |
| biff | No | N/A | N/A | ? | ? | Needed |
| langlearn-tts | Yes | ? | ? | ? | ? | Low risk |

The 2026-07-17 vox audit ([`docs/logging-proposal.md`](https://github.com/punt-labs/vox/blob/main/docs/logging-proposal.md)) showed the previous all-green vox row was optimistic — the role model had `0644` files, a content leak, a multi-writer race, and silent gaps. Every project needs a real audit against the columns above, not a self-report.
