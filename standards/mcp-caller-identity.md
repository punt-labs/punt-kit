# MCP Caller Identity Standards

**Updated:** 2026-11-04

How a Punt Labs engine learns which Claude Code session, and which agent
inside it, is calling — on every client surface that session uses: MCP tool
calls, hooks, and applets. This standard applies to every engine that holds
state for its callers. [architecture.md](architecture.md) invariant 4 already
requires that state to live in the engine, keyed by client; this document
says where the key comes from.

The reference implementation is ethos (DES-074, amendments of 2026-11-03).
The lux and vox applications in § 8 test the boundaries of the standard.

---

## 1. The Problem, Measured

Measured against Claude Code 2.1.309 with a logging MCP server and a logging
PreToolUse hook (fastmcp 3.4.11 and 4.1.6, headless `claude -p` sessions,
2026-11-04):

| Fact | Evidence |
|---|---|
| A `tools/call` names no session and no agent. Beyond the arguments it carries only `_meta: {claudecode/toolUseId, progressToken}`. | Raw request bodies |
| An MCP server's environment has no `CLAUDE_PID` and no session variable. The documented `${VAR}` expansions in `url`, `headers`, and `headersHelper` include none. | ethos DES-074; Claude Code MCP docs |
| A subagent uses its leader's MCP connection. Two parallel subagents share it too. | Identical `Mcp-Session-Id` for leader and subagents |
| The connection identifier changes on every reconnect. Claude Code reconnects on its own about 2 s after a server restart. | New `Mcp-Session-Id` after a restart, same caller |
| Claude Code offers the stateless 2026-07-28 protocol first and stays on it when the server accepts. That protocol has no `initialize`, no `Mcp-Session-Id`, and no connection. | `server/discover` first; fallback to `initialize` only on refusal |
| Every hook payload carries `session_id`. A subagent's payload adds `agent_id` and `agent_type`. `CLAUDE_PID` is set in the hook's environment. | PreToolUse payload log |
| `session_id` is unchanged across `claude --resume`. | Same value before and after |
| OAuth does not identify the session or agent. An MCP access token authorizes a resource owner through a client, is audience-bound to one server, and is stored per endpoint and reused across sessions. | MCP spec 2025-11-25 § Authorization; Claude Code MCP docs |

Consequences:

- **The connection is not an identity.** It is shared by the leader and every
  subagent, it is replaced on reconnect, and in the stateless protocol it does
  not exist. No engine may key caller state on it.
- **The process is not an identity either.** A stdio server is one process per
  Claude Code session, but every subagent of that session shares the process.
- **Hooks are the only place Claude Code states who is acting.** This standard
  moves that fact, once, into every call the session makes.
- **Authorization and identity are separate concerns.** OAuth answers "may this
  user, through this app, use this server". This standard answers "which
  session and which agent is calling". An engine may need both.

---

## 2. Terms

| Term | Meaning |
|---|---|
| **Caller facts** | `session_id` (the Claude Code session) and `agent_id` (who inside it). Stated by Claude Code to hooks; never invented by the engine. |
| **Main-thread agent id** | For a call with no `agent_id` in the payload: the hook's corroborated `CLAUDE_PID`. A payload carrying `agent_type` but no `agent_id` is still the main thread (`claude --agent`). |
| **Engine session** | The engine's own record of one Claude Code session: the state it holds for that caller, its lease, and its handle. |
| **Handle** | The engine-issued reference to an engine session. Opaque to every client. |
| **Session client** | Any process acting for a Claude Code session against an engine: the MCP leg, the plugin's hooks, and applets the session spawns. |
| **`_caller`** | The reserved argument that carries caller facts, plus the handle where § 4 applies, on an MCP tool call. |

---

## 3. Layer 1 — Caller Facts on Every Call (Required)

Every engine that needs to know who is calling implements this layer.

### 3.1 The hook

The plugin's PreToolUse hook matches only its own server's tools
(`mcp__plugin_<plugin>_<server>__*`) and returns `updatedInput`: the original
arguments plus

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
5. For its own tools the hook **fails closed**: a payload it cannot read or
   parse is denied with the cause in the reason, never passed through
   unidentified. For any other tool a hook failure leaves the call untouched.
6. The hook is small and fast. A stdlib-only Python hook measured 20 ms per
   call; no heavy imports on this path.

### 3.2 The server

