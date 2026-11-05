# MCP Caller Identity: Lifecycle Model Report

Model-check report for `mcp-caller-identity-lifecycle.tex`, a Z model of the
engine-session lifecycle in [mcp-caller-identity.md](mcp-caller-identity.md)
§ 4.2. Tools: fuzz, ProB probcli (z-spec 0.20.5), 2026-11-04. Revision 2: live
resources belong to a run; handle collisions resolved by `session_id`.

## The model

Two sessions (`sa`, `sb`), three main-thread pids (`pa`, `pb`, `pc`), three
handles (`ha`, `hb`, `hc`). A record is keyed by its handle and carries a
session, a state (`live`, `dormant`, `ended`), a current main pid, a durable
state flag, and `resown`: the pid of the run that registered the record's
live-client resources, if it holds any. Ghost history (every pid that ever ran
for a session, the latest run, sessions whose durable state has not
legitimately expired, dormant records that held resources at their lapse)
states the invariants. Operations, each atomic: `OpenSess`, `CallTool`,
`Register` (the current run registers resources), `LeaseLapse`, `SessionEnd`
(enabled for any pid that ever ran for the session), `RetentionExpire`. Resume
is `OpenSess` or `CallTool` with a fresh pid.

Resource rules in the model:

- A created record holds no resources; `Register` gives the current run's
  resources to a live record.
- Open or call by the record's current main pid (same run): resources stay.
- Open or call by a different pid (new run): the previous run's resources are
  released before the record goes live; durable state carries over.
- Lapse keeps resources; SessionEnd and retention expiry release them.

