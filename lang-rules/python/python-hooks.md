---
paths:
  - "**/*.py"
---

# Python Hooks

**Introduced:** 2026-11-27

Implements the [hook standard](../../standards/hooks.md) for tools written in
Python. The hook evaluator reviews the consuming tool's hook module, shell
gates and tests against these rules.

## PY-HOOK-1: Write handlers as functions over the payload dict

**Implements:** HOOK-1, HOOK-2, HOOK-6 · **Gate:** `review` (hook evaluator)

Business logic lives in `hooks.py` as pure functions. Each takes the payload
`dict` the dispatcher parsed and returns the context to inject, or `None`. An
observation handler catches every exception and returns `None`; a mutation
handler lets the exception reach the dispatcher, which exits non-zero so the
gate fails closed (HOOK-16).

```python
def handle_post_bash(data: dict[str, Any]) -> str | None:
    """PostToolUse Bash — detect events and return context."""
    command = data.get("tool_input", {}).get("command", "")
    # ... classify, detect, return additionalContext or None
```

## PY-HOOK-2: Fire side effects without waiting

**Implements:** HOOK-7 · **Gate:** `review` (hook evaluator)

For side-effect handlers, use `subprocess.Popen` (not `subprocess.run`)
or a daemon thread to avoid blocking the hook timeout:

```python
# CORRECT: fire-and-forget for side effects
subprocess.Popen(
    ["vox", "play", chime_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
return None  # Don't wait

# WRONG: blocks until audio finishes playing
subprocess.run(["vox", "play", chime_path])
return None  # Waited for nothing
```

## PY-HOOK-3: Read stdin with select and os.read

**Implements:** HOOK-8 · **Gate:** `make test` (open-pipe regression test)

**Never call `sys.stdin.read()` in a hook handler.** It blocks until
EOF. Claude Code pipes JSON to hook subprocesses but does not always
close the pipe promptly — causing an indefinite hang that freezes
session resume/startup.

Use `os.read()` in a `select` loop with short timeouts:

```python
import json
import os
import select
import sys


def _read_hook_input() -> dict[str, object]:
    """Read JSON hook payload from stdin (non-blocking).

    Uses select + os.read to avoid blocking forever when
    Claude Code does not close the stdin pipe.  See biff DES-027.
    """
    try:
        fd = sys.stdin.fileno()
        # Wait up to 100ms for initial data.
        if not select.select([fd], [], [], 0.1)[0]:
            return {}
        # Read available data in chunks (50ms inter-chunk timeout).
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:  # EOF
                break
            chunks.append(chunk)
            if not select.select([fd], [], [], 0.05)[0]:
                break
        raw = b"".join(chunks).decode()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
```

**Why not `sys.stdin.read()`?** `select()` returning readable only
guarantees one byte won't block — it does not guarantee EOF has
arrived. `sys.stdin.read()` after `select()` still blocks when data
exists without EOF. `os.read(fd, 65536)` returns available bytes
immediately without waiting for EOF.

**Handlers that don't use stdin data should not read it.** The
"consume stdin to avoid pipe backpressure" pattern is the exact
vector for this hang. Remove `_read_hook_input()` calls from
handlers that discard the result.

**Test the non-blocking behavior.** Every project that reads stdin
in hooks must have a regression test for the open-pipe-no-EOF case:

```python
def test_no_eof_does_not_hang(self) -> None:
    """Stdin with data but no EOF returns data without blocking."""
    r_fd, w_fd = os.pipe()
    os.write(w_fd, b'{"event": "resume"}\n')
    # Do NOT close w_fd — simulates open pipe without EOF.
    r = os.fdopen(r_fd, "r")
    with patch("sys.stdin", r):
        result = _read_hook_input()
    r.close()
    os.close(w_fd)
    assert result == {"event": "resume"}
```

## PY-HOOK-4: Dispatch hooks through a hidden Typer group

**Implements:** HOOK-9 · **Gate:** `review` (hook evaluator)

The CLI exposes hook handlers as hidden subcommands:

```python
hook_app = typer.Typer(hidden=True)


@hook_app.command("post-bash")
def cc_post_bash() -> None:
    """PostToolUse Bash — internal hook dispatcher."""
    data = _read_hook_input()  # non-blocking, never sys.stdin.read()
    context = handle_post_bash(data)
    if context:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": context,
                    }
                }
            )
        )


app.add_typer(hook_app, name="hook")
```

