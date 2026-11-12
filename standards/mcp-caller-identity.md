# MCP Caller Identity Standards

**Introduced:** 2026-11-04

Decision record: [DESIGN.md DES-037](../DESIGN.md).

How a Punt Labs engine learns which Claude Code session, and which agent
inside it, is calling — on every client surface that session uses: MCP tool
calls, hooks, and applets. [architecture.md](architecture.md) invariant 4
requires client state to live in the engine, keyed by client; this document
says where the key comes from when the client is a Claude Code session.

ethos (DES-074) is the source of the hook rules in § 3.1. § 8 states each
engine's channel contract under this standard: which process is the engine,
which layer it implements, what carries `_caller`, and what the handle keys.

---

## 1. The Problem, Measured

Measured against Claude Code 2.1.309, headless `claude -p`, over streamable
HTTP, with a logging MCP server (fastmcp 3.4.11 and 4.1.6) and logging hooks,
2026-11-04. stdio servers were not measured.

| Fact | Evidence |
|---|---|
| A `tools/call` names no session and no agent. In the handshake era its `_meta` is `{claudecode/toolUseId, progressToken}`; in the stateless era `_meta` adds the protocol version, `clientInfo`, and client capabilities. None identifies a session or agent. | Raw request bodies, both eras |
| An MCP server's environment carries no documented session variable, and the documented `${VAR}` expansions in `url`, `headers`, and `headersHelper` include none. `CLAUDE_PID` does not reach MCP servers; `CLAUDE_CODE_MESSAGING_SOCKET` does, and encodes a process id, not a session (ethos DES-074). | Claude Code MCP docs; ethos DES-074 |
| A subagent uses its leader's MCP connection: leader and subagent sent the same `Mcp-Session-Id` (handshake era). Two parallel subagents in the stateless era sent no connection id at all and differed only in the hook's `agent_id`. | Request headers; PreToolUse payloads |
| The connection id changes on every reconnect. Claude Code reconnected on its own about 2 s after a server restart, with a new `Mcp-Session-Id` and the same caller. | Request headers across a restart |
| Claude Code sends `server/discover` (protocol 2026-07-28) first. fastmcp 4.1.6 accepted it and the session stayed stateless: no `initialize`, no `Mcp-Session-Id`. fastmcp 3.4.11 did not, and Claude Code then sent `initialize` (2025-11-25). | Request sequence on each server |
| Every hook payload carries `session_id`; a subagent's payload adds `agent_id` and `agent_type`. `CLAUDE_PID` is set in the hook's environment. | Hook payload log |
| `session_id` is unchanged across `claude --resume`; SessionStart fires again with `source: "resume"`; the main thread's `CLAUDE_PID` changes (a resumed session is a new process). | Hook payloads before and after resume |
| SessionEnd fired at the end of each headless run (`reason: "other"`). A file written by the SessionStart hook was readable by PreToolUse (leader and subagent), SubagentStop, and Stop, and removed by SessionEnd. | Handoff spike logs |
| OAuth does not identify the session or agent. An MCP access token authorizes a resource owner through a client, is audience-bound to one server, and is stored per endpoint and reused across sessions. | MCP spec 2025-11-25 § Authorization; Claude Code MCP docs |

Consequences:

- **The connection is not an identity.** It is shared by the leader and every
  subagent, replaced on reconnect, and absent in the stateless protocol.
- **The process is not an identity.** A stdio server is one process per
  session, shared by every subagent; the main thread's pid changes on resume.
- **Hooks are the only place Claude Code states who is acting.** This standard
  moves that fact into every call the session makes.
- **Authorization and identity are separate concerns.** OAuth answers "may this
  user, through this app, use this server". This standard answers "which
  session and which agent is calling". An engine may need both.

---

## 2. Terms

| Term | Meaning |
|---|---|
| **Caller facts** | `session_id` and `agent_id`, stated by Claude Code to hooks and never invented by the engine. |
| **Main thread** | The leader of a session. Its payloads carry no `agent_id` (a payload with `agent_type` but no `agent_id` is still the main thread, as under `claude --agent`). |
| **Main-thread agent id** | The hook's corroborated `CLAUDE_PID`: the pid in `CLAUDE_PID`, accepted only if that process is a live ancestor of the hook (ethos's check). It identifies the current process, so it changes on resume. |
| **Engine session** | The engine's own record of one Claude Code session: the state it holds for that caller, its lease, and its handle. At most one live record exists per `session_id`. |
| **Handle** | The engine-issued reference to an engine session, opaque to every client. |
| **Session client** | Any process acting for a Claude Code session against an engine: the MCP leg, the plugin's hooks, and applets the session spawns. |
| **`_caller`** | The reserved argument that carries caller facts on an MCP tool call; under layer 2 it adds `handle` and `main_agent_id` (§ 4.2.5). |