Handle rules: a call whose handle the session's record owns renews it. Any
other handle (free or another record's) resolves by `session_id`: to the
session's record if it has one; otherwise a record is created, under the
presented handle if no record holds it, under a fresh handle if another
record does.

Invariants (schema `Safety`), checked as reachability goals because a state
invariant would make ProB disable the violating operation (Δ includes the
post-state constraint):

- I1 at most one record per session.
- I2 an ended record was ended by the session's latest run.
- I3 a session with unexpired durable state has a record that holds it.
- I4 a dormant record that held resources at its lapse still holds them; an
  ended record holds none.
- I5 a record's current main pid is the pid of the session's most recent Open
  or call.
- I6 every resource a record holds belongs to its current run
  (`resown h = hpid h`).

Handles are injective across records by construction (a record is keyed by its
handle); a collision shows as an overwritten record, which I3 reports.

## Type-check

```text
fuzz standards/mcp-caller-identity-lifecycle.tex
```

No output, exit 0. All six `_buggy` files are likewise clean (probcli runs
fuzz on each before exploring).

## Model-check: the correct model

```text
probcli standards/mcp-caller-identity-lifecycle.tex -model_check \
  -p MAX_OPERATIONS 1000 -p TIME_OUT 900000
```

```text
ALL OPERATIONS COVERED
% Model checking finished, all open states visited
States analysed: 95929
Transitions fired: 2197477
No counter example found. ALL states visited.
```

No deadlock. (The default `MAX_OPERATIONS` of 10 truncates the exploration.)

Each invariant is checked by asking for a violating state:

```text
probcli standards/mcp-caller-identity-lifecycle.tex -model_check -nodead \
  -p MAX_OPERATIONS 1000 -p TIME_OUT 900000 -goal "<violation>"
```

| Inv | Violation goal | Result |
|---|---|---|
| I1 | `#(a,b).(a:hs & b:hs & a/=b & hsid(a)=hsid(b))` | not found |
| I2 | `#h.(h:hs & hst(h)=ended & endby(h)/=lastrun(hsid(h)))` | not found |
| I3 | `#s.(s:dursid & (s/:ran(hsid) or #h.(h:hs & hsid(h)=s & h/:dur)))` | not found |
| I4 | `#h.((h:kept & (hst(h)/=dormant or h/:dom(resown))) or (h:hs & hst(h)=ended & h:dom(resown)))` | not found |
| I5 | `#h.(h:hs & hpid(h)/=lastrun(hsid(h)))` | not found |
| I6 | `#h.(h:dom(resown) & resown(h)/=hpid(h))` | not found |

Each of the six runs visited all 95929 states and 2197477 transitions. (The I4
run prints a ProB style warning, `bmachine_construction`, that its goal has a
disjunction under the quantifier; the result is unaffected.) Deadlock-freedom
is real but cheap: `OpenSess` is enabled in every state, so the model cannot
stall; `EndStale` is a stutter step and is not what keeps it live.

## Fidelity controls

Each control is the correct model with one change. Every one reaches a
counterexample in under 2 s. Command shape:

```text
probcli standards/<control>.tex -model_check -nodead \
  -p MAX_OPERATIONS 1000 -goal "<violation>"
```

### (a) `_dormant_buggy`: get-or-create ignores dormant records

Goals I1 and I3 (traces differ only in which session and pid).

```text
I1:  OpenSess(pa,sa)-->ha ; LeaseLapse(sa) ; CallTool(hb,pc,sa)-->hb
     two records for sa
I3:  OpenSess(pb,sa)-->ha ; LeaseLapse(sa) ; CallTool(hb,pc,sa)-->hb
     sa's durable state is no longer held by a record of sa
```

### (b) `_nopin_buggy`: Open does not update the record's main pid

```text
I5:  OpenSess(pa,sa)-->ha ; OpenSess(pb,sa)-->ha
I2:  CallTool(hc,pc,sb) ; OpenSess(pb,sb) ; SessionEnd(pc,sb)
     a late end from the replaced run pc ends the resumed record
```

### (b') `_nopincall_buggy`: only Open updates the main pid, calls do not

This is the literal reading of § 4.2.

```text
I5:  OpenSess(pa,sa)-->hc ; CallTool(hc,pb,sb)-->ha ; CallTool(hc,pb,sa)-->hc
I2:  OpenSess(pb,sb)-->hb ; CallTool(hb,pc,sb)-->hb ; SessionEnd(pb,sb)
```

### (c) `_noguard_buggy`: SessionEnd without the pid guard

ProB's search found a 9-step trace; the shortest is

```text
I2:  OpenSess(pb,sb) ; CallTool(hb,pa,sb) ; SessionEnd(pb,sb)
     late end from the replaced run pb ends the record resumed as pa
```

### (d) `_runres_buggy`: resources survive a run change

`ReviveNew` keeps `resown`. Goal I6.

```text
I6:  CallTool(hc,pc,sb)-->hc ; Register(sb) ; CallTool(ha,pa,sb)-->hc
     the record is now run pa's, its resources are still run pc's
```

### (e) `_handlecollide_buggy`: create under a handle another record owns

`CallCreateFree` has no free-handle guard and overwrites. Goal I3.

```text
I3:  CallTool(hc,pb,sb)-->hc ; CallTool(hc,pc,sa)-->hc
     sa's call overwrites sb's record under hc; sb's durable state is lost
```

## What § 4.2 must say

The correct model passes only because it encodes the rules below. Rules 1-3
and 5-7 are absent or wrong in the current prose.

1. **Lookup covers every retained state.** Open and unknown-handle resolution
   find the session's record by `session_id` in state live, dormant, or ended
   within retention. (§ 4.2.1 and § 4.2.7 omit dormant: control a.)
2. **Open sets the record's current main pid** to the caller's
   `main_agent_id` (control b).
3. **Every call carrying `main_agent_id` does too**, including a known-handle
   call and the first call after a resume whose SessionStart did not run
   (control b'). An open or call from a replaced run (a pid that ran for the
   session but is not current) is refused and never repins (`PidOk`).
4. **SessionEnd ends the record only if its `main_agent_id` equals the record's
   current main pid** (control c); any state, idempotent on an ended record.
5. **Resources belong to the run that registered them.** An Open or call whose
   `main_agent_id` differs from the record's current main pid is a new run: the
   previous run's callbacks, subscriptions and pending deliveries are released
   before the record goes live, and durable state carries over (control d). An
   Open or call from the same run leaves resources alone. A lease lapse keeps
   them (dormancy is the same run being quiet); a crash fires no SessionEnd, so
   only the next run's arrival releases a dead run's resources.
6. **An ended record revives without resources**; a created record starts
   without them; clients (re-)register. Nothing is "restored".
7. **A presented handle never selects a record of another session.** Calls
   resolve by `session_id`. If the handle belongs to another session's record,
   treat it as unknown: reuse the session's own record if it has one, otherwise
   create one under a *fresh* handle. If the handle is free, creating under it
   is allowed. Never create under, reuse, or overwrite another record's handle
   (control e).
8. **Retention** removes only ended or dormant records and is the only way
   durable state is dropped; for a dormant record it should be measured from
   the lapse.

## Assumptions the model makes

- A call or open is enabled only for the session's latest run or a run never
  seen for the session (`PidOk`, over the `ever` history, which
  `RetentionExpire` leaves unchanged). An engine implements this by keeping,
  per `session_id` and independent of the record, the main pids that have
  run, and
  refusing an open or call from a replaced run; a late call from a replaced
  run therefore never moves the current main pid backward.
- Calls store durable state. `RetentionExpire` is nondeterministic for ended
  and dormant records.
- Resolution by `session_id` makes the presented handle non-authoritative: a
  client holding a stale or foreign handle keeps taking the unknown-handle path
  until its handle file is rewritten.
