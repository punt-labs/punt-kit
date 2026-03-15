# Logging Standards

Standards for logging across all Punt Labs Python projects. Role models: **vox** (centralized dictConfig, rotating files, PII-free correlation) and **quarry** (comprehensive operational coverage).

---

## Core Principles

1. **Logs are for diagnosis, not monitoring.** These are local-first CLI tools, not cloud services. Logs exist to answer "what happened?" after something goes wrong.
2. **Never log content.** User text, document bodies, speech payloads, and message content are PII. Log metadata, counts, and content-derived hashes instead.
3. **Every process writes to the same file.** CLI invocations, MCP server requests, hook dispatchers, and detached subprocesses all append to one rotating log. Interleaved entries are expected; correlation keys distinguish them.

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
                    "class": "logging.handlers.RotatingFileHandler",
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

### MCP server constraint

MCP servers using stdio transport must never write to stdout (reserved for the JSON-RPC protocol). The stderr handler captures server-side logs. The file handler captures everything.

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

## Per-Module Logger Declaration

Every module that logs must declare its logger at module scope:

```python
logger = logging.getLogger(__name__)
```

Do not use the root logger directly. Do not pass logger instances between modules. The `__name__` convention ensures log entries show the originating module.

---

## What Not to Log

- **Success of routine operations.** Don't log "Config file loaded successfully" on every startup. Log it only if loading *fails* or if the path is non-obvious.
- **Loop iterations.** Don't log inside tight loops. Log the aggregate: "Processed 42 documents" not 42 individual "Processing document X" entries.
- **Unchanged state.** Don't log "No changes detected." Absence of a change log entry *is* the signal.
- **Redundant context.** If a caller already logged the operation, the callee should not log it again. Log at the decision point, not at every layer.

---

## Detached Subprocesses

Subprocesses spawned with `start_new_session=True` (e.g., playback workers) inherit no logging configuration. They must call `configure_logging()` in their `__main__` block.

```python
if __name__ == "__main__":
    from <package>.logging_config import configure_logging
    configure_logging(stderr_level="WARNING")
    # ... do work ...
```

Do not suppress stderr from subprocesses that need to log. If a subprocess writes to stderr and the parent doesn't want to see it, let the file handler capture it silently.

---

## Adoption Checklist

For projects adopting this standard:

- [ ] Create `logging_config.py` with the `dictConfig` pattern above
- [ ] Set log directory permissions to `0o700`
- [ ] Ensure every module uses `logger = logging.getLogger(__name__)`
- [ ] Call `configure_logging()` from each entry point (CLI, MCP, hooks)
- [ ] Audit INFO-level log messages for content/PII leakage
- [ ] Suppress noisy third-party loggers
- [ ] Verify detached subprocesses configure their own logging
- [ ] Standardize log format to `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

### Current project status

| Project | Persistent logs | dictConfig | 0o700 dir | Format match | PII audit |
|---------|:-:|:-:|:-:|:-:|:-:|
| vox | Yes | Yes | Yes | Yes | Done |
| quarry | Yes | No (manual) | No | No (bare style) | Needed |
| biff | No | No | N/A | N/A | Needed |
| langlearn-tts | Yes | Yes | No | Yes | Low risk |