---

## 3. Layer 1 — Caller Facts on Every Call (Required)

Every engine that needs to know who is calling implements this layer.

### 3.1 The hook

The plugin's PreToolUse hook stamps `_caller` on its own server's tools under
every name Claude Code gives them: the plugin registration, the `-dev` plugin
registration, and a direct registration (for example
`mcp__(plugin_lux(-dev)?_)?lux__.*`). A direct registration is matched only
under the server name the plugin documents; a user who registers the server
under another name gets no stamping, and the engine's refusal (§ 3.2.3) names
the documented name. A hook may match more tools than that —
ethos matches every tool because it also gates them — but it stamps only its
own. It returns `updatedInput`: the original arguments plus

```json
{"_caller": {"session_id": "<payload session_id>", "agent_id": "<agent id>"}}
```

1. `agent_id` is the payload's `agent_id` for a subagent, otherwise the
   main-thread agent id (§ 2).
2. The hook **always overwrites** a `_caller` the model supplied.
3. If the hook cannot determine `session_id` or an agent id, it returns
   `updatedInput` with `_caller` **removed**, so a model-written value never
   reaches the server.
4. The hook **never returns `permissionDecision: "allow"`**. Its output type
   holds `deny` or no decision; `allow` would bypass the user's permission
   rules for every matched call.
5. For the tools it stamps, the hook **fails closed**: a payload it cannot read
   or parse is denied with the cause in the reason. For any other tool it
   matches, a hook failure leaves the call untouched.
6. The hook reads its whole payload per [hooks.md](hooks.md) and stays light:
   a stdlib-only Python hook measured 0.02 s wall time per invocation.
7. The hook honors the org kill switch like any other hook. With the stamping
   hook killed or absent, calls arrive without `_caller` and the engine
   refuses them (§ 3.2.3), naming the cause. The engine cannot tell a stamped
   `_caller` from one the model wrote itself while no hook was running; the
   hook prevents that forgery only while it runs. That is acceptable because
   `_caller` routes rather than authenticates (§ 4.4).

### 3.2 The server

1. **Strip before validation.** `_caller` is removed from the arguments before
   tool argument validation (fastmcp 4: a `Middleware.on_call_tool`). No tool
   schema declares it, so agents never see it. Measured: adding `_caller` to a
   tool whose schema does not declare it fails the call with
   `Unexpected keyword argument` unless the server strips it. A server whose
   framework cannot strip (ethos, in Go) may declare `_caller` on each tool;
   the observable contract is the same.
2. **One source for Claude Code callers.** A call carrying `_caller` is
   identified by `_caller` alone — never by the transport, the connection, the
   process tree, the environment, git, or the OS user.
3. **Refuse an unidentified call.** A tool call that carries neither `_caller`
   nor the engine's documented credential for another client type (for
   example OpenCode's `_meta`, or a CLI/REST identity on a non-MCP surface) is
   refused with a named error that lists the likely causes (the stamping hook
   is not installed, disabled, or killed). The engine does not try to detect
   Claude Code to decide whether `_caller` was owed: every client type has a
   declared channel, and a call with none is unidentified. An engine may
   exempt tools it declares caller-free — diagnostics such as ethos's
   `doctor`, which must still answer when the stamping hook is the thing that
   is broken. A caller-free tool reads and writes no per-session or per-agent
   state.
4. **Validate the shape.** `session_id` and `agent_id` (and, under layer 2,
   `handle` and `main_agent_id`) are non-empty and match `[A-Za-z0-9_-]+`.
   Anything else is a named error.
5. **Work in the stateless protocol.** No identity rides on the connection, so
   a conforming engine accepts the 2026-07-28 era. On streamable HTTP that
   requires fastmcp 4 or later (fastmcp 3 does not serve it). An engine must
   not refuse the era to keep a connection-scoped identity.

### 3.3 Hooks and applets are session clients too