Pattern: `<tool> hook <event>` ([CLI-10](../../standards/cli.md#cli-10-keep-hook-dispatch-internal)).

---

## PY-HOOK-5: Keep the import tax off the hook path

**Implements:** HOOK-25 · **Gate:** `review` (hook evaluator)

### The import tax

The three-layer dispatch ([HOOK-2](../../standards/hooks.md#hook-2-dispatch-through-registration-gate-and-handler)) routes hook calls through the
CLI entry point:

```text
hooks/<event>.sh  →  <tool> hook <event>  →  __main__.py  →  hooks.py handler
```

This path imports the full application before dispatching to the hook
handler. If the application imports nats, pydantic, lancedb,
onnxruntime, or similar heavy libraries, every hook invocation pays
that cost — even when the handler only needs `pathlib` and `json`.

Three layers compound the tax:

1. **Eager `__init__.py`** — `import <package>` triggers top-level
   imports of every submodule. A `from <package>.hook import handler`
   pulls in the entire dependency tree.
2. **Entry point routing through `__main__.py`** — The CLI framework
   (typer), server, commands, and configuration all load before the
   hook subcommand is reached.
3. **Handler imports from heavy modules** — Even with lazy imports in
   the handler, importing from a module that itself imports heavy
   libraries triggers the full chain. Pure-stdlib functions trapped
   inside heavy modules are the root cause.

Measured on biff: `biff hook claude-code session-start` took 3.7s cold;
the lightweight `biff-hook` entry point took 0.29s.

### The fix: three corresponding layers

Each layer of the import tax has a corresponding fix:

**1. `_stdlib.py` — Extract stdlib-only functions**

Move pure-stdlib functions out of modules that import third-party
libraries. The handler imports from `_stdlib` instead of from the
heavy module. The heavy module also imports from `_stdlib` to avoid
duplication.

```python
# src/<package>/_stdlib.py
"""Stdlib-only helpers for lightweight hook paths.

Every function in this module MUST use only stdlib imports.
Adding a third-party import here defeats the entire purpose.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def find_git_root() -> Path | None:
    """Walk up from cwd to find .git directory."""
    ...


def is_enabled(repo_root: Path) -> bool:
    """Check if tool is enabled in this repo."""
    ...
```

**Invariant**: `_stdlib.py` uses only stdlib imports. This is the
module's reason for existing. The docstring must state this explicitly.

**2. Lightweight entry point — bypass `__main__.py`**

Register a separate console script that parses `sys.argv` directly
and dispatches to handler functions without loading the CLI framework:

```toml
# pyproject.toml
[project.scripts]
<tool> = "<package>.__main__:app"         # Full CLI
<tool>-hook = "<package>._hook_entry:main" # Lightweight hook path
```

```python
# src/<package>/_hook_entry.py
"""Lightweight hook entry point — bypasses __main__.py entirely."""
import sys

def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        from <package>.__main__ import app
        app()
        return
    layer, event = args[0], args[1]
    # Dispatch to handler functions (lazy import per handler)
    ...
```

Update all hook shell scripts: `<tool> hook` → `<tool>-hook`.

**3. Lazy `__init__.py` — PEP 562 `__getattr__`**

Replace eager imports with deferred loading so that importing a
lightweight submodule does not trigger the full package:

```python
# src/<package>/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from <package>.models import MyModel  # static analysis only

def __getattr__(name: str) -> object:
    if name == "MyModel":
        from <package>.models import MyModel
        globals()["MyModel"] = MyModel
        return MyModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### When to apply

Not every project needs the full fix. Apply based on measured cost:

| Condition | Action |
|-----------|--------|
| SessionStart handler spawns Python, cold start > 1s | Apply all three layers |
| SessionStart handler spawns Python, cold start 0.3–1s | Consider `_stdlib` extraction only |
| SessionStart is pure shell or cold start < 0.3s | No action needed |
| Git hooks (`.git/hooks/`) use the CLI | Leave as-is — not on the latency-critical path |

## PY-HOOK-6: Gate, wire, register and test hooks

**Implements:** HOOK-3, HOOK-4, HOOK-5, HOOK-10, HOOK-11, HOOK-12, HOOK-13, HOOK-14, HOOK-15, HOOK-16, HOOK-17, HOOK-18, HOOK-19, HOOK-20, HOOK-21, HOOK-22, HOOK-23, HOOK-24 · **Gate:** `review` (hook evaluator)

Shell gates under `hooks/` test effective state and then call
`<tool> hook <event>` (or the `<tool>-hook` entry point of PY-HOOK-5); for
every `handle_<event>()` in `hooks.py`, a gate calls it and its event and
matcher are registered: in `hooks.json` for a plugin hook, or by shared-scope
`enable` for a repo-scoped hook (HOOK-17). Return deny decisions as
`hookSpecificOutput` with `permissionDecisionReason`, and check
`data.get("stop_hook_active")` before a Stop hook blocks. Unit tests call
each `handle_<event>()` with a `dict` and assert on the result; integration
tests drive the shell gate with JSON on stdin and read JSON from stdout.
