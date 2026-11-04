# MCP Caller Identity: Lifecycle Model Report

Model-check report for `mcp-caller-identity-lifecycle.tex`, a Z model of the
engine-session lifecycle in [mcp-caller-identity.md](mcp-caller-identity.md)
§ 4.2. Tools: fuzz (`/home/jfreeman/.local/bin/fuzz`), ProB probcli
(`z-spec doctor`: z-spec 0.20.5), 2026-11-04.

## The model

Two sessions (`sa`, `sb`), three main-thread pids (`pa`, `pb`, `pc`), three
handles (`ha`, `hb`, `hc`). A record is keyed by its handle and carries a
session, a state (`live`, `dormant`, `ended`), a current main pid, a durable
state flag and a live-client-resources flag. Ghost history (every pid that ever
ran for a session, the latest run, sessions whose durable state has not
legitimately expired) states the invariants. Operations, each atomic:
`OpenSess`, `CallTool` (known or unknown handle), `LeaseLapse`, `SessionEnd`
(enabled for any pid that ever ran for the session), `RetentionExpire`. Resume
is `OpenSess` or `CallTool` with a fresh pid.

The invariants are the schema `Safety`. They are checked as reachability goals,
not as state invariants: Z's `\Delta` includes the post-state constraint, so a
state invariant would make ProB disable the violating operation instead of
reporting it.

## Type-check

```text
fuzz standards/mcp-caller-identity-lifecycle.tex
```

No output, exit 0. The four `_buggy` files are likewise clean.

## Model-check: the correct model

Deadlock and full state space:

```text
probcli standards/mcp-caller-identity-lifecycle.tex -model_check \
  -p MAX_OPERATIONS 1000 -p TIME_OUT 600000
```

```text
ALL OPERATIONS COVERED
% Model checking finished, all open states visited
States analysed: 36889
Transitions fired: 672517
No counter example found. ALL states visited.
```

(The default `MAX_OPERATIONS` of 10 truncates the exploration and ProB warns
`model_check_incomplete`; 1000 is enough.) No deadlock.

Each invariant is checked by asking for a state that violates it. Every run is

```text
probcli standards/mcp-caller-identity-lifecycle.tex -model_check -nodead \
  -p MAX_OPERATIONS 1000 -p TIME_OUT 600000 -goal "<violation>"
```

| Inv | Violation goal | Result |
|---|---|---|
| I1 | `#(a,b).(a:hs & b:hs & a/=b & hsid(a)=hsid(b))` | not found; 36889 states, 672517 transitions |
| I2 | `#h.(h:hs & hst(h)=ended & endby(h)/=lastrun(hsid(h)))` | not found; same |
| I3 | `#s.(s:dursid & (s/:ran(hsid) or #h.(h:hs & hsid(h)=s & h/:dur)))` | not found; same |
| I4 | `#h.(h:hs & ((hst(h)=dormant & h/:res) or (hst(h)=live & h/:res) or (hst(h)=ended & h:res)))` | not found; same |
| I5 | `#h.(h:hs & hpid(h)/=lastrun(hsid(h)))` | not found; same |
| deadlock | (default `-model_check`) | none |

Deadlock-freedom is real but cheap: `OpenSess` is enabled in every state (the
latest pid may always re-open, and a free handle always exists for a session
without a record), so the model cannot stall. The stale `EndStale` step is a
stutter and is not what keeps the model live.

## Fidelity controls

Each control is the correct model with one change. Command shape:

```text
probcli standards/<control>.tex -model_check -nodead \
  -p MAX_OPERATIONS 1000 -goal "<violation>"
```

### (a) `_dormant_buggy`: get-or-create ignores dormant records

`CreateCore` fires when no non-dormant record exists for the session;
`OpenReuse` and `CallUnknownReuse` refuse a dormant record. Goals I1 and I3.

