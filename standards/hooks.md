# Hook Standards

Standards for Claude Code hook implementation across all Punt Labs projects.
Hooks integrate tools with Claude Code's lifecycle without containing
business logic themselves.

This standard consolidates hook guidance from
[cli.md § Hook Architecture](cli.md#hook-architecture) (structure and
dispatch) and [plugins.md § Required Hooks](plugins.md#required-hooks)
(SessionStart and output suppression). Those sections remain as
cross-references; this document is the authoritative reference for hook
implementation.

---

## 1. Claude Code State Machine

Hooks fire at specific transitions in Claude Code's lifecycle. To
understand where a hook fires and what it can do, you need the state
machine. This section summarizes the formal model maintained at
`z-spec/examples/claude-code.tex` (verified by probcli model checker:
329K states, 1.1M transitions, all visited, no counter-example).

### Session phases

```text
spInactive → spIdle → spProcessing → spResponding → spIdle → ... → spEnded
                ↑           ↓              ↓
                └───────────┘  (ForceContinue — Stop hook blocks)
                ↑              ↓
                └──────────────┘  (FinishResponse — Stop hook allows)
```

| Phase | Description | What can happen |
|-------|-------------|-----------------|
| **spInactive** | Before SessionStart | Nothing — no hooks, no tools |
| **spIdle** | Waiting for user input | CompactContext, EndSession |
| **spProcessing** | Claude reasoning + dispatching tools | Tool calls, subagent spawns, biff/vox/quarry operations |
| **spResponding** | Streaming response to user | Stop hook fires (block or allow) |
| **spEnded** | Terminal | SessionEnd hook fires, then nothing |

### Tool execution pipeline

Within `spProcessing`, each tool call traverses:

```text
tpNone → tpPreHook → tpPermission → tpExecuting → tpNone
              ↓ (deny)      ↓ (deny)
              └──────────────┴──→ tpNone (tool blocked, context injected)
```

| Phase | Hook event | Can block? |
|-------|-----------|------------|
| **tpPreHook** | PreToolUse | Yes — deny returns to tpNone with reason |
| **tpPermission** | PermissionRequest | Yes — deny returns to tpNone |
| **tpExecuting** | (tool runs) | No — tool is in flight |
| **tpNone** (after) | PostToolUse / PostToolUseFailure | No — tool already completed |

### Hook event timing

| Hook Event | When | Session Phase | Can Block? |
|-----------|------|---------------|------------|
| SessionStart | Session begins or resumes | spInactive → spIdle | No |
| UserPromptSubmit | User submits prompt | spIdle → spProcessing | Yes |
| PreToolUse | Before tool executes | spProcessing (tpPreHook) | Yes |
| PermissionRequest | Permission dialog | spProcessing (tpPermission) | Yes |
| PostToolUse | After tool succeeds | spProcessing (tpNone) | No |
| PostToolUseFailure | After tool fails | spProcessing (tpNone) | No |
| SubagentStart | Subagent spawned | spProcessing | No |
| SubagentStop | Subagent finishes | spProcessing | Yes |
| Stop | Claude finishes responding | spResponding | Yes |
| PreCompact | Before context compaction | spIdle | No |
| SessionEnd | Session terminates | spIdle → spEnded | No |
| Notification | Permission/idle prompt | Any active phase | No |

### Key invariants

These hold across all reachable states (proven by model checker):

1. **Tools only during processing**: `sessionPhase ≠ spProcessing ⟹
   toolPhase = tpNone`
2. **Blocking hooks are preconditions**: A blocking hook that fires
   prevents the transition entirely — no partial state update occurs.
3. **Stop hook re-entry**: If the Stop hook blocks, Claude returns to
   spProcessing. The `stop_hook_active` flag prevents a second block.
4. **Clean termination**: EndSession requires all subagents stopped
   and session in spIdle.

### Formal model

The full Z specification is at `z-spec/examples/claude-code.tex` with
Layer 2 extensions for each tool:

| Spec | What it models | Key property |
|------|---------------|--------------|
| `claude-code.tex` | Base state machine (18 ops) | All invariants hold across 329K states |
| `claude-code-biff.tex` | Workflow gates (plan + bead) | No file edit without plan and bead claimed |
| `claude-code-vox.tex` | Stop hook decision-block | No infinite loop; exactly one block per turn |
| `claude-code-quarry.tex` | Knowledge capture lifecycle | WebFetch dedup; compaction flag tracking |

---

## 2. Architecture

### Principle

Hooks are plumbing, not product. They integrate the CLI with Claude
Code's lifecycle but do not contain business logic themselves.

### Three-layer dispatch

```text
hooks.json          →  Shell script (thin gate)  →  CLI handler (business logic)
(registration)         (precondition check)          (pure function)
```

1. **hooks.json** — Declares which events to listen for and which
   scripts to run. Lives in `hooks/hooks.json` in the plugin root.
2. **Shell script** — Checks preconditions (config exists, tool
   enabled) and delegates to the CLI. Fails silently on error.
3. **CLI handler** — Pure Python function in `hooks.py` that takes
   structured input and returns structured output. Testable in
   isolation.

### File layout

```text
hooks/
  hooks.json              # Hook event registrations
  session-start.sh        # Thin gate → <tool> hook session-start
  suppress-output.sh      # Output formatting for MCP tools
  notify.sh               # Stop hook handler (if applicable)
  signal.sh               # PostToolUse Bash handler (if applicable)
  ...

src/<package>/
  hooks.py                # Pure handler functions (testable)
  __main__.py             # CLI entry point, includes hook subcommands
```

---

## 3. Shell Script Pattern

Shell scripts are thin gates. They check preconditions and delegate to
the CLI. They must never contain business logic.

```bash
#!/usr/bin/env bash
# hooks/<event>.sh — Thin gate for <event> hook
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -f "$REPO_ROOT/.punt-labs/<tool>/enabled" ] || exit 0
<tool> hook <event> 2>/dev/null || true
```

### Rules

- **Stdin passthrough**: Claude Code sends JSON on stdin. The shell
  script must pass it to the CLI handler (implicit via pipe or
  redirect). Do not consume stdin in the shell script.
- **Fail silently**: Use `2>/dev/null || true` for observation hooks.
  Only mutation hooks (PreToolUse denials) should propagate failures.
- **No business logic**: If the script is longer than 10 lines of
  non-boilerplate, the logic belongs in Python.
- **Config gate**: Check the tool's enabled marker
  (`.punt-labs/<tool>/enabled`) before dispatching. Exit 0 if absent. The
  marker — not a repo-root dotfile — is the enabled signal
  ([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)).

### Critical: wire shell scripts to Python handlers

Every shell script that delegates to a Python handler **must actually
call the handler**. This is the most common hook bug across Punt Labs
projects. Pattern:

```bash
# CORRECT: shell invokes Python handler
<tool> hook <event> < /dev/stdin

# WRONG: shell only does setup, Python handler is dead code
# (This exact bug was found in quarry — 3 handlers implemented but never called)
```

**Audit checklist**: For every `handle_<event>()` function in
`hooks.py`, verify that a shell script in `hooks/` calls it via the CLI
dispatcher. Dead handlers are invisible bugs.

---

## 4. Python Handler Pattern

Business logic lives in `hooks.py` as pure functions.

```python
def handle_post_bash(data: dict[str, Any]) -> str | None:
    """PostToolUse Bash — detect events and return context."""
    command = data.get("tool_input", {}).get("command", "")
    # ... classify, detect, return additionalContext or None
```

### Rules

- **Pure functions**: Take a dict, return a string (context to inject)
  or None. No side effects except logging and config file writes.
- **Structured input**: Read from the `data` dict passed by the CLI
  dispatcher, not from stdin directly.
- **Graceful degradation**: Catch all exceptions. Return `{}` or `None`
  on error. Never crash — a crashing hook blocks Claude Code.
- **Testable**: Every handler should have unit tests that pass dicts
  and assert on return values.

### Blocking vs non-blocking handlers

The Python handler should only do synchronous (blocking) work when the
**return value drives a decision**. If the hook's output is a side
effect (audio playback, file write, background ingest), do the work
asynchronously and return immediately.

| Return value purpose | Handler behavior | Example |
|---------------------|-----------------|---------|
| **Decision** (allow/deny/block) | Synchronous — must compute before returning | PreToolUse gate checks plan state |
| **Context injection** (additionalContext) | Synchronous — Claude needs the text | SessionStart injects project standards |
| **Side effect only** (audio, ingest, log) | Fire-and-forget — subprocess or thread, return immediately | Notification plays chime, PreCompact ingests transcript |
| **Nothing** (observation) | Return `None` immediately | Most PostToolUse signal classification |

**Rule**: Match the handler's blocking behavior to whether the caller
(Claude Code) needs the return value to proceed. This follows the same
principle as [cli.md § Sync vs Async](cli.md#sync-vs-async): "Does the
caller need the return value to proceed?"

For side-effect handlers, use `subprocess.Popen` (not `subprocess.run`)
or a daemon thread to avoid blocking the hook timeout:

```python
# CORRECT: fire-and-forget for side effects
subprocess.Popen(["vox", "play", chime_path],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
return None  # Don't wait

# WRONG: blocks until audio finishes playing
subprocess.run(["vox", "play", chime_path])
return None  # Waited for nothing
```

The hook registration's `async` flag controls whether **Claude Code**
waits for the shell script to exit. The handler's blocking behavior
controls whether the **Python process** waits for side effects. Both
should be non-blocking when the return value isn't needed — they are
independent knobs at different layers of the dispatch chain.

### Reading stdin: non-blocking reads only

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

### CLI dispatcher

The CLI exposes hook handlers as hidden subcommands:

```python
hook_app = typer.Typer(hidden=True)

@hook_app.command("post-bash")
def cc_post_bash() -> None:
    """PostToolUse Bash — internal hook dispatcher."""
    data = _read_hook_input()  # non-blocking, never sys.stdin.read()
    result = handle_post_bash(data)
    if result:
        print(json.dumps(result))

app.add_typer(hook_app, name="hook")
```

Pattern: `<tool> hook <event>` — "Commands called by hooks. These are
internal and not for direct user use." (from cli.md Layer 3)

---

## 5. Required Hooks

Every Punt Labs Claude Code plugin must implement these hooks. See
[plugins.md § Required Hooks](plugins.md#required-hooks) for the full
specification. Repo-scoped hook deposit and removal via `<tool> enable` /
`disable` — additive entries in `<repo>/.claude/settings.json`, reversed by
exact value-match — follow
[tool-enable-disable.md § 2.8](tool-enable-disable.md#28-hooks-and-config).

### SessionStart

Setup hook that runs on every session start. Must:

1. Deploy top-level commands (diff-and-copy, not skip-if-exists)
2. Auto-allow MCP tool permissions in `~/.claude/settings.json`
3. Run any first-time setup
4. Emit `hookSpecificOutput` with `additionalContext`

### PostToolUse (output suppression)

Every MCP tool must have a corresponding handler in
`suppress-output.sh` that formats output for the UI panel. Missing
handlers cause raw JSON to leak into the conversation.

Pattern: two-channel display — compact summary in
`updatedMCPToolOutput`, full data in `additionalContext`.

---

## 6. Hook Event Patterns

Patterns observed across biff, vox, and quarry, verified by Z
specification model checking.

### Observation hooks (non-blocking)

These hooks observe state and inject context. They must never block.

| Event | Matcher | Pattern | Example |
|-------|---------|---------|---------|
| SessionStart | * | Load state, inject guidance | Wall text, collision detection, project standards |
| PostToolUse | Bash | Classify output, accumulate signals | Vibe signals, plan hints, bead claim detection |
| PostToolUse | WebFetch | Capture side effect | Auto-ingest fetched URLs into knowledge base |
| PostToolUse | Edit\|Write | Inject relevant standards | Changelog format, Z spec conventions |
| PostToolUse | MCP tools | Format output | Two-channel display (suppress-output.sh) |
| PreCompact | * | Preserve state before compaction | Capture session transcript as searchable notes |
| SessionEnd | * | Cleanup | Clear session markers, reset signals |
| Notification | permission\|idle | Alert user | Chime or spoken notification |

### Mutation hooks (blocking)

These hooks can prevent an action. Use sparingly — blocking hooks that
fail can deadlock Claude Code.

| Event | Matcher | Pattern | Example |
|-------|---------|---------|---------|
| PreToolUse | Edit\|Write | Workflow gate | Require plan + bead before file edits |
| Stop | * | Decision-block | Speak summary before allowing stop |

### Decision-block pattern (Stop hook)

The Stop hook can block Claude from stopping to perform a side effect
(e.g., speaking a summary). This creates a re-entrant cycle:

```text
1. Claude finishes → Stop hook fires
2. Hook returns decision: "block" → Claude re-enters processing
3. Claude performs side effect (speak, check, etc.)
4. Claude finishes again → Stop hook fires (second time)
5. Hook detects re-entry flag → allows stop
```

**Critical invariant**: The re-entry flag (`stop_hook_active`) must
prevent the hook from blocking a second time. Without it, the hook
creates an infinite loop. This was formally verified by Z specification
model checking (11K states, 48K transitions, no counter-example).

**Implementation pattern** (from vox):

```python
def handle_stop(data: dict) -> dict | None:
    if data.get("stop_hook_active"):
        return None  # Second fire — allow stop
    if not should_block():
        return None  # Nothing to do — allow stop
    return {"decision": "block", "reason": "♪ Speaking..."}
```

### Workflow gate pattern (PreToolUse hook)

A PreToolUse hook can deny a tool call based on workflow state. The
denied tool call's reason is injected into context, and Claude
self-corrects.

```text
1. Claude decides to call Edit → PreToolUse fires
2. Hook checks: plan set? bead claimed?
3. If missing: return permissionDecision: "deny" with reason
4. Claude sees denial, sets plan/claims bead, retries
```

**Implementation pattern**:

```python
def handle_pre_tool_use(data: dict) -> dict | None:
    if not is_plan_set():
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Set a plan with /plan before editing files."
            }
        }
    return None  # Allow
```

**Critical: the field name is `permissionDecisionReason`, not `reason`.**
Claude Code silently ignores `"reason"` — the tool is still denied, but the
model receives no explanation. This breaks the self-correction loop: the
agent cannot read *why* it was blocked or *how* to unblock. There is no
error or warning when the wrong field name is used. See biff DES-026.

---

## 7. Fail-Open vs Fail-Closed

Following the principle from cli.md:

| Hook type | Failure behavior | Rationale |
|-----------|-----------------|-----------|
| **Observation** (PostToolUse, SessionStart, Notification, PreCompact, SessionEnd) | Fail-open (`\|\| true`) | If the tool crashes, Claude Code continues normally |
| **Mutation** (PreToolUse deny, Stop block) | Fail-closed (propagate error) | Safety: if the gate crashes, block the action |

Async hooks (Notification, PreCompact in some projects) are inherently
fail-open — they run in the background and their exit code is ignored.

---

## 8. Hook Registration

Plugins register hooks globally via `hooks.json` (below). Genuinely
repo-scoped hooks are registered by `<tool> enable` as additive
`<repo>/.claude/settings.json` entries and removed by `disable` via exact
value-match —
[tool-enable-disable.md § 2.8](tool-enable-disable.md#28-hooks-and-config).

### hooks.json structure

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<regex>",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/<script>.sh",
            "async": false
          }
        ]
      }
    ]
  }
}
```

### Matcher regex for dev/prod

Matchers must cover both dev and prod plugin namespaces:

```json
"matcher": "mcp__plugin_<tool>(-dev)?_<server>__.*"
```

### Async hooks

Use `"async": true` for fire-and-forget hooks that should not block
the event:

- Notification handlers (chimes, speech)
- PreCompact handlers (transcript capture)
- SessionEnd handlers (cleanup, farewell speech)

---

## 9. Cross-Tool Hook Coordination

Hooks from different plugins fire independently on the same event.
Order is not guaranteed. Design accordingly.

### Hook independence

- **No dependency between hooks**: Biff's SessionStart and quarry's
  SessionStart must not depend on each other's output.
- **Additive context only**: Multiple hooks can append to
  `additionalContext`. They must not conflict or overwrite.
- **Shared state via files**: If hooks need shared state, use the
  integration protocol (L3: state files). See
  [integration.md](integration.md).

### Building block hook ownership (DES-009)

When multiple plugins hook the same Claude Code event, each building
block owns its own sensory reaction. See
[DESIGN.md § DES-009](../DESIGN.md#des-009-building-block-hook-ownership)
for the full decision record.

**Rules:**

1. **Each building block reacts independently.** PR creation fires
   PostToolUse. Vox may speak. Biff may `/wall`. Quarry may ingest.
   These are parallel, additive reactions.
2. **Building blocks do not call each other for generic events.** Biff
   does not call vox to speak on PR creation. Vox speaks on its own.
3. **Consumers add domain-specific context.** Only z-spec can narrate
   "Model check: 10K states, all visited." Only quarry can compose
   search result tables for lux.
4. **File beads in the consumer, not the building block.** If biff
   wants a lux display on PR creation, the bead goes in biff. Lux has
   no upstream awareness.

### Activation asymmetry (DES-010)

Vox and lux have different activation semantics:

- **`/vox y`** activates vox's own behavior (Stop summary, chimes,
  signals). A user with only vox installed gets a working product.
- **`/lux y`** signals consumers to render visually. Lux has no
  default behavior — consumers must call `show()`.

---

## 10. Testing

### Unit tests

Every `handle_<event>()` function should have unit tests:

```python
def test_handle_post_bash_detects_test_pass():
    data = {"tool_input": {"command": "pytest"}, "tool_response": {"stdout": "5 passed"}}
    result = handle_post_bash(data)
    assert "tests-pass" in result
