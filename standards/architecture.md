# Architecture Standards

What a Punt Labs tool is: one engine, thin client surfaces. Language-agnostic;
the per-language standards and distribution.md cross-reference this.

---

## The Projection Model (canonical)

This is the canonical description of the engine-and-clients model. python.md,
cli.md, plugins.md, and distribution.md cross-reference this section; they do not
restate it.

### Principle: one engine, many thin clients

Every project is an **engine** fronted by thin clients. The engine is the core —
it holds the logic, the state, and the authority. Every surface a caller uses —
library import, CLI, MCP server, REST API — is a thin client of that one engine.
The library is a client too; it is not the core.

Four invariants hold for every product. No product may vary them.

**1. One engine, implemented once, never duplicated per client or per surface.**
The engine may be a single process or a small set of cooperating processes,
possibly on separate machines — but it is split only for (a) an architectural
boundary, or (b) network distribution. The split is decomposition, never
duplication:

- *Decomposition* (allowed): complementary parts of one engine. lux splits its
  engine into the **Hub**, which owns authority, state, and handler dispatch,
  and the **Display**, which owns rendering and input. Two processes, one
  engine, complementary jobs.
- *Duplication* (forbidden): the same functionality standing up once per surface
  or per session. This is the multiplication vox eliminated when eight
  per-session audio processes collapsed into one `voxd` daemon.

Clients reach the one engine through its front door — in lux, the Hub — and
never talk to its internal components. A lux client never talks to the Display.

**2. Every surface is a thin client of the engine.** Library, CLI, MCP, REST —
none reimplements or forks the engine logic.

**3. One code path.** A given capability runs the same engine-side code no
matter which surface it entered from. quarry's `search` runs the identical
engine code whether it arrived from the Python import, the `quarry search` CLI,
the MCP tool, or the REST endpoint.

**4. Client-specific state lives in the engine, keyed by client.** Working
directory, active repo, which features are on or off, session context — the
engine holds these authoritatively. A client carries only its own identity and
the context it alone can originate, such as its working directory, and pushes
that into the engine. Keep clients thin; default to holding their state in the
engine. quarry keys each client's selected database server-side: the
`quarry serve` daemon holds it, not the client.

### The four surfaces

One engine, four client surfaces. Each reaches a different caller; none
reimplements the engine.

| Surface | Caller |
|---------|--------|
| Library import | code in the same process |
| CLI | human at a terminal, shell script, CI |
| MCP server | AI agent in an MCP-aware host |
| REST API | app, web frontend, webhook, remote client |

Build the surfaces that have callers — but treat the CLI as present by default,
because scripts, automation, and humans always give it one. `punt init`
scaffolds the surfaces from the first commit; a surface with no caller stays thin
scaffolding until one appears.

### Surfaces versus channels

A **surface** is how a caller reaches the engine. A **channel** is how a surface
is shipped. One surface can ship through several channels; do not confuse the two
axes. For the concrete channel mapping — which channel ships which surface — see
[distribution.md](distribution.md#surfaces-versus-channels).

The **plugin shell** and the **`.mcpb` desktop bundle** are distribution
channels for the MCP surface, not separate surfaces — a plugin wraps the MCP
server (see plugins.md). A **native app** is a distribution channel for a
platform-native front end (App Store, TestFlight, Homebrew), outside the four
client surfaces of the engine.

### Bounded choices (product judgment)

The invariants are fixed. Three choices are left to each product:

**Transport: REST/HTTP, a local socket, or stdio.** Choose by latency and
reachability. quarry uses REST because search tolerates network latency. lux uses
a local socket because display I/O is at millisecond scale.

**When the engine must become a daemon.** Required once clients share mutable
state, contend for a device, or run concurrently. Deferrable before that, but
only if the surfaces are already thin clients over a clean engine boundary, so
adding the daemon later is a deployment change, not a rewrite. ethos has no
daemon today — repo state on disk, no concurrency pressure — and defers it until
scale demands it. vox's `voxd` daemon owns the audio device, so it exists now.

**Which surfaces to build.** Only those with callers — though the CLI
effectively always has one.

### Carve-out: the stateless leaf

A pure stateless leaf has no engine. langlearn-types exports types and protocols
only — no state, no device, no authority — so it is plain importable code, the
one non-client case. This is not an exception to invariant 1; it is the absence
of an engine to have clients of.
