# Design: Prompt State Machines for the Playbook DSL

**Status:** Draft for operator ratification
**Author:** adt (Hopper)
**Ticket:** pkit-r94d
**Date:** 2026-07-27

## Problem

The playbook DSL (`playbooks/SCHEMA.md`) describes **linear** processes: an
ordered list of `steps`, each `script` (deterministic shell) or `llm`
(judgment), with `mode: once | loop`. `mode: loop` restarts from step 1 after
the last step; there is no other control flow. A playbook is a straight line
that optionally repeats.

The workflows `/punt:auto` should automate are not straight lines. The
operator's model (`standards/workflow.md`) is three nested loops, and each loop
is a set of **named states with guarded transitions** — not a sequence.
The Level-2 PR loop polls a pull request, and on each tick branches three ways:
findings to fix, a merge gate to test, or wait and poll again. That is a state
machine. Today it is hand-authored as a raw cron prompt, once per PR — done
twice in a single session on 2026-07-27. Re-authoring a state machine in prose
on every PR is precisely the toil the playbook DSL exists to remove.

This document designs the minimal extension that lets a playbook express a
state machine, so the PR watch loop is a reviewed artifact
(`pr-loop.yaml`) instead of a retyped cron prompt. Every construct below is
justified by a loop we actually run; nothing is added for hypothetical
workflows.

## Terminology

Defined before use, so the sections below can lean on them:

- **Machine** — a playbook that declares `states` instead of `steps`. Its
  initial state is the first `states` entry, and it has at least one terminal
  state (unless it is a deliberately non-terminating loop, e.g. the backlog
  loop).
- **State** — a named node with an optional list of **actions** and a list of
  outgoing **transitions**. `e.g. id = watch`.
- **Action** — a step in the existing vocabulary (`type: script` or
  `type: llm`, with `postcondition` and `on_failure`), run when the machine
  **visits** the state. Actions are the reused half of the DSL; they are
  unchanged.
- **Visit** — one execution of a state: run its actions in order, then
  evaluate its transitions. Entering a state is a visit; a poll tick is
  another visit of the same state.
- **Transition** — a directed edge with an optional **guard** (`when`) and a
  target state (`to`). A transition with no guard is unconditional.
- **Guard** — a conjunction of **guard-checks** that must all pass for the
  transition to fire. A guard-check is a `check` (shell, passes on exit 0) or a
  `type: llm` judgment (passes on an affirmative verdict). Guard-checks reuse
  the precondition shape.
- **Tick** — a scheduled re-visit of a polling state after its `poll` interval
  elapses without any transition firing. The tick is the loop's clock.
- **Terminal state** — a state with no transitions. Reaching it halts the
  machine.
- **Run-state** — the persisted record of one machine execution: its
  parameters, its current state, and enough breadcrumbs to resume. Distinct
  from `LoopState` in `workflow.md`, which is the *domain* the machine observes
  (beads, PRs); run-state is the *machine's own* position.

## Section 1 — The Construct

### 1.1 A playbook is linear or a machine, never both

A playbook declares **either** `steps` (linear, the existing form) **or**
`states` (a machine). The executor selects by which key is present. This is the
whole backward-compatibility story:

- A linear playbook is unchanged and remains valid. It is the degenerate
  machine — one state whose actions are the step list, terminal on completion
  (or, under `mode: loop`, a single self-looping state with an unconditional
  transition back to itself). No existing file is touched; no existing field
  changes meaning.
- `mode: once | loop` stays meaningful only for linear playbooks. A machine
  expresses looping through transitions and termination through terminal
  states, so `mode` is ignored (and should be omitted) when `states` is
  present.

### 1.2 Top-level additions

Two optional top-level keys, valid only when `states` is present:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `states` | list | machine only | The states of the machine. **The first entry is the initial state** — the convention is fixed, with no override field. |
| `instance` | string | no | An expression, e.g. `pr-${pr}`, that names one running instance. Two values run two independent run-states. Default: the machine `name` (one instance per repo). |

The initial state is the first `states` entry, always — there is no `initial`
field. An earlier draft carried one; it failed this design's own "justified by
a loop we run" test, since none of the three worked machines (§3, §4) needs an
initial state other than the first — the earlier draft's `pr-loop` even set
`initial: watch` where `watch` was already first, a redundancy that proved the
field unnecessary. First-entry-is-initial is one fewer construct for zero lost
expressiveness; author order the states so the entry point leads.

`name`, `description`, `parameters`, and `preconditions` keep their current
meaning. In `SCHEMA.md` the top-level table marks `steps` **required: yes**;
under this extension that requiredness becomes **conditional** — `steps` is
required if and only if `states` is absent, and exactly one of the two is
present. This changes `steps`'s requiredness, not its meaning: a playbook that
has `steps` behaves exactly as before. Preconditions run once before the
initial state is entered.

