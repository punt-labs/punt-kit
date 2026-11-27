# Hook Standards

**Updated:** 2026-11-27

Standards for Claude Code hook implementation across all Punt Labs projects.
Hooks integrate tools with Claude Code's lifecycle without containing
business logic themselves.

This standard consolidates hook guidance from
[CLI-10](cli.md#cli-10-keep-hook-dispatch-internal) (structure and
dispatch) and [plugins.md § Required Hooks](plugins.md#required-hooks)
(SessionStart and output suppression). Those sections remain as
cross-references; this document is the authoritative reference for hook
implementation. Each obligation is a `HOOK-<n>` clause; implementation rules
live in [Python](../lang-rules/python/python-hooks.md) and
[Go](../lang-rules/go/go-enablement.md).

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
| `claude-code-biff.tex` | Workflow gates (plan + issue) | No file edit without plan and issue claimed |
| `claude-code-vox.tex` | Stop hook decision-block | No infinite loop; exactly one block per turn |
| `claude-code-quarry.tex` | Knowledge capture lifecycle | WebFetch dedup; compaction flag tracking |

---

## 2. Architecture

### HOOK-1: Keep business logic out of hooks

**Applies to:** python, go

Hooks are plumbing, not product. They integrate the CLI with Claude
Code's lifecycle but do not contain business logic themselves.

### HOOK-2: Dispatch through registration, gate and handler

**Applies to:** python, go

```text
hooks.json          →  Shell script (thin gate)  →  CLI handler (business logic)
(registration)         (precondition check)          (pure function)
```

1. **hooks.json** — Declares which events to listen for and which
   scripts to run. Lives in `hooks/hooks.json` in the plugin root.
2. **Shell script** — Checks preconditions (config exists, tool
   enabled) and delegates to the CLI. Fails silently on error.
3. **CLI handler** — Pure function in the tool's hook module (`hooks.py`
   in Python) that takes structured input and returns structured output. Testable in
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

### HOOK-3: Keep shell gates thin

**Applies to:** python, go

Shell scripts are thin gates. They check preconditions and delegate to
the CLI. They must never contain business logic.

```bash
#!/usr/bin/env bash
# hooks/<event>.sh — Thin gate for <event> hook
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
P="$REPO_ROOT/.punt-labs"
[ -f "$P/<tool>/opt-out" ] && exit 0
[ -f "$P/local/<tool>/disabled" ] && exit 0
[ -f "$P/<tool>/enabled" ] || [ -f "$P/local/<tool>/enabled" ] || exit 0
<tool> hook <event> 2>/dev/null || true
```

- **Stdin passthrough**: Claude Code sends JSON on stdin. The shell
  script must pass it to the CLI handler (implicit via pipe or
  redirect). Do not consume stdin in the shell script.
- **Fail silently**: Use `2>/dev/null || true` for observation hooks.
  Only mutation hooks (PreToolUse denials) should propagate failures.
- **No business logic**: If the script is longer than 10 lines of
  non-boilerplate, the logic belongs in the handler.

### HOOK-4: Gate every hook on effective state

**Applies to:** python, go

- **Config gate**: Check the tool's effective state before dispatching:
  exit 0 when the opt-out (`.punt-labs/<tool>/opt-out`) or the personal
  `disabled` marker exists, or when neither the shared
  (`.punt-labs/<tool>/enabled`) nor the personal
  (`.punt-labs/local/<tool>/enabled`) marker does. The markers — not a
  repo-root dotfile — are the enabled signal
  ([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)).

### HOOK-5: Wire every gate to its handler

**Applies to:** python, go

Every shell script that delegates to a handler **must actually
call the handler**. Pattern:

```bash
# CORRECT: shell invokes the handler
<tool> hook <event> < /dev/stdin

# WRONG: shell only does setup, the handler is dead code
```

**Audit checklist**: For every handler function (`handle_<event>()`
in Python), verify that a shell script in `hooks/` calls it via the CLI
dispatcher. Dead handlers are invisible bugs.

---

## 4. Handler Pattern

### HOOK-6: Write handlers as pure functions that never crash

**Applies to:** python, go

Business logic lives in the tool's hook module as pure functions
([PY-HOOK-1](../lang-rules/python/python-hooks.md) gives the Python form).

- **Pure functions**: Take the parsed event payload and return the context
  to inject, or nothing. No side effects except logging and config file
  writes.
- **Structured input**: Read from the payload the dispatcher passes, not
  from stdin directly.
- **Graceful degradation**: An observation handler catches all errors and
  returns an empty result, because a crashing hook blocks Claude Code. A
  mutation handler fails closed instead (HOOK-16).