```text
I1:  1: INITIALISATION
     2: OpenSess(pa,sb)-->ha
     3: LeaseLapse(sb)-->ha
     4: CallTool(hc,pc,sb)-->hc        two records for sb: ha (dormant), hc

I3:  1: INITIALISATION
     2: OpenSess(pa,sa)-->hb
     3: LeaseLapse(sa)-->hb
     4: CallTool(hc,pc,sa)-->hc        sa has durable state; hc is empty
```

### (b) `_nopin_buggy`: Open does not update the record's current main pid

`OpenReuse` keeps `hpid`. Goals I5 and I2.

```text
I5:  1: INITIALISATION
     2: OpenSess(pa,sb)-->hc
     3: OpenSess(pb,sb)-->hc           resume; record still says pa

I2:  1: INITIALISATION
     2: CallTool(ha,pc,sb)-->ha
     3: OpenSess(pa,sb)-->ha           resume; record still says pc
     4: SessionEnd(pc,sb)-->ha         late end from the replaced run ends it
```

### (b') `_nopincall_buggy`: only Open updates the main pid, calls do not

This is the literal reading of § 4.2 (§ 4.2.1 and § 4.2.6 mention the main pid
only for Open). `CallTool` keeps `hpid`. Goals I5 and I2.

```text
I5:  1: INITIALISATION
     2: OpenSess(pb,sb)-->ha
     3: CallTool(hb,pc,sb)-->ha        first call after a resume whose
                                       SessionStart did not run

I2:  1: INITIALISATION
     2: CallTool(hb,pb,sb)-->hb
     3: OpenSess(pa,sa)-->ha
     4: CallTool(hc,pb,sa)-->ha
     5: SessionEnd(pa,sa)-->ha
```

### (c) `_noguard_buggy`: SessionEnd without the pid guard

`SessionEnd` is `EndMatch` with the `hpid h = p` conjunct removed. Goal I2.

```text
     1: INITIALISATION
     2: OpenSess(pb,sb)-->hc
     3: CallTool(hb,pa,sb)-->hc        resume as pa
     4: SessionEnd(pb,sb)-->hc         late end from the replaced run pb
```

## What the model says about § 4.2

The correct model passes all five invariants. It passes because it encodes
rules the current prose does not state, or states incompletely.

1. **§ 4.2.1 and § 4.2.7 omit dormant.** Both say "live, or ended within
   retention" (§ 4.2.7 adds "or one a concurrent SessionStart just opened").
   Control (a) is exactly this reading. The lookup must cover a record in any
   retained state: live, dormant, ended.
2. **No rule says Open sets the record's current main pid** (control b).
   § 4.2.1 says only that the record is "made live again".
3. **A call also sets it** (control b'). § 4.2.4 sends `main_agent_id` on
   every call, but § 4.2.6 ties "current main thread" to nothing. The model
   checks the rule that every Open and every call carrying `main_agent_id`
   sets the record's current main pid to it, including the first call after a
   resume when SessionStart was async or failed (§ 4.2.2).
4. **SessionEnd guard** (control c) is already in § 4.2.6 and is necessary.
5. **Resources on revival.** A dormant record keeps its resources, so revival
   re-establishes nothing (I4). An ended record has released them, so a resume
   that revives it returns the handle and durable state but no callbacks,
   subscriptions or pending deliveries; clients re-register. § 4.2.6 says "the
   same record, handle, and durable state" and is silent on this.
6. **A handle another session's record holds** is outside the model. A call
   presenting such a handle should be refused or treated as unknown; the
   prose does not say.

## Assumptions the model makes

- A call or open comes only from the session's latest run or from a fresh run.
  A late call from a replaced run would move the current main pid backward;
  the engine cannot detect that.
- Calls store durable state. `RetentionExpire` is nondeterministic for ended
  and dormant records; it is the only operation that may remove durable state.
- Resolving by `session_id` means the presented handle is not authoritative:
  after a call with an unknown handle resolves to an existing record under a
  different handle, the client's stale handle keeps taking the unknown-handle
  path until its handle file is rewritten.