### 1.3 State fields

```yaml
states:
  - id: watch
    description: Poll the open PR and route on what the tick observes
    poll: 2m                 # re-visit after 2m if no transition fires
    actions: []              # this state's guards read live state; no actions
    transitions:
      - to: fixing
        when:
          - description: CI is red, or there are unaddressed findings
            check: ./scripts/pr-needs-work.sh ${pr}
      - to: merging
        when: [ ... the merge gate ... ]   # §3
      # no unconditional transition: if neither fires, poll and tick
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique state identifier (kebab-case). |
| `description` | string | yes | What this state is for. |
| `actions` | list | no | Steps (existing `script`/`llm` vocabulary) run on every visit, in order, before transitions are evaluated. Absent ⇒ a pure decision state. |
| `transitions` | list | no | Outgoing edges, evaluated top-to-bottom. Absent ⇒ terminal. |
| `poll` | duration | no | If set and no transition fires, wait this long, then re-visit (tick). If unset and no transition fires and the state is non-terminal, the machine is **stuck** — an executor error. |

### 1.4 Transition fields

```yaml
transitions:
  - to: merging
    when:                    # conjunction: ALL guard-checks must pass
      - description: CI green on the latest commit
        check: ./scripts/ci-green-latest.sh ${pr}
      - description: No unaddressed material findings in the latest round
        type: llm
        context: |
          Read the latest review round's comments. A material finding is one
          that asks for a code change. Report PASS only if every material
          finding has a fix commit and a resolved thread, or a documented
          dismissal. Silence after a fix is not a finding.
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | string | yes | Target state `id`. |
| `when` | list | no | Guard: a list of guard-checks, all of which must pass (AND). Absent ⇒ unconditional (always fires). |

**Guard-check** — one entry of `when`. Reuses the precondition/step shape:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | yes | Human-readable statement of what is checked. |
| `check` | string | script guard-check | Shell command; passes on exit 0. Default type. |
| `type` | `script` \| `llm` | no | `script` (default) or `llm` for a judgment guard-check. |
| `context` | string | llm guard-check | Guidance for the judgment; the executor reports PASS/FAIL. |

Two guard-check types exist because the merge gate needs both. Four of its five
clauses are deterministic (CI status, thread count, timestamp arithmetic) and
are `check` shell. One clause — "no unaddressed **material** findings" — is
irreducibly a judgment: materiality and "addressed" are what the leader decides
today. Rather than pretend that clause is shell, the DSL admits a judgment
guard-check. `script` is the default; `llm` is opt-in and rare.

A judgment guard-check carries a cost that a shell one does not: **it is not
reproducible across runs.** A shell `check` is a pure function of the world — the
same inputs give the same exit code every time — so a deterministic transition
routes identically on every evaluation. An `llm` verdict is not pure; the same
PR state may route differently on two ticks. A machine with a judgment guard
therefore trades determinism for expressiveness on exactly the clauses that need
it. Keep judgment guards to those clauses (open question 1 asks the operator to
ratify this trade), and keep every other guard shell so the machine's routing is
reproducible wherever it can be.

### 1.5 Transition evaluation — the doorway rules

Stated as preconditions before behavior:

1. **Visit.** Run the state's `actions` in order. Any action failure applies
   its own `on_failure` (`retry` | `diagnose` | `abort`), unchanged from the
   linear semantics.
2. **Evaluate.** Take transitions in declared order. For the first whose `when`
   passes in full (every guard-check passes; an absent `when` passes
   trivially), fire it: the target becomes the current state. Go to step 1 for
   the target.
3. **No transition fired.**
   - If `poll` is set: register/keep the tick (§2.3), wait, re-visit (step 1).
   - Else if the state is terminal (no transitions): **halt, success.**
   - Else: **stuck** — a non-terminal state with no fireable transition and no
     `poll`. The executor reports the stuck state and halts with an error. This
     is a playbook bug, caught at runtime.

Declared order is the disambiguator: guards may overlap, and the author orders
them by priority. In the PR loop, `fixing` precedes `merging`, so a tick that
sees both unaddressed findings and a green gate always fixes first — the DSL
encoding of the invariant "findings never wait."

### 1.6 Parameters and variable flow

Parameters are unchanged: the top-level `parameters` block, `${name}`
substitution in action commands, guard-check `check` commands, and the
`instance` expression. The executor substitutes scalars before running a
command, exactly as today.

The machine deliberately has **no mutable machine variables**. Every guard
derives what it needs from live external state (the GitHub API, `git`, the
filesystem), never from a value the machine computed on an earlier tick. This
is a design choice, not an omission: timestamp clauses like "CI green for more
than ten minutes" read the check's `completedAt` from the API and compare to
now, rather than remembering when the machine first saw green. Statelessness of
guards is what makes crash/resume trivial (§2.4) — a resumed tick recomputes
everything from the world, so it cannot disagree with the tick that crashed.