- **Testable**: Every handler has unit tests that pass payloads and assert
  on return values.

### HOOK-7: Block only when the return value drives a decision

**Applies to:** python, go

The handler should only do synchronous (blocking) work when the
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
(Claude Code) needs the return value to proceed. Public command success
semantics are defined separately in [CLI-18](cli.md#cli-18-define-what-success-means-for-each-command).

For side-effect handlers, start the side effect as a detached process or
background task and return without waiting for it
([PY-HOOK-2](../lang-rules/python/python-hooks.md)).

The hook registration's `async` flag controls whether **Claude Code**
waits for the shell script to exit. The handler's blocking behavior
controls whether the **handler process** waits for side effects. Both
should be non-blocking when the return value isn't needed — they are
independent knobs at different layers of the dispatch chain.

### HOOK-8: Never block waiting for stdin to close

**Applies to:** python, go

Claude Code pipes JSON to hook subprocesses but does not always close the
pipe promptly, so a read that waits for EOF hangs indefinitely and freezes
session resume and startup. A hook reads stdin with a short readiness
timeout and takes the bytes available; it never does a blocking
read-to-EOF.

A handler that does not use the payload does not read stdin at all:
draining it "to avoid pipe backpressure" is the exact vector for the hang.

Every project that reads stdin in hooks has a regression test that writes a
payload, leaves the pipe open without EOF, and asserts the read returns
promptly. Python: [PY-HOOK-3](../lang-rules/python/python-hooks.md).

### HOOK-9: Expose handlers as hidden `hook` subcommands

**Applies to:** python, go

The CLI exposes hook handlers as hidden subcommands, `<tool> hook <event>`:
commands called by hooks, internal and not for direct use
([CLI-10](cli.md#cli-10-keep-hook-dispatch-internal)). Python:
[PY-HOOK-4](../lang-rules/python/python-hooks.md).

---

## 5. Required Hooks

Every Punt Labs Claude Code plugin must implement these hooks. See
[plugins.md § Required Hooks](plugins.md#required-hooks) for the full
specification. Repo-scoped hook deposit and removal via `<tool> enable` /
`disable` — additive entries in `<repo>/.claude/settings.json`, reversed by
exact value-match — follow
[tool-enable-disable.md § 2.8](tool-enable-disable.md#28-hooks-and-config).

### HOOK-10: Set up at SessionStart without editing settings

**Applies to:** python, go

Setup hook that runs on every session start. Must:

1. Deploy top-level commands (diff-and-copy, not skip-if-exists)
2. Run any first-time setup
3. Emit `hookSpecificOutput` with `additionalContext`

It never edits a settings file: permission rules come from `<tool> enable`
([permissions.md § 6](permissions.md#6-plugin-distributed-permissions)).

An engine that holds per-session state also opens its engine session here,
and its PreToolUse hook stamps the caller on its MCP tool calls:
[mcp-caller-identity.md § 3–4](mcp-caller-identity.md).

### HOOK-11: Format the output of every MCP tool

**Applies to:** python, go

Every MCP tool must have a corresponding handler in
`suppress-output.sh` that formats output for the UI panel. Missing
handlers cause raw JSON to leak into the conversation.

Pattern: two-channel display — compact summary in
`updatedMCPToolOutput`, full data in `additionalContext`.

---

## 6. Hook Event Patterns

Patterns verified by Z specification model checking.

### HOOK-12: Never block from an observation hook

**Applies to:** python, go

These hooks observe state and inject context. They must never block.

| Event | Matcher | Pattern | Example |
|-------|---------|---------|---------|
| SessionStart | * | Load state, inject guidance | Wall text, collision detection, project standards |
| PostToolUse | Bash | Classify output, accumulate signals | Vibe signals, plan hints |
| PostToolUse | `mcp__linear__save_issue` | Detect an issue claim from the tool input (status In Progress) | Issue claim detection |
| PostToolUse | WebFetch | Capture side effect | Auto-ingest fetched URLs into knowledge base |
| PostToolUse | Edit\|Write | Inject relevant standards | Changelog format, Z spec conventions |
| PostToolUse | MCP tools | Format output | Two-channel display (suppress-output.sh) |
| PreCompact | * | Preserve state before compaction | Capture session transcript as searchable notes |
| SessionEnd | * | Cleanup | Clear session markers, reset signals |
| Notification | permission\|idle | Alert user | Chime or spoken notification |

### HOOK-13: Use blocking hooks sparingly

**Applies to:** python, go

These hooks can prevent an action. Use sparingly — blocking hooks that
fail can deadlock Claude Code.

| Event | Matcher | Pattern | Example |
|-------|---------|---------|---------|
| PreToolUse | Edit\|Write | Workflow gate | Require plan + issue before file edits |
| Stop | * | Decision-block | Speak summary before allowing stop |

### HOOK-14: Block a Stop hook at most once per turn

**Applies to:** python, go

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

### HOOK-15: Give every denial a `permissionDecisionReason`

**Applies to:** python, go

A PreToolUse hook can deny a tool call based on workflow state. The
denied tool call's reason is injected into context, and Claude
self-corrects.

```text
1. Claude decides to call Edit → PreToolUse fires
2. Hook checks: plan set? issue claimed?
3. If missing: return permissionDecision: "deny" with reason
4. Claude sees denial, sets plan/claims issue, retries
```

**Implementation pattern**:

```python
def handle_pre_tool_use(data: dict) -> dict | None:
    if not is_plan_set():
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Set a plan with /plan before editing files.",
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

### HOOK-16: Fail open on observation and closed on mutation

**Applies to:** python, go

Following the principle from cli.md:

| Hook type | Failure behavior | Rationale |
|-----------|-----------------|-----------|
| **Observation** (PostToolUse, SessionStart, Notification, PreCompact, SessionEnd) | Fail-open (`\|\| true`) | If the tool crashes, Claude Code continues normally |
| **Mutation** (PreToolUse deny, Stop block) | Fail-closed (propagate error) | Safety: if the gate crashes, block the action |

Async hooks (Notification, PreCompact in some projects) are inherently
fail-open — they run in the background and their exit code is ignored.

A PreToolUse hook that stamps caller identity on its own MCP tools is a
mutation hook for those tools and fails closed there
([mcp-caller-identity.md § 3.1](mcp-caller-identity.md)). Opening an engine
session from SessionStart stays fail-open, because the PreToolUse hook opens
the session itself when SessionStart has not.

---

## 8. Hook Registration

### HOOK-17: Register plugin hooks in hooks.json and repo hooks through enable

**Applies to:** python, go

Plugins register hooks globally via `hooks.json` (below). Genuinely
repo-scoped hooks are registered by `<tool> enable` as additive
`<repo>/.claude/settings.json` entries and removed by `disable` via exact
value-match —
[tool-enable-disable.md § 2.8](tool-enable-disable.md#28-hooks-and-config).

#### hooks.json structure

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

### HOOK-18: Match both dev and prod plugin namespaces

**Applies to:** python, go

Matchers must cover both dev and prod plugin namespaces:

```json
"matcher": "mcp__plugin_<tool>(-dev)?_<server>__.*"
```

### HOOK-19: Mark fire-and-forget hooks async

**Applies to:** python, go

Use `"async": true` for fire-and-forget hooks that should not block
the event:

- Notification handlers (chimes, speech)
- PreCompact handlers (transcript capture)
- SessionEnd handlers (cleanup, farewell speech)

---

## 9. Cross-Tool Hook Coordination

Hooks from different plugins fire independently on the same event.
Order is not guaranteed. Design accordingly.

### HOOK-20: Keep hooks independent of one another

**Applies to:** python, go

- **No dependency between hooks**: Biff's SessionStart and quarry's
  SessionStart must not depend on each other's output.
- **Additive context only**: Multiple hooks can append to
  `additionalContext`. They must not conflict or overwrite.
- **Shared state via files**: If hooks need shared state, use the
  integration protocol (L3: state files). See
  [integration.md](integration.md).

### HOOK-21: Let each building block own its reaction (DES-009)

**Applies to:** python, go

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
4. **File issues in the consumer, not the building block.** If biff
   wants a lux display on PR creation, the Linear issue carries biff's
   repo label. Lux has
   no upstream awareness.

### Activation asymmetry (DES-010)

Vox and lux have different activation semantics:

- **`/vox y`** activates vox's own behavior (Stop summary, chimes,
  signals). A user with only vox installed gets a working product.
- **`/lux y`** signals consumers to render visually. Lux has no
  default behavior — consumers must call `show()`.

---

## 10. Testing

### HOOK-22: Unit-test every handler

**Applies to:** python, go

Every handler has unit tests. In Python, for `handle_<event>()`:

```python
def test_handle_post_bash_detects_test_pass():
    data = {
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": "5 passed"},
    }
    result = handle_post_bash(data)
    assert "tests-pass" in result
```

### HOOK-23: Test the full dispatch chain

**Applies to:** python, go

Test the full dispatch chain: JSON stdin → shell script → CLI → handler → JSON stdout.

### HOOK-24: Model-check hooks with complex state

**Applies to:** python, go

For hooks with complex state (decision-block, workflow gates), maintain
a Z specification that models the hook's state machine. Use probcli to
model-check that invariants hold:

```bash
make test  # Model-check all Z specs via probcli
```

Reference implementations:

- `z-spec/examples/claude-code-biff.tex` — Workflow gate (plan + issue)
- `z-spec/examples/claude-code-vox.tex` — Decision-block (Stop hook)
- `z-spec/examples/claude-code-quarry.tex` — Knowledge capture lifecycle

---

## 11. Common Bugs

Failure modes the clauses above prevent:

| Bug | Root Cause | Prevention |
|-----|------------|------------|
| **Dead handler** | Python handler implemented but shell script never calls it | Audit: for every `handle_*()`, verify a shell script invokes it |
| **Missing registration** | Handler exists, hooks.json has no entry for the event | Audit: for every handler, verify hooks.json has the event + matcher |
| **Ghost states** | Free type declares states no operation uses | Model check: unreachable states cause deadlocks in ProB |
| **Unbounded accumulation** | Vibe signals grow without pruning | Bound collections in the Z spec; implement pruning in handler |
| **Invariant too strict** | `stopHookActive` cleared on wrong phase boundary | Model check catches immediately; fix invariant, re-verify |
| **Context overflow deadlock** | Context append exceeds maxContext bound | Truncate on append: `(1 ↟ max) ◁ (context ⌢ ⟨chunk⟩)` |
| **Silent deny reason** | PreToolUse deny used `"reason"` instead of `"permissionDecisionReason"` — field silently ignored, agent sees generic denial with no self-correction instructions | Always use `"permissionDecisionReason"` (HOOK-15). Test that deny output contains the field. See biff DES-026. |
| **Stdin hang on session resume** | `sys.stdin.read()` blocks until EOF. Claude Code does not always close the stdin pipe for SessionStart resume/compact events, causing hooks to hang forever and freezing session load. Also triggered by "consume stdin" drain calls in handlers that discard the data. | Never use `sys.stdin.read()` in hooks. Read with a readiness timeout (HOOK-8). Remove stdin reads from handlers that don't use the data. Test with open-pipe-no-EOF regression test. See biff DES-027. |
| **Import tax on hook startup** | Hook shell script calls `<tool> hook <event>`, routing through `__main__.py` and importing the full application (nats, pydantic, lancedb, etc.) before dispatching to a handler that only needs stdlib. Cold start: 1.5–4.7s per Python hook invocation. | Load only what the handler needs (HOOK-25). Extract stdlib-only helpers. Make `__init__.py` lazy. See biff DES-028. |

---

## 12. Hook Startup Performance

### HOOK-25: Load only what the handler needs on the hook path

**Applies to:** python, go

Hooks are the hottest path in a Claude Code plugin. SessionStart hooks fire
on every session open and every resume; when several plugins each start a
process that loads a heavy dependency tree, the serial cost can exceed 15
seconds — the "Resuming conversation..." hang. A hook's entry path loads
only what its handler needs, not the full application, and SessionStart
cold start, measured with the installed binary rather than a development
runner, stays under one second. Git hooks (`.git/hooks/`) are off the
latency-critical path and may use the full CLI. Python:
[PY-HOOK-5](../lang-rules/python/python-hooks.md).

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
  `select` loop (HOOK-8, PY-HOOK-3). Grep for `stdin.read` in hooks.py.
- [ ] **No unnecessary stdin reads** — handlers that discard the data
  must not call `_read_hook_input()`
- [ ] **Open-pipe regression test exists** — test that reads stdin
  without EOF and returns within 200ms
- [ ] **Quality gates include hook tests** (`make test` runs handler
  unit tests)
- [ ] **SessionStart cold start < 1s** — measure with installed binary,
  not `uv run`. If > 1s, apply HOOK-25 (Python: PY-HOOK-5).
- [ ] **`_stdlib.py` has no third-party imports** — if the module
  exists, grep for non-stdlib imports. Any third-party import defeats
  the purpose.
- [ ] **Hook shell scripts use lightweight entry point** — if a
  `<tool>-hook` console script exists, verify `hooks/*.sh` calls it
  instead of `<tool> hook`
- [ ] **Security hooks exempt from kill-switch** — if a global
  kill-switch exists for emergency hook disable, PreToolUse authz
  gates must not honor it (they are security boundaries)