1. **Strip before validation.** `_caller` is removed from the arguments before
   tool argument validation (fastmcp: a `Middleware.on_call_tool`). A tool's
   schema never declares `_caller`, so agents never see it. Measured: a hook
   adding `_caller` to a tool whose schema does not declare it fails the call
   with `Unexpected keyword argument` unless the server strips it. A server
   whose framework cannot strip (ethos, in Go) may declare `_caller` on each
   tool instead; the observable contract is the same.
2. **One source.** The caller comes from `_caller` only. Never from the
   transport, the connection, the process tree, the environment, git, or the
   OS user.
3. **Validate the shape.** `session_id` and `agent_id` are non-empty and match
   `[A-Za-z0-9_-]+`. Anything else is a named error.
4. **Refuse a Claude Code call without `_caller`.** The server recognizes Claude
   Code by `clientInfo.name == "claude-code"`, present in both protocol eras,
   and answers with an error naming the likely cause (the hook is not
   installed, disabled, or killed). A client that is not Claude Code keeps its
   own documented path (for example OpenCode's `_meta`).
5. **Work in the stateless protocol.** Because no identity rides on the
   connection, an engine following this standard accepts the 2026-07-28 era.
   An engine must not refuse it merely to keep a connection-scoped identity.

### 3.3 Hooks and applets are session clients too

A hook already receives `session_id` and `agent_id` in its payload, so a hook
calling its engine sends them directly, the same shape as `_caller`. An
applet spawned by a SessionStart hook receives the caller facts from that
hook at spawn time.

---

## 4. Layer 2 — Engine-Owned Sessions

### 4.1 When it applies

An engine implements layer 2 when it holds **any per-session or per-agent
state for its callers** — which, under architecture.md invariant 4, is any
engine that holds client state at all. Only an engine that holds nothing per
caller (every request self-contained, every answer independent of who asked)
stops at layer 1.

Caller facts identify a Claude Code session; they do not make the engine the
authority on it. Layer 2 does: the engine opens its own session record,
issues the handle, and every session client presents that handle.

### 4.2 Lifecycle

1. **Open.** The plugin's SessionStart hook calls the engine's own API (REST or
   CLI, not MCP) to open an engine session. It declares the caller facts and
   whatever identity the engine's model wants (repo, cwd, kind, name). The
   engine creates the record, starts its lease, and returns the handle.
   Identity remains caller-declared; only the handle is engine-issued.
2. **Store.** The hook writes the handle to
   `~/.punt-labs/<tool>/sessions/<session_id>` with mode `0600`, in a directory
   with mode `0700`. The file is keyed by Claude's `session_id`, which every
   later hook payload carries.
3. **Present.** Every session client presents the handle with its caller facts:
   - the PreToolUse hook adds `"handle": "<handle>"` to `_caller`;
   - other hooks read the file and send the handle to the engine directly;
   - applets receive it from the SessionStart hook that spawned them.
4. **Renew.** Every call carrying the handle renews the lease.
5. **Close.** The SessionEnd hook closes the engine session and removes the
   file. SessionEnd fires on a clean exit only, so the lease is the backstop:
   a crashed session's record is reaped when its lease lapses.
6. **Recover.** A call presenting an unknown or expired handle gets a named
   error that the hook can act on by opening a fresh session (for example
   after an engine restart without persisted sessions).

### 4.3 Per-agent state

The engine scopes state below the session by `agent_id`: one engine session,
many agents. A subagent's state is its own; the main thread's agent id is
`CLAUDE_PID`, matching ethos so the same agent has the same key in every
engine.

### 4.4 The handle

The handle is either an opaque secret or the caller facts themselves:

- **Opaque secret** (required where another local process could act against a
  session it does not own, and for any engine reachable across hosts). A
  process that has not seen the SessionStart hook's output cannot present it.
- **The caller facts** `(session_id, agent_id)`, validated against the engine's
  own record (the ethos roster model). Acceptable for an engine whose records
  are local and whose spoofing cost is low.

Either way the handle is routing first. A loopback bind remains the trust
boundary for a local engine; cross-host engines add transport authentication
(and, if they expose third-party resources, OAuth per the MCP spec).

---

## 5. Not Acceptable

- Keying caller state on `Mcp-Session-Id`, a transport connection, or a
  per-process UUID.
- A random identity minted per connection, per request, or per process.
- Walking the process tree from an MCP server to find a Claude process.
- Reading caller identity from the environment of an MCP server.
- Refusing the stateless protocol to preserve a connection-scoped identity.
- Splitting one session's state across files, hook processes, and MCP process
  memory with no single owner.
- A PreToolUse hook that returns `allow`.

---

## 6. Conformance Tests

Every engine ships tests at the wire boundary that:

1. Call a tool with a well-formed `_caller` and assert the engine resolved the
   caller (and, under layer 2, the session).
2. Call a tool as `claude-code` without `_caller` and assert the named refusal.
3. Call a tool with a malformed `_caller` and assert the named error.
4. Call a tool whose schema does not declare `_caller` with one present and
   assert the call succeeds and the tool never received it.
5. Under layer 2: present an unknown handle and assert the named error; let a
   lease lapse and assert the record is gone.
6. Run against the stateless protocol and against the handshake protocol and
   assert identical caller resolution.

The hook ships its own tests: overwrite of a model-supplied `_caller`, removal
when facts are missing, denial on an unreadable payload for its own tools, and
no `allow` output on any path.

---

## 7. Relation to Other Standards

- [architecture.md](architecture.md) invariant 4 — client state lives in the
  engine, keyed by client. This standard supplies the key.
- [hooks.md](hooks.md) — hook structure and dispatch; § 3.1 and § 4.2 add the
  caller-facts and handle duties.
- [integration.md](integration.md) — tools coordinate without hard
  dependencies. Each plugin ships its own conforming hook; no engine depends on
  another tool's hook to identify its callers.
- [filesystem.md](filesystem.md) — `sessions/` under the tool's home holds the
  per-session handle files.
- [python.md](python.md) — standalone fastmcp is the server framework; its
  middleware is where `_caller` is stripped.

---

## 8. Applications

### 8.1 ethos — the reference

ethos implements both layers today. Its SessionStart hook writes the session
roster (the engine session); its PreToolUse hook stamps
`_caller {session_id, agent_id}` on ethos tools; its server resolves the caller
by exact-participant lookup in the roster and refuses a Claude Code call
without `_caller`. The handle is the caller facts (§ 4.4). ethos is written in
Go and declares `_caller` on its tools rather than stripping it.

### 8.2 lux — an engine whose sessions own UI

The lux Hub (luxd) is the engine; the Display only renders and plays no part
in identity. The Hub already models callers (`Scope`, `connection_id`,
`ClientLifecycle`, leases; lux DES-057), but its MCP leg derived the session
from the transport, which breaks for subagents, reconnects, and the stateless
protocol. Under this standard:

- The SessionStart hook opens a Hub session over REST and receives a handle:
  the Hub's `connection_id` plus a secret. The applets the hook already spawns
  receive the same handle, so a session's scenes, subscriptions, and menu
  entries belong to one Hub session.
- `_caller` carries the facts and the handle; Hub middleware resolves the
  `Scope` and an agent sub-scope, so a subagent owns its own scenes.
- The Hub accepts the stateless protocol. Lease renewal on each call and
  SessionEnd replace connection-scoped cleanup.
- The handle is a secret: lux is moving cross-host (lux DES-089/090).

### 8.3 vox — an engine whose state is spread today

voxd is the engine. It holds no caller state today: voice, provider, and model
are resolved client-side and sent with each `synthesize`, from the per-repo
`vox.md`, the per-repo `vox.local.md` (which holds vibe, so two sessions in
one repo overwrite each other's), and in-memory overrides inside each
`vox mcp` stdio process that hooks cannot see. Half of vox's speech is driven
from hooks (Stop, Subagent, notify), so the MCP leg alone is not enough.
Under this standard:

- voxd owns session state (vibe, voice override) keyed by the handle; repo
  defaults stay in `vox.md`; each agent's voice resolves from its ethos
  persona, so a subagent speaks in its own voice.
- The MCP leg, the hooks, and the vox-panel applet all present the same handle,
  so a voice chosen through a tool is the voice the Stop hook uses.
- Music stays machine-global and ownership-free (vox DES-041): layer 2 scopes
  only the state that is genuinely per session or per agent.
- vox's server moves from the SDK-bundled `mcp.server.fastmcp` to standalone
  fastmcp ([python.md](python.md)) to gain the stripping middleware.

---

## 9. Open Items

- Whether `/clear` and compaction change `session_id` has not been measured
  interactively. `/clear` starting a new session is the expected and correct
  behavior; the SessionStart hook then opens a new engine session.
- The SessionStart-to-PreToolUse handle handoff through
  `~/.punt-labs/<tool>/sessions/` is specified, not yet spiked end to end.
- The measurements in § 1 are against Claude Code 2.1.309. A Claude Code
  release that sends caller identity to MCP servers natively supersedes the
  hook transport in § 3.1, not the rest of this standard.