## Section 2 — The Executor Contract

The executor is an LLM reading `skills/auto/SKILL.md`, not a daemon. The
protocol additions below are the changes that skill needs; they are additive —
the linear protocol (Phase 0–3) is untouched.

### 2.1 Detecting a machine

In Phase 0 (Load and Validate), after parsing, branch on shape: if `states` is
present, run the **machine protocol** (§2.2) instead of Phase 2's linear step
loop. If `steps` is present, run the existing protocol. A playbook with both,
or neither, is a validation error.

### 2.2 The visit loop

Replacing Phase 2 for machines:

```text
initial = first states entry
write run-state: { instance, parameters, current: <initial>, entered_at }
loop:
    S = current state
    run S.actions in order            # existing step semantics, on_failure applies
    for T in S.transitions (in order):
        if every guard-check in T.when passes:
            record transition in run-state history
            current = T.to; write run-state; break to loop
    else:                             # no transition fired
        if S has poll:
            schedule tick (§2.3); suspend
        elif S has no transitions:
            print completion summary; halt success
        else:
            print stuck-state error; halt error
```

A guard-check runs as its own Bash tool call (shell) or a scoped judgment
(llm), matching the linear protocol's rule that each `check` is a separate call
so it auto-approves.

### 2.3 The tick — scheduling without a daemon