```

### Integration tests

Test the full dispatch chain: JSON stdin → shell script → CLI → handler → JSON stdout.

### Z specification verification

For hooks with complex state (decision-block, workflow gates), maintain
a Z specification that models the hook's state machine. Use probcli to
model-check that invariants hold:

```bash
make test  # Model-check all Z specs via probcli
```

Reference implementations:

- `z-spec/examples/claude-code-biff.tex` — Workflow gate (plan + bead)
- `z-spec/examples/claude-code-vox.tex` — Decision-block (Stop hook)
- `z-spec/examples/claude-code-quarry.tex` — Knowledge capture lifecycle

---

## 11. Common Bugs

Patterns found during Z specification audits across biff, vox, and
quarry:

| Bug | Project | Root Cause | Prevention |
|-----|---------|------------|------------|
| **Dead handler** | quarry | Python handler implemented but shell script never calls it | Audit: for every `handle_*()`, verify a shell script invokes it |
| **Missing registration** | quarry | Handler exists, hooks.json has no entry for the event | Audit: for every handler, verify hooks.json has the event + matcher |
| **Ghost states** | z-spec base | Free type declares states no operation uses | Model check: unreachable states cause deadlocks in ProB |
| **Unbounded accumulation** | vox | Vibe signals grow without pruning | Bound collections in the Z spec; implement pruning in handler |
| **Invariant too strict** | z-spec vox | `stopHookActive` cleared on wrong phase boundary | Model check catches immediately; fix invariant, re-verify |
| **Context overflow deadlock** | z-spec base | Context append exceeds maxContext bound | Truncate on append: `(1 ↟ max) ◁ (context ⌢ ⟨chunk⟩)` |
| **Silent deny reason** | biff | PreToolUse deny used `"reason"` instead of `"permissionDecisionReason"` — field silently ignored, agent sees generic denial with no self-correction instructions | Always use `"permissionDecisionReason"` (see § 6 workflow gate pattern). Test that deny output contains the field. See biff DES-026. |
| **Stdin hang on session resume** | biff, vox, lux | `sys.stdin.read()` blocks until EOF. Claude Code does not always close the stdin pipe for SessionStart resume/compact events, causing hooks to hang forever and freezing session load. Also triggered by "consume stdin" drain calls in handlers that discard the data. | Never use `sys.stdin.read()` in hooks. Use `os.read()` + `select` loop (see § 4). Remove stdin reads from handlers that don't use the data. Test with open-pipe-no-EOF regression test. See biff DES-027. |
| **Import tax on hook startup** | biff, quarry | Hook shell script calls `<tool> hook <event>`, routing through `__main__.py` and importing the full application (nats, pydantic, lancedb, etc.) before dispatching to a handler that only needs stdlib. Cold start: 1.5–4.7s per Python hook invocation. | Use a lightweight entry point (§ 12). Extract stdlib-only helpers. Make `__init__.py` lazy. See biff DES-028. |

---

## 12. Hook Startup Performance

Hooks are the hottest path in a Claude Code plugin. SessionStart hooks
fire on every session open and every resume. When multiple plugins each
spawn Python processes that import heavy dependency trees, the serial
cost can exceed 15 seconds — observed as the "Resuming conversation..."
hang.

### The import tax anti-pattern

The standard three-layer dispatch (§ 2) routes hook calls through the
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

### Measured impact (biff, M2 MacBook Air)

| Path | Cold Start |
|------|-----------|
| `biff hook claude-code session-start` (old) | 3.7s |
| `biff-hook claude-code session-start` (new) | 0.29s |
| **Ratio** | **13×** |

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

### Cross-product findings (2026-03-11)

| Product | SessionStart Python? | Cold Start | Status |
|---------|---------------------|-----------|--------|
| **biff** | Yes (2 hooks) | 4.7s → 0.43s | **Fixed** (v1.3.4, DES-028) |
| **quarry** | Yes (1 hook) | 1.47s | **Needs fix** — same pattern |
| **vox** | No (pure shell) | 0.1s | Already optimal |
| **lux** | Yes (lightweight) | 0.3s | Already near floor |

Quarry's `handle_session_start` imports `pydantic_settings` (1.9s),
`lancedb` (16.2s), `onnxruntime`, `pymupdf`, and `bs4` at module
level — but only needs `sqlite3` + `subprocess`. The same three-layer
fix applies.

---

## 13. Audit Checklist

For every Punt Labs plugin, verify:

- [ ] **hooks.json exists** with SessionStart and PostToolUse (output
  suppression) entries
- [ ] **Every shell script calls its Python handler** — no dead code
- [ ] **Every Python handler has a hooks.json registration** — no
  orphaned handlers
- [ ] **Observation hooks fail-open** (`|| true`)
- [ ] **Mutation hooks fail-closed** (propagate errors)
- [ ] **Matchers cover dev and prod** (`(-dev)?` regex)
- [ ] **Async flag set** on fire-and-forget hooks
- [ ] **Two-channel display** for all MCP tool output
- [ ] **No `sys.stdin.read()` in hook handlers** — use `os.read()` +
  `select` loop (see § 4). Grep for `stdin.read` in hooks.py.
- [ ] **No unnecessary stdin reads** — handlers that discard the data
  must not call `_read_hook_input()`
- [ ] **Open-pipe regression test exists** — test that reads stdin
  without EOF and returns within 200ms
- [ ] **Quality gates include hook tests** (`make test` runs handler
  unit tests)
- [ ] **SessionStart cold start < 1s** — measure with installed binary,
  not `uv run`. If > 1s, apply the three-layer fix (§ 12).
- [ ] **`_stdlib.py` has no third-party imports** — if the module
  exists, grep for non-stdlib imports. Any third-party import defeats
  the purpose.
- [ ] **Hook shell scripts use lightweight entry point** — if a
  `<tool>-hook` console script exists, verify `hooks/*.sh` calls it
  instead of `<tool> hook`
- [ ] **Security hooks exempt from kill-switch** — if a global
  kill-switch exists for emergency hook disable, PreToolUse authz
  gates must not honor it (they are security boundaries)