A hook receives `session_id` and `agent_id` in its payload, so a hook calling
its engine sends them directly, in the same shape as `_caller`. An applet
spawned by a SessionStart hook receives the caller facts (and, under layer 2,
the handle) from that hook at spawn time.

---

## 4. Layer 2 — Engine-Owned Sessions

### 4.1 When it applies

An engine implements layer 2 when it holds **any per-session or per-agent
state for its callers** — under architecture.md invariant 4, any engine that
holds client state. Machine-global state with no owner (vox's music, DES-041)
does not count. Only an engine that holds nothing per caller stops at layer 1.

Caller facts identify a Claude Code session; layer 2 makes the engine the
authority on its own record of it. Identity stays caller-declared; only the
handle is engine-issued.

### 4.2 Lifecycle

**Scope: this is a daemon-tier concern.** The stateful session-record
lifecycle below — get-or-create by `session_id`, the live/dormant/ended
record states, resume reviving a record and preserving its handle — presupposes
a long-lived engine that *holds* records across calls. That is a daemon. Per
[architecture.md's daemon-deferral criteria](architecture.md#bounded-choices-product-judgment),
a daemon is required only once clients share mutable state, contend for a
device, or run concurrently, and is deferrable before that. A **daemonless**
tool holds no cross-call record: it resolves caller identity per invocation
from the facts on that call (§ 3) and has nothing to keep live, make dormant,
or revive. It adopts this full lifecycle only when it grows a daemon — the same
point architecture.md defers the daemon to. The spec below is the contract for
that daemon-tier engine; it is not mandatory for a daemonless tool.

The engine-session lifecycle is model-checked: a Z specification,
[mcp-caller-identity-lifecycle.tex](mcp-caller-identity-lifecycle.tex), proves
the invariants below with ProB over every reachable state (95,929 states, no
violation, no deadlock), and six fidelity controls reproduce the defects
earlier drafts of this section had
([report](mcp-caller-identity-lifecycle.md)). The rules here are the model's;
a change to them changes the model first.

A record is **live**, **dormant**, or **ended**; a session with no record is
**absent**. Every record carries a handle, the session's durable state, its
live-client resources (callbacks, subscriptions, pending deliveries), and its
**current main pid** — the main-thread agent id of the session's latest run.
Durable state belongs to the session; live-client resources belong to the
**run** that registered them.

1. **Get-or-create by `session_id`.** Open, and any call presenting a handle
   the engine does not hold, resolve by `session_id`: if a record exists for
   it in **any** state — live, dormant, or ended — that record is used and
   made live; otherwise the engine creates one, with no live-client
   resources and empty durable state. The engine never holds two records for
   one `session_id`. A presented handle never selects another session's
   record: one that belongs to a different session is treated as unknown,
   and a record created for an unknown handle uses the presented handle only
   if no record owns it, otherwise a fresh one (model control
   `_handlecollide_buggy`).
2. **Every open and every call sets the current main pid** to the caller's
   `main_agent_id`. A resume's first call may arrive before (or without) its
   SessionStart, so updating the pid on open alone is not enough: with it,
   a late SessionEnd from the replaced run still ends the resumed record
   (model control `_nopincall_buggy`). The engine keeps, per `session_id`,
   every main pid that has run for the session — independent of the record,
   so it outlives a record's retention expiry (the model's `ever`). An engine
   that drops this history may do so only after the session has been absent
   longer than its retention period, and then a late call from a replaced run
   is indistinguishable from a new session. An open or call whose
   `main_agent_id` is one of
   those but not the current one comes from a **replaced run**: the engine
   refuses it with a named error and never moves the pin back. An open or
   call whose `main_agent_id` has never run for the session is a **new run**:
   the engine
   releases the previous run's live-client resources before the record goes
   live, and durable state carries over. A crash fires no SessionEnd, so the
   next run's arrival is what releases a dead run's callbacks and
   subscriptions (model control `_runres_buggy`).
3. **Who opens.** The SessionStart hook opens, on every `source` (`startup`,
   `resume`, and the rest). SessionStart hooks are fail-open and may run
   asynchronously ([hooks.md](hooks.md) § 7), so any session client that finds
   no handle file opens instead — in practice the PreToolUse hook on the
   session's first tool call, which runs before that call.
4. **Store.** The opener writes the handle to
   `~/.punt-labs/<tool>/sessions/<session_id>/handle`, mode `0600`, in
   directories with mode `0700`, through a temporary file renamed into place.
   `session_id` comes from a hook payload, so it is checked against
   `[A-Za-z0-9_-]+` (§ 3.2.4) before it is used in a path; a value that fails
   is treated as missing facts.
5. **Present.** Every session client presents the handle, its caller facts,
   and `main_agent_id`: the PreToolUse hook adds `"handle"` and
   `"main_agent_id"` to `_caller`; other hooks read the file and send the same
   values directly; applets receive them at spawn. Every hook can compute
   `main_agent_id` (the corroborated `CLAUDE_PID`).
6. **Renew; a lapse is dormancy.** Every call renews the lease. The lease
   measures abandonment, not activity, so its TTL is hours, and an applet that
   lives as long as the session renews it on the session's behalf. A lapse
   moves a live record to **dormant** and keeps its live-client resources,
   because dormancy is the same run being quiet: the next call from that run
   revives it with nothing to re-establish.
7. **SessionEnd ends a record only for the current run.** SessionEnd
   presents its `main_agent_id`; the engine ends the record (live or dormant
   to **ended**) only if that equals the record's current main pid, and
   ending an ended record changes nothing. A late SessionEnd from a run that a
   resume has replaced ends nothing (model controls `_nopin_buggy`,
   `_noguard_buggy`). Ending releases live-client resources and keeps durable
   state.
8. **Resume after an end.** Get-or-create revives an ended record with its
   handle and durable state but no live-client resources: the new run's
   clients register their callbacks and subscriptions. Nothing is restored.
9. **Expire.** Retention is the only rule that drops durable state. A
   dormant or ended record whose retention period has run (from the lapse or
   the end) is removed, and the hook's directory goes with it on the next
   open or a periodic sweep. SessionEnd does not fire on a crash; a crashed
   session goes dormant at its lease lapse and expires after retention.
10. **Unknown handles never error.** Rule 1 resolves them and the engine logs
    it, because a PreToolUse hook never sees the tool's result and could not
    act on an error. State lost to an engine restart without persistence stays
    lost; the session keeps working and never splits.

The model enables an open or call only for the current run or a run that has
never been seen for the session (its `PidOk` guard over the pids that have
run); rule 2's refusal of a replaced run is that guard, implemented from the
per-session pid history the engine keeps.

### 4.3 Per-agent state

The engine scopes state below the session by agent. A call whose `agent_id`
equals its `main_agent_id` is the main thread; any other is a subagent. A
subagent's state is keyed by its `agent_id`. The main thread's state is held
at the session level, not under the main-thread agent id, because that id
changes on every resume.

### 4.4 The handle

The handle is either an opaque engine-issued value or the caller facts
themselves (the ethos roster model). Either way it is **routing, not
authentication**: every process of the same user can read
`~/.punt-labs/<tool>/sessions/`, so a handle does not keep one same-user
process from acting as another session. What it adds is engine authority — the
engine, not the client, names its sessions, and a handle that names no live
record is caught. The trust boundary for a local engine stays the loopback
bind and same-user access. An engine reachable across hosts or across users
adds real authentication on its transport (and, where it exposes protected
resources, OAuth per the MCP spec), records the authenticated principal on
each engine session at open, and resolves a `session_id` or handle only for
that same principal — so one user cannot open, resume, or re-create another
user's session by naming its `session_id`.

---

## 5. Not Acceptable

- Keying caller state on `Mcp-Session-Id`, a transport connection, or a
  per-process UUID.
- A random identity minted per connection, per request, or per process.
- Deriving a Claude Code caller's identity from the process tree, from the MCP
  server's environment, or by parsing `CLAUDE_CODE_MESSAGING_SOCKET`.
- Keying durable main-thread state on the main-thread agent id (§ 4.3).
- Refusing the stateless protocol to preserve a connection-scoped identity.
- Splitting one session's state across files, hook processes, and MCP process
  memory with no single owner.
- A PreToolUse hook that returns `allow`.

---

## 6. Conformance Tests

**Engine**, at the wire boundary:

1. A call with a well-formed `_caller` resolves the caller; under layer 2, the
   engine session too.
2. A call with neither `_caller` nor another declared credential is refused
   with the named error.
3. A malformed `_caller` (missing key, bad characters) is a named error.
4. A tool whose schema does not declare `_caller` succeeds with one present,
   and the tool never receives it.
5. Caller resolution is identical in the stateless and handshake protocols.
6. Layer 2, one test per model invariant and per fidelity control
   (§ 4.2): open twice for one `session_id` yields one record; an unknown
   handle resolves to an existing live, dormant, or ended record, or creates
   one, and never a second; every open and call sets the current main pid;
   a lapse keeps live-client resources; SessionEnd from the current run ends
   the record and a late SessionEnd from a replaced run (before and after the
   new run's first call) does not; a resume revives an ended record with its
   durable state and no resources; a new run releases the previous run's
   resources; a handle owned by another session never selects or overwrites
   that session's record; retention expiry removes it. A multi-user engine resolves a
   session only for the principal that opened it.
7. Layer 2: a subagent's state is separate from the main thread's, and the
   main thread's state survives a change of `main_agent_id`.

**Hook**:

1. Stamps the payload's `agent_id` for a subagent and the corroborated
   `CLAUDE_PID` for the main thread, including a payload with `agent_type`
   and no `agent_id`.
2. Overwrites a model-supplied `_caller`; removes it when facts are missing.
3. Stamps every registration name of its server and no other tool.
4. Denies an unreadable payload for its stamped tools; passes other matched
   tools through untouched.
5. Never emits `allow`.
6. Layer 2: opens when no handle file exists, writes it with modes
   `0600`/`0700`, adds `handle` and `main_agent_id` to `_caller`, and
   SessionEnd ends the engine session without deleting the handle a resume
   will need.

---

## 7. Relation to Other Standards

- [architecture.md](architecture.md) invariant 4 — client state lives in the
  engine, keyed by client. This standard supplies the key.
- [hooks.md](hooks.md) — hook structure, stdin handling, fail-open/fail-closed,
  kill switch; § 3.1 and § 4.2 add the stamping and handle duties.
- [integration.md](integration.md) — tools coordinate without hard
  dependencies. Each plugin ships its own conforming hook; no engine depends on
  another tool's hook to identify its callers.
- [filesystem.md](filesystem.md) — `sessions/` is the reserved subdirectory
  for per-session handle directories.
- [python.md](python.md) — standalone fastmcp is the server framework; § 3.2.5
  needs fastmcp 4 for streamable HTTP servers. python.md's dependency example
  moves to fastmcp 4 when the first engine ships on it.

---

## 8. Applications

### 8.1 ethos — the source of the hook rules

ethos resolves the caller's `session_id` and `agent_id` to the exact
participant in the session roster: the persona a call acts as, the mission a
delegation belongs to, and the gate on each tool. ethos is daemonless
(§ 4.2): the engine is the `ethos serve` MCP process over stdio, which
resolves each call from the facts on that call, and the handle is the caller
facts themselves (§ 4.4). The roster at
`~/.punt-labs/ethos/sessions/<session_id>.yaml` is keyed by `session_id`,
with participants keyed by `agent_id`; no handle file (§ 4.2.4) exists
because there is no engine-issued handle to store. ethos is written in Go and
declares `_caller` on each tool rather than stripping it (§ 3.2.1). Caller
identity arrives on a per-client declared channel, never by detecting the
harness:

- **Claude Code** — the PreToolUse hook stamps `_caller` via `updatedInput`
  under the matcher `mcp__plugin_ethos(-dev)?_self__.*`. The hook matches every
  tool because it also gates them, and stamps only its own (§ 3.1).
- **OpenCode** — MCP `params._meta["ai.opencode/sessionID"]`; session and
  agent are the same id.
- **CLI** — `ETHOS_SESSION` and `ETHOS_AGENT_ID` in the process environment,
  the declared credential for the non-MCP surface (§ 3.2.3).

An MCP call carrying none of these is refused with the named error; `doctor`
is the caller-free diagnostic (§ 3.2.3).

### 8.2 lux — an engine whose sessions own UI

lux resolves the caller to the Hub session that owns its scenes,
subscriptions, and menu entries. The Hub (luxd) is the engine and a layer-2
engine (§ 4.1): it holds per-session UI state, so it owns engine sessions and
issues an opaque handle; the Display only renders and plays no part in
identity. The handle keys the Hub's `Scope`, and an agent sub-scope keyed by
`agent_id` gives each subagent its own scenes (§ 4.3). Caller identity
arrives on a declared channel, never from the transport session key:

- **Claude Code** — the PreToolUse hook stamps `_caller` (the facts, the
  handle, and `main_agent_id`) via `updatedInput` under the matcher
  `mcp__(plugin_lux(-dev)?_)?lux__.*`; Hub middleware strips it and resolves
  the `Scope`.
- **Hooks and applets** — the SessionStart hook opens the Hub session over
  REST, stores the handle (§ 4.2.4), and passes it to the applets it spawns;
  every hook and applet presents the same handle (§ 3.3).

The Hub accepts the stateless protocol; lease renewal on each call and
SessionEnd, not connection close, bound a session's resources (§ 4.2.6–7).
Identity stays declared and the handle is keyed by `session_id`, never by a
connection (lux DES-057).

### 8.3 vox — an engine whose sessions own a voice

vox resolves the caller to the session whose voice, vibe, and conversation it
serves. voxd is the engine and a layer-2 engine (§ 4.1): it owns session
state (vibe, voice override) keyed by the handle, scoped per agent so each
subagent's voice resolves from its ethos persona (§ 4.3); repo defaults stay
in `vox.md`. Caller identity arrives on a declared channel:

- **Claude Code** — the PreToolUse hook stamps `_caller` via `updatedInput`
  under the matcher `mcp__(plugin_vox(-dev)?_)?mic__.*`; the server strips it
  with standalone fastmcp middleware ([python.md](python.md), § 3.2.1).
- **Hooks** — the Stop, SubagentStop, and Notification hooks that drive
  speech present the handle and facts directly (§ 3.3), so a voice chosen
  through a tool is the voice the Stop hook uses.
- **Applets and conversation mode** — the vox-panel applet receives the
  handle at spawn; conversation mode addresses the session it serves by its
  `session_id`.

Music is machine-global and ownership-free (vox DES-041); layer 2 scopes only
what is per session or per agent.

### 8.4 quarry — a layer-1 engine

quarry resolves the caller to route each call. The quarry daemon is the
engine; it holds no per-caller state, so quarry is a layer-1 engine (§ 3):
each call carries its facts and the daemon keeps nothing per session. Caller
identity arrives on a declared channel:

- **Claude Code** — the PreToolUse hook stamps `_caller` via `updatedInput`
  under the matcher `mcp__(plugin_quarry(-dev)?_)?quarry(-proxy|-dev)?__.*`;
  the server strips it before validation (§ 3.2.1).

quarry becomes a layer-2 engine the moment its daemon holds state per session
— database selection (`use`) held per caller, as architecture.md invariant 4
asks — and then owns its sessions under § 4. Which state the daemon holds is
quarry's own decision.

### 8.5 biff — one engine path, four harnesses

biff resolves the caller's `session_id` and `agent_id` to route messages, track
presence, and gate the plan. Caller identity arrives on a per-harness declared
channel, never inferred from the process tree and never read from another
engine's CLI; biff's engine side runs one channel-agnostic path — strip the
identity argument before schema validation, validate its shape, refuse an
unidentified call, resolve:

- **Claude Code** — the PreToolUse hook stamps `_caller` via `updatedInput`
  under the matcher `mcp__(plugin_biff(-dev)?_)?tty__.*`.
- **codex** — the same hook. codex's `ClaudeHooksEngine` is Claude-hooks-compatible
  (`CLAUDE_PLUGIN_ROOT`), so the Claude stamping hook runs near-verbatim.
- **OpenCode** — MCP `params._meta["ai.opencode/sessionID"]`.
- **pi** — in-process: the extension passes `session_id` and `agent_id`
  directly to biff's thin-client calls (§ 3.3, hooks and applets are session
  clients too).

Four harnesses, three producer mechanisms: the hook stamp serves Claude Code and
codex, OpenCode uses MCP `_meta`, and pi (and any applet) passes the facts
in-process.

---

## 9. Scope

- § 1's connection facts are for streamable HTTP; the hook facts and the
  rules in § 3 and § 4 apply to every transport.
- `/clear` starts a new session; § 4.2 then opens a new engine session.
- § 3.2.3 does not depend on `clientInfo`: a declared channel per client
  type is the only identity source.
- A Claude Code release that sends caller identity to MCP servers natively
  supersedes the hook transport in § 3.1, not the rest of this standard.