A polling state does not busy-wait; the executor is not resident between ticks.
On reaching a `poll` state with no fired transition, the executor **registers a
recurring re-invocation** and returns control. The mechanism is the existing
`/loop` wrapper — the org's standard for recurring polling, as
`standards/workflow.md` §5 requires ("schedule a background poll — never a
blocking watch"): the executor registers

```text
/loop <poll> /punt:auto <name> --resume --instance <instance-key>
```

and stops. Each fire re-invokes the executor with `--resume`, which reloads
run-state and re-visits the current state — one tick. On firing a transition
out of the polling state, the executor cancels the `/loop` (its stop condition
is "current state changed"). This reuses the org's existing scheduler; the DSL
does not introduce one. `poll` is therefore a declaration that compiles to a
`/loop` registration, nothing more.

**This is an explicit dependency, not an implicit one: a machine with any
`poll` state cannot tick outside a `/loop`-capable executor.** A `/loop`
registration is session-scoped — it lives in the session that created it and
dies with that session. So a machine does not tick on its own after the
session that registered its `/loop` ends (a crash, a compaction that drops the
cron, a closed terminal). Nothing wakes the machine autonomously; run-state on
disk is inert until something invokes the executor again.

The minimal honest answer — not a piece of machinery, a documented property —
is that **any `/punt:auto <name> --resume` re-registers the tick.** On resume,
the executor reads run-state, finds the current state is a `poll` state with no
fired transition, and registers a fresh `/loop` before returning, exactly as a
first entry would. A machine whose session died therefore resumes ticking the
next time anyone runs `/punt:auto <name> --resume` for that instance — a new
session at the operator's next sweep, or a supervising loop that periodically
resumes known-open instances. The limitation stands plainly: between the death
of one session and the next resume invocation, the machine is paused, not
progressing. It loses no state (run-state is durable, §2.4) and it cannot act
wrongly (guards recompute on the next tick), but it also does not advance. This
is a property to design around — the operator's session-start sweep is the
natural re-igniter — not a gap the DSL closes with a daemon it deliberately
does not have.

### 2.4 Run-state persistence and crash/resume

Run-state is per-checkout, machine-local **live state**: it is bound to one
developer's checkout driving one PR, and the executor rewrites it on every
transition and every tick. `standards/punt-labs-dir.md` §3 routes exactly this
class of state — "person- or machine-scoped live state, but repo-bound" — to
the **local zone**, `.punt-labs/local/<tool>/`, never committed (§1 core
principle, §5 "Live State is Never a Tracked File"). So run-state persists,
keyed by instance, to:

```text
.punt-labs/local/punt/auto/<name>-<instance-key>.json
{
  "machine": "pr-loop",
  "instance": "pr-317",
  "parameters": { "pr": "317" },
  "current": "watch",
  "recap_sent": false,
  "entered_at": "2026-07-27T18:04:11Z",
  "history": ["watch", "fixing", "watch"]
}
```

This is inside the tool's own subtree (`punt/`) under the reserved `local/`
zone — not a new top-level dot-directory, which `punt-labs-dir.md` §2 forbids.
It needs **no rule beyond the canonical gitignore block**: the block's
`.punt-labs/**/local` line (`punt-labs-dir.md` §6) ignores the whole local
zone. Repos that have not yet adopted the canonical block — punt-kit's own
`.gitignore` does not carry it today — must adopt it before run-state lands,
or the run-state files become trackable. (The `recap_sent` flag is used by
the idempotency guard in §3.)

Crash/resume semantics rest on one invariant the author must uphold:

> **Visits are idempotent.** Re-visiting a state must produce the same net
> effect as visiting it once. A crash between an action and the run-state write
> causes the next `--resume` tick to re-visit the same state; the machine must
> tolerate that.

Idempotency is achievable because every action reads-then-acts against live
state, and an action with a side effect the world cannot un-see guards that
effect with its own precondition. The invariant is not "actions have no side
effects" — `merging` merges and `closing` sends mail — it is "an action that
already ran is a no-op the second time." The three action-states in the worked
example each show how:

- **`fixing`** re-fetches findings; if the crashed visit already committed the
  fix, the re-visit finds nothing to fix, `make check` passes, `git commit`
  no-ops on a clean tree, and the guard back to `watch` fires. Read-then-act
  makes the repeat empty.
- **`merging`** guards `gh pr merge` with a check of the PR's live state: it
  merges only when `gh pr view --json state` reads `OPEN`. A crash after the
  merge lands but before the run-state write leaves the PR `MERGED`, so the
  re-visit's guard reads `MERGED`, skips the merge, and falls through to
  `closing`. Without this guard, `gh pr merge` on a `MERGED` PR exits non-zero
  and drops into `on_failure: diagnose` — recoverable, but a violation of
  invariant 5, so the guard is mandatory, not cosmetic.
- **`closing`**'s recap email is the one effect with no external idempotency
  key — a second send is a second visible email. It is guarded by a flag the
  machine owns: `recap_sent` in run-state. The action sends only when
  `recap_sent` is false, then sets it true and rewrites run-state. A crash
  after the send but before the flag write re-sends on resume — so the flag is
  set in the **same** action, immediately after the send returns, and the
  window is one function call. This is the single place the machine keeps a
  written fact rather than reading the world, precisely because the world
  (an inbox) offers no reliable "already sent?" query; §1.6's no-mutable-state
  rule is about *guards*, and this is an *action* recording its own completion.

The stateless-guard rule (§1.6) is the other half of resume safety: because
guards recompute from the world, a resumed tick's routing decision equals the
crashed tick's. Resume therefore needs no transactional journal — only the last
committed `current` state plus the one `recap_sent` flag. If the crash predates
the first run-state write, `--resume` finds no file and starts from the initial
state, which is safe because the initial visit is itself idempotent.

The local zone `.punt-labs/local/punt/auto/` (fix chosen in §2.4 above,
`punt-labs-dir.md` §3) is deliberately not `.tmp/`: `make clean` wipes `.tmp/`
(confirmed, `Makefile:29` — `clean: rm -rf dist/ .tmp/`), and a PR watch loop
can outlive a `make clean`. Run-state needs a durable, gitignored home; the
local zone is exactly that, and unlike `.tmp/` it is not swept by a build
target.

### 2.5 What does not change

The failure strategies (`retry`/`diagnose`/`abort`), postconditions,
background script steps, working-directory rules, discovery order, and progress
reporting are all unchanged. A machine's actions *are* linear steps; everything
the executor already knows about steps still holds inside a state.

## Section 3 — The Worked Example: `pr-loop.yaml`

A design artifact, not a shipped file. It automates the Level-2 PR loop for one
open PR. Its guards encode `merge_gate` exactly as merged post-#244, and its
`closing` state encodes `git.md` §4 post-merge cleanup in the load-bearing
order.

```yaml
name: pr-loop
description: Poll one open PR, fix findings, merge on the gate, clean up
instance: pr-${pr}

parameters:
  - name: pr
    type: string
    required: true
    description: The pull request number to drive to merge

preconditions:
  - description: The PR exists and is open
    check: test "$(gh pr view ${pr} --json state -q .state)" = "OPEN"

states:
  # watch is first, so it is the initial state (no `initial` field)
  # --- Decision state: one tick reads live state and routes -------------
  - id: watch
    description: Poll the PR; route to fixing, merging, or wait
    poll: 2m
    # No actions: each guard reads the live PR state it needs.
    transitions:
      # fixing precedes merging: findings never wait (workflow §8 invariant 3)
      - to: fixing
        when:
          - description: CI is red on the latest commit, OR a review round has
              unaddressed findings on the latest commit
            check: ./scripts/pr-needs-work.sh ${pr}
      - to: merging
        when:
          # merge_gate clause 1: CI green on the latest commit
          - description: CI green on the latest commit
            check: |
              test "$(gh pr view ${pr} --json statusCheckRollup \
                -q '[.statusCheckRollup[]|select(.__typename=="CheckRun")
                     |.conclusion]|all(.=="SUCCESS")')" = "true"
          # merge_gate clause 2: Copilot reviewed latest, OR reviewed an
          # earlier commit but not the latest and CI has been green >10min
          - description: Copilot reviewed the latest commit, or reviewed
              earlier and CI has been green more than ten minutes
            check: ./scripts/reviewer-gate.sh ${pr} copilot 600
          # merge_gate clause 3: Bugbot reviewed latest, OR never reviewed
          # this PR and >6min have passed since CI went green
          - description: Bugbot reviewed the latest commit, or never reviewed
              this PR and more than six minutes have passed since CI went green
            check: ./scripts/reviewer-gate.sh ${pr} bugbot 360
          # merge_gate clause 4: zero unresolved review threads
          - description: Zero unresolved review threads
            check: |
              test "$(./scripts/unresolved-threads.sh ${pr})" -eq 0
          # merge_gate clause 5: latest review round has no unaddressed
          # material findings — the one judgment clause
          - description: The latest review round has no unaddressed material
              findings (fixed-and-resolved, or documented dismissal, counts as
              addressed; silence after a fix is not a finding)
            type: llm
            context: |
              Read the latest review round on PR ${pr}. A material finding asks
              for a code change. Report PASS only if every material finding has
              a fix commit and a resolved thread, or a recorded dismissal with
              the finding, the reason it does not apply, and a code reference.
              An empty round, or silence on the fix commit, is PASS.
      # else: neither fired -> poll 2m and tick again

  # --- Action state: fix whatever the tick found, push, resolve ---------
  - id: fixing
    description: Fix findings or a red build in this PR, then hand back to watch
    actions:
      - id: address
        description: Fix every unaddressed finding and any CI failure
        type: llm
        context: |
          Read the current reviews, threads, and checks on PR ${pr}. For each
          unaddressed finding, fix it in this PR or dismiss it with the exact
          finding, the specific reason it does not apply, and a code reference.
          If CI is red, diagnose and fix the cause. Resolve the thread for each
          fixed finding (the leader resolves, not the worker). Idempotent: if a
          prior crashed visit already fixed everything, find nothing to do.
        on_failure: diagnose
      - id: gate
        description: Quality gate must pass before the commit
        type: script
        command: make check
        on_failure: diagnose
      - id: push
        description: Commit and push; each push restarts the merge gate
        type: script
        # Idempotent: no-op when the working tree is already clean.
        command: ./scripts/commit-push-if-dirty.sh ${pr}
    transitions:
      - to: watch            # unconditional: re-evaluate the gate next tick

  # --- Action state: the merge itself -----------------------------------
  - id: merging
    description: Squash-merge the PR (reached only through the full gate)
    actions:
      - id: squash-merge
        description: Squash-merge with branch delete, only if still OPEN
        type: script
        # Idempotent (invariant 5): a crash after the merge lands but before
        # the run-state write re-visits this state. The `state = OPEN` read-
        # then-act guard makes the merge a no-op the second time, instead of
        # `gh pr merge` erroring on an already-MERGED PR.
        command: |
          if [ "$(gh pr view ${pr} --json state -q .state)" = "OPEN" ]; then
            gh pr merge ${pr} --squash --delete-branch
          fi
        postcondition:
          check: test "$(gh pr view ${pr} --json state -q .state)" = "MERGED"
        on_failure: diagnose
    transitions:
      - to: closing          # unconditional

  # --- Action state: post-merge cleanup, git.md §4 order ----------------
  - id: closing
    description: Post-merge cleanup and the merge recap
    actions:
      - id: cleanup
        description: git.md §4 cleanup, in the load-bearing order
        type: script
        # Order is load-bearing (git.md §4): checkout, pull --ff-only,
        # branch -d (needs origin/<branch> still present), then fetch --prune.
        # Idempotent (invariant 5): `checkout main` and `pull --ff-only` are
        # already no-ops when repeated; `branch -d` is guarded on the branch
        # still existing, so a re-visit after the branch was deleted skips it
        # rather than erroring.
        command: |
          git checkout main
          git pull --ff-only origin main
          branch="$(./scripts/branch-of-pr.sh ${pr})"
          if git show-ref --verify --quiet "refs/heads/$branch"; then
            git branch -d "$branch"
          fi
          git fetch --prune origin
      - id: recap
        description: Send the merge recap email once (every merge, unprompted)
        type: llm
        # Idempotent (invariant 5): a recap email has no external "already
        # sent?" key, so the machine records sent-ness itself. Send only when
        # run-state recap_sent is false, then set it true in this same action.
        # A crash after the send but before the flag write re-sends on resume,
        # so the flag write follows the send immediately, narrowing the window
        # to one call. This is the one written fact the machine keeps (§2.4).
        context: |
          If run-state recap_sent is already true, do nothing. Otherwise send
          the merge recap for PR ${pr} via beadle to the operator's recap
          address: subject "[repo] PR #${pr} merged: <title>", body with the
          bead id, PR link, and one paragraph on what changed, why, and how it
          left the system better (workflow §5 The merge recap). Immediately
          after the send returns, set recap_sent = true in run-state.
        # No shell postcondition: recap_sent lives in run-state, which the
        # executor owns and reads directly (§2.4) — it is not a repo file a
        # helper script would query.
    transitions:
      - to: done             # unconditional

  # --- Terminal state ---------------------------------------------------
  - id: done
    description: PR merged, branch cleaned up, recap sent
    # No transitions: terminal. The machine halts here. Starting the next unit
    # belongs to the Level-1 backlog machine, not this one.
```

`./scripts/reviewer-gate.sh <pr> <reviewer> <seconds>` encapsulates the
two-armed clause for one reviewer: pass if that reviewer reviewed the latest
commit, **or** the fallback holds — for Copilot, reviewed an earlier commit and
CI green longer than `<seconds>`; for Bugbot, never reviewed this PR and more
than `<seconds>` since CI went green. Naming the reviewer and the window as
arguments keeps the two clauses one script with the difference in data, not two
copies of shell. The exact `gh`/GraphQL incantations live in `pr-review.md` and
`git.md`; the point here is the DSL shape and the 1:1 mapping to the five
clauses, annotated inline. Where these five scripts live and ship — vendored
with `punt` versus repo-local — is open question 6.

### 3.1 Invariants this machine maintains

Written as invariants, since state machines are the home ground for them:

1. **Single position.** Exactly one `current` state exists at all times,
   persisted before control returns. There is no "between states."
2. **Merge only through the gate.** `merging` is reachable only from `watch`'s
   second transition, whose `when` is the entire five-clause `merge_gate`.
   There is no other edge into `merging` or to `gh pr merge`. This is the DSL
   form of workflow invariant 2 ("a satisfied merge gate means merge — and the
   gate is the only path").
3. **Findings before merge.** In `watch`, the `fixing` transition precedes the
   `merging` transition, so any tick with unaddressed findings routes to
   `fixing` first. Workflow invariant 3 ("findings never wait").
4. **Every push restarts the gate.** `fixing` always returns to `watch`
   unconditionally; the next tick re-reads CI and reviews on the new commit.
   Workflow invariant 4.
5. **Idempotent visits.** Every state's actions are safe to re-run, so
   crash/resume re-visiting a state cannot double-apply an effect (§2.4). The
   three states with real side effects prove it in the YAML: `merging` guards
   `gh pr merge` on the PR still being `OPEN`, `closing`'s cleanup guards
   `branch -d` on the branch still existing, and `closing`'s recap guards the
   send on the `recap_sent` flag it then sets. An action that already ran is a
   no-op the second time; the invariant is not "no side effects."
6. **Terminal after close-out.** `done` is reachable only after `closing`
   completes both cleanup and recap; the machine cannot report success with the
   branch un-deleted or the recap unsent. Workflow invariant 7 ("close-out is
   inside the loop").

## Section 4 — Expressiveness Check

The same three constructs — states, guarded transitions, terminal/poll —
express the other two loop levels. Shown in brief to prove the DSL carries all
three, not in full YAML.

### 4.1 Level 1 — the backlog loop (a non-terminating machine)

```text
states:                  # intake is first -> the initial state; poll = session cadence
  intake   actions: sweep signals -> beads or close-at-door
           transitions: -> validate (unconditional)
  validate actions: re-prove ready beads against main
           transitions: -> assess (unconditional)
  assess   actions: sort validated beads by the standing order
           transitions:
             -> escalate  when: [ llm: ordering hit a fork the charter
                                        cannot resolve ]        # human gate
             -> select    (unconditional fallback)
  escalate actions: [ ask operator for a focus ruling ]         # blocks
           transitions: -> select (unconditional, after ruling)
  select   actions: claim a batch; for each unit, run pr-loop as a sub-machine
           transitions: -> closeout (unconditional)
  closeout actions: close resolved issues; send batch recap
           transitions: -> intake (unconditional)   # do-while(true): no terminal
```

Two things this exercises that the PR loop did not: a machine with **no
terminal state** (the backlog loop is `do-while(true)` — `closeout` returns to
`intake`), and a **judgment guard as a human gate** (`assess -> escalate` fires
on the operator-fork judgment, and `escalate` blocks on the operator's ruling).
The `poll` at session cadence is the "runs at session start and when the batch
is done" trigger. Invoking `pr-loop` per unit is a sub-machine call; §6 open
question 4 asks how nesting is expressed.

### 4.2 Level 3 — the mission loop (a do-while with a review cycle)

```text
states:                  # dispatch is first -> the initial state
  dispatch actions: write contract; mission create; spawn worker; verify running
           transitions: -> working (unconditional)
  working  poll: <filesystem cadence>
           actions: (none; guards read the worker's result/filesystem)
           transitions:
             -> review  when: [ script: worker submitted a result ]
             # else poll: judge by filesystem, never by commits (workflow §6)
  review   actions: evaluator reviews; leader runs the change + review agents
           transitions:
             -> reflect  when: [ llm: findings remain ]
             -> close    (unconditional fallback: verdict accept, no findings)
  reflect  actions: record the reflection for the next round
           transitions: -> working (unconditional)   # the do-while back-edge
  close    (terminal)  # verdict accept, findings empty, mission closed
```

This exercises the **do-while** shape directly: `working -> review ->
(reflect -> working | close)` is exactly the "run at least once, repeat the
review-and-fix cycle until a clean round" of `mission_loop`. The back-edge
`reflect -> working` is the loop; `close` is the terminal that the empty-findings
fallback reaches. The `working` poll encodes "judge worker progress by the
filesystem" — the tick re-checks for a submitted result without intervening.

All three loops are the same machine vocabulary at three scopes. The DSL
carries the operator's three-loop structure end to end.

## Section 5 — Alternatives Considered

### 5.1 Keep linear + `mode: loop`, fake states with conditionals

Encode the PR loop as one linear playbook whose `llm` steps branch internally
("if findings, fix; if gate, merge; else stop and reschedule").

**Rejected.** `mode: loop` restarts from step 1 unconditionally — it has no
guarded exit and no distinct per-state actions. The branch logic would live
inside `llm` step prose, which means the "current state" exists only in the
model's working context and evaporates on compaction or crash — the exact
failure that makes today's hand-authored cron unreliable. Faking states with
conditionals *is* smuggling a state machine into prose; the DSL would describe
a straight line while the real control flow hides in an `llm` context block,
unreviewable and unresumable. The construct we need is the one we would be
hiding.

### 5.2 An external orchestrator / real state-machine engine

Run the machine in a daemon (a Temporal-style engine, or a Python state-machine
library) and call out to the LLM only for judgment steps.

**Rejected.** The executor is defined as an LLM reading a protocol doc, not a
daemon, and that is load-bearing: half the actions and one guard clause are
judgment (fix findings, assess materiality) and half the actions call
sub-agents. A daemon cannot do those; it would have to round-trip every
non-trivial step back to an LLM, so the "engine" becomes a scheduler wrapping an
LLM that is doing the real work — which is what `/loop` + `/punt:auto --resume`
already are, with far less machinery. Splitting the machine across a daemon and
an LLM also doubles the source of truth for "current state" and breaks
crash/resume coherence: two systems that can disagree about where the machine
is. Minimal means one executor, one run-state file.

### 5.3 Per-state playbook files chained by tail-call

Make each state its own linear playbook that ends by invoking the next
(`/punt:auto fixing` calls `/punt:auto watch`).

**Rejected.** The transition guards and shared parameters scatter across files;
no single artifact shows the machine, so the graph is only reconstructable by
reading every file's last step. Cycles — `watch <-> fixing` — become mutual
recursion across files, and a reviewer cannot see the loop without tracing
tail-calls by hand. The design goal is a **reviewed artifact** for the PR loop;
a machine smeared across N files is the opposite. One machine, one file, the
graph visible in the `states` list.

## Section 6 — Open Questions

### 6.0 Settled in round-2 review

- **Run-state location — settled: the local zone.** Run-state persists to
  `.punt-labs/local/punt/auto/<name>-<instance>.json`. It is per-checkout,
  machine-local live state the executor rewrites every tick, which
  `standards/punt-labs-dir.md` §3 routes to the local zone
  `.punt-labs/local/<tool>/` (§1 core principle; §5 "Live State is Never a
  Tracked File"). This is inside the tool's own subtree, not a new top-level
  dot-directory — `punt-labs-dir.md` §2 forbids the latter, which an earlier
  draft's `.punt/auto/` would have created. It needs **no new `.gitignore`
  rule**: the canonical block's `.punt-labs/**/local` line (§6) already ignores
  the whole zone. `.tmp/` is ruled out because `make clean` wipes it
  (confirmed, `Makefile:29`) and a PR watch loop can outlive a clean; that only
  rules out `.tmp/`, it does not justify a new root. (Details in §2.4.)

### 6.1 Remaining open questions

Each carries a recommendation, per the design-gate discipline.

1. **Judgment guard-checks — admit them, or force everything to shell.**
   **Recommend admit them** (`type: llm` guard-check), scoped to the one
   `merge_gate` clause that is irreducibly judgment ("no unaddressed material
   findings"). Forcing it to shell would either drop the clause or fake it with
   a brittle comment-scraper; the honest encoding is a judgment guard. Keep
   `script` the default so machines stay mostly deterministic and guard-checks
   read like preconditions. **Constraint the operator should accept with it:** a
   judgment-gated transition is **not reproducible across runs** — the same PR
   state can route differently on two evaluations because an LLM verdict is not
   a pure function of the inputs the way a shell exit code is. Deterministic
   (shell) guards are reproducible; a machine with a judgment guard trades that
   property for expressiveness on exactly the clauses that need it. This is
   acceptable here because the clause is judgment in the standard today, but it
   is a real weakening of the machine's determinism and should be a conscious
   ratification, not a silent one.

2. **Instance keying and concurrency.** Two open PRs need two independent
   `pr-loop` runs. **Recommend the `instance` expression** (`instance:
   pr-${pr}`) keying the run-state file, so concurrency is one file per
   instance with no shared mutable state. Open sub-question: should the executor
   refuse to start a second run with the same instance key (a lock), or treat a
   second start as a resume? **Recommend treat-as-resume** — it is idempotent
   and avoids a lock file that can leak.

3. **Sub-machine invocation.** The backlog loop runs `pr-loop` per unit
   (§4.1). Is that a new action type (`type: playbook`), or does the executor
   just `/punt:auto pr-loop pr=<n>` from an `llm` action? **Recommend the
   latter for now** — an `llm` action that invokes the nested playbook — and
   defer a first-class `type: playbook` action until a second nesting case
   exists. Minimal: do not add a construct on one example.

4. **Unbounded polling / stuck safety.** If CI never resolves, `watch` polls
   forever. **Recommend an optional per-state `deadline`** (e.g. `deadline:
   2h`) that, when exceeded with no transition fired, routes to an operator-
   notify state — opt-in, absent from the core, added to the worked example
   only if the operator wants a ceiling. Not in the minimal core because no
   loop we run today needs it; noted so it is not rediscovered under an
   incident. A lighter alternative the evaluator raised: an operator-visible
   "still waiting Nh" ping instead of a full deadline state — cheaper, and
   worth offering as the first increment.

5. **Scheduling ownership.** `poll` compiles to a `/loop` registration (§2.3).
   Is that binding correct, or should `/punt:auto` own its own cron primitive?
   **Recommend bind to `/loop`** — the org standard already mandates `/loop`
   over raw `CronCreate`, and a machine's `poll` is exactly the recurring poll
   `/loop` exists for. Reusing it means no new scheduler and one place that
   knows how to cancel a tick. The coupling is an **explicit dependency**, not
   an implicit convenience (§2.3): a machine with a `poll` state cannot tick
   outside a `/loop`-capable executor, and because `/loop` registrations are
   session-scoped, a machine pauses when its session dies and resumes only on
   the next `/punt:auto <name> --resume`. That is a documented limitation of
   binding to the session-scoped scheduler, not a defect to engineer away with
   a daemon the design deliberately rejects (§5.2).

6. **Helper-script packaging and home.** The worked example references five
   helper scripts — `reviewer-gate.sh`, `pr-needs-work.sh`,
   `unresolved-threads.sh`, `commit-push-if-dirty.sh`, `branch-of-pr.sh` —
   that wrap the `gh`/GraphQL specifics of the merge gate and cleanup. Where do
   they live and ship: packaged with `punt` and deposited into the repo on
   enable (the vendored zone, `punt-labs-dir.md` §7), or repo-local under
   `scripts/`? **Recommend punt-packaged and deposited under
   `.punt-labs/punt/`.** These scripts encode org standards — the exact
   `merge_gate` clauses (workflow §5) and the `git.md` §4 cleanup — so they must
   version with the standard and the tool, not be copy-pasted per repo where
   they would drift out of sync with the gate they enforce. Repo-local
   `scripts/` would mean fifteen divergent copies of the merge gate; a vendored,
   tool-shipped set is one authoritative copy that `enable`/upgrade refreshes
   wholesale (the vendored-zone determinism contract, `punt-labs-dir.md` §7).
   Sub-question the operator should rule on: whether these are `pr-loop`-specific
   or a general `punt`-shipped gate library other machines reuse — I lean
   general, since `merge_gate` is not unique to `pr-loop`.

## Backward Compatibility

Restated plainly, since it is a success criterion: every existing linear
playbook — `release`, `autopilot`, `makefile`, `permissions-rollout`,
`reconcile-memory`, `standards-rollout` — remains valid and unchanged. The executor selects linear vs. machine by the presence of `steps`
vs. `states`. No existing field changes meaning; `mode`, `parameters`,
`preconditions`, and the step vocabulary are carried verbatim into states as
actions. A linear playbook is the degenerate one-state machine: the executor
runs a step list and a single state's action list through the same code path,
so there is one DSL, not two.
