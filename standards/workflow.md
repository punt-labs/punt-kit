# Workflow Standards

**Updated:** 2026-07-26

How Punt Labs teams track work, delegate it, develop code, and ship it. All
work runs as **three nested loops**. The outermost loop owns the backlog:
what is worth doing and in what order. The middle loop owns one pull request:
a single shippable, revertible change. The innermost loop owns one mission: a
single delegated piece of work inside that change. The unit of delegation is
the **ethos mission** — a typed contract that replaces prose instructions
with declared roles, file boundaries, success criteria, and bounded review
rounds.

```text
Level 1 — Backlog loop   one iteration = one work batch     (beads)
  Level 2 — PR loop      one iteration = one pull request
    Level 3 — Mission    one iteration = one delegated mission
                         (design, code, test — a do-while)
```

Each level hands work down and receives finished results back. Two flow
rules bind the levels together:

- **Scope escalates up, never down.** A mission that uncovers a bigger
  problem grows its PR; a PR that uncovers a genuinely new line of work files
  a bead for the backlog loop. Never demote mid-flight.
- **Defects flow down, never up.** Anything found while a PR is open is
  fixed in that PR — never sent back to the backlog as a "follow-up bead."

This standard is the normative home of the loop structure. Each repo deploys
a `docs/WORKFLOW.md` that instantiates it — naming that repo's demo, its
worker/evaluator table, its formal-verification classes, and its
backlog-ordering specifics — and points here for the frame. This document
carries what those instantiations share; it never absorbs per-repo specifics.

---

## 1. Scope and Ownership

This standard owns the work lifecycle: the three loops, issue tracking,
workflow tiers, mission-based delegation, human-in-the-loop gates, branch and
commit discipline, quality gates, and session protocol. Adjacent concerns are
owned by neighboring documents — cross-reference them, do not restate them:

| Concern | Owning standard |
|---------|-----------------|
| PR boundaries, local and remote review sequencing, what "installed" means | [PR and Review](pr-review.md) |
| Judgment defaults: reversibility, test proportionality, confidence calibration | [Agent Engineering](agent-engineering.md) |
| `make check` targets and gate composition | [Makefile](makefile.md) |
| Branch protection, CI, Copilot configuration | [GitHub](github.md) |
| Release phases and cross-repo propagation | [Release Process](release-process.md) |
| Mission contract schema, archetypes, pipeline templates, mission CLI | ethos documentation (see §6) |
| Per-repo instantiation: the demo, worker/evaluator table, formal classes | each repo's `docs/WORKFLOW.md` |

Terms used throughout:

- **Operator** — the human accountable for the repo.
- **Leader** — the session (human or agent, e.g. `claude`) that owns the
  branch, dispatches missions, and merges.
- **Worker** — the specialist a mission delegates work to (e.g. `rmh`).
- **Evaluator** — the reviewer named in the mission contract, distinct from
  both leader and worker.

---

## 2. Loop State

The pseudocode at each level gives the control flow; a small Z schema at
each level gives the doorway conditions — what must be true to enter an
iteration and what must be true to leave it. The state those schemas observe:

```text
LoopState
  signals       : ℙ SIGNAL  -- issues, alerts, messages not yet triaged
  open          : ℙ BEAD    -- open beads: the single work funnel
  validated     : ℙ BEAD    -- re-proven against current main
  claimed       : ℙ BEAD    -- the current batch
  closed        : ℙ BEAD    -- beads completed by a merged PR
  activeWorkers : ℙ WORKER  -- sub-agents editing a shared worktree
  testCount     : ℕ         -- tests collected by the suite
  ------------------------------------------------------------------
  validated ⊆ open
  claimed   ⊆ validated
  open ∩ closed = ∅         -- a bead is open or closed, never both
```

A bead's lifecycle is a walk through these sets: `open → validated →
claimed → closed`. Steps that were performed ("the recap was sent") appear
as named predicates over declared terms, never as bare primed flags.

The schemas in this standard are the org-wide minimum. A per-repo
`docs/WORKFLOW.md` **may** extend them — add state components, or strengthen
a doorway with extra conjuncts (e.g. an OO-improvement obligation on mission
exit, or a repo-specific demo predicate on PR exit). It **must not** weaken
them: every conjunct stated here holds in every repo.

---

## 3. Roles

The operator owns requirements and design direction, rules on genuine design
forks, and confirms demos of user-facing behavior. The leader runs
everything else: the backlog, the missions, the review cycles, and the
merges.

**Review of code is agent-owned end to end**: the evaluator inside each
mission, the local review agents on the diff, and the remote reviewers
(Copilot, Bugbot) on the PR. There is no human code-review gate. The
operator reads code in the IDE, but that inspection is separate, feeds
design discussion only, and nothing in these loops waits on it; when it
happens, it happens locally, before the PR — the PR is a merge gate, not a
review mechanism ([PR and Review](pr-review.md)).

Two human gates do exist, and neither is a diff review:

- **The design-ratification gate** (§7). When a design mission closes on
  architectural work, implementation waits for the operator's ruling on
  substantive issues. This gates *direction, before code exists*.
- **The demo** (Level 2, §5). For user-facing behavior the operator confirms
  the observed outcome — what ran, not what changed. This gates *behavior,
  after code runs*.

"There is no human review gate" and "the operator must ratify designs"
therefore never conflict: the first is a statement about diffs, the second
about direction. Human judgment binds before implementation (design) and
after execution (demo) — never on the diff between.

---

## 4. Level 1 — The Backlog Loop

The backlog loop keeps the bead tracker true and decides what to work on
next. Beads are the single funnel: every piece of work above the trivial
tier (T4, below), whatever its origin, is a bead before it is anything else.
One iteration selects and completes one batch of work. The loop runs at
session start and again whenever the current batch is done.

```text
function backlog_loop():

    # 1. INTAKE — every signal becomes a bead or is disposed at the door
    for signal in [github_issues, dependabot_alerts, biff_messages,
                   operator_requests, new_scope_found_while_working]:
                   # a defect inside an open PR's unit is fixed in that PR,
                   # never filed — only genuinely NEW scope arrives here
        if duplicate(signal):  close_at_door(signal, link_existing_bead)
        elif invalid(signal):  close_at_door(signal, stated_reason)
        else:                  bd_create(signal, labels, link_back_to_source)

    # 2. VALIDATE — a bead must be true before it is workable
    for bead in candidates(bd_ready):
        confirm it is still real against current main
        confirm nothing merged or decided has superseded it
        confirm it is one rollback-coherent unit (split or merge if not)
        confirm its blocked-by links reflect reality
        otherwise: fix the bead, or close it with the reason

    # 3. ASSESS — automatic ordering; escalate only on a genuine fork
    order = sort(validated, by:
        security severity                  # open HIGH/CRITICAL first, always
        > broken user journeys             # bugs on paths users actually hit
        > active epic continuity           # finish what is started
        > debt that blocks throughput      # decomposition, testability
        > features)
    if the ordering hits a fork the charter cannot resolve:
        ask the operator for a focus ruling
    else:
        proceed without asking

    # 4. SELECT AND EXECUTE
    batch = claim a realistic set from the top of the order
    for unit in rollback_coherent_units(batch):
        pr_loop(unit)                      # Level 2

    # 5. CLOSE OUT
    close GitHub issues resolved by the merged PRs, linking each PR
    send the batch recap                   # covers what the per-merge recaps
                                           # do not: intake dispositions, beads
                                           # closed at validation, order changes
    return to intake — new signals have accrued while working
```

Entry and exit for one batch iteration:

```text
EnterBatch ≙ [ LoopState ]                -- no precondition: the backlog loop
                                          -- is a do-while(true); intake always
                                          -- has standing to run

ExitBatch ≙ [ Δ LoopState; mergedPRs : ℙ PR |   -- the PRs merged this batch
  intakeDisposed(signals)                 -- every signal observed at this
                                          --   iteration's intake became a bead
                                          --   or was closed at the door with a
                                          --   reason; new signals keep accruing,
                                          --   so the live queue is never empty
  ∧ claimed′ = ∅ ∧ claimed ⊆ closed′      -- the batch drained: every claimed
                                          --   bead closed by a merged PR
  ∧ resolvedIssuesClosed(mergedPRs)       -- GitHub issues answered with their PR
  ∧ batchRecapSent(claimed) ]
```

### Beads: the single funnel

All projects use **beads** (`bd`) for issue tracking. Beads are the durable,
cross-session source of truth for what work exists and what state it is in.
Every repo must have beads initialized (`bd init`); the `.beads/` directory
is committed to git.

- `bd create "title"` to create issues with `--type` (task, bug, feature,
  spike) and `--priority` (1-5)
- `bd ready` to find available work
- `bd update <id> --status in_progress` before starting
- `bd close <id>` when complete
- Work is not complete until `git push` succeeds

Issues must have: a clear title in imperative form; a description with
enough context for another engineer (or agent) to act on; correct type and
priority; dependencies declared (`--blocks`, `--blocked-by`) when
applicable.

### Intake

Work arrives from five places: GitHub issues, Dependabot security alerts,
biff messages from agents in other repositories, requests from the operator,
and new lines of work discovered while building. That last source carries a
boundary: a defect found inside the unit of an open PR is fixed in that PR
and never becomes a bead; only genuinely new scope — discovered outside any
open PR, or clearly a separate rollback unit — enters at intake. At intake,
each signal is either turned into a bead or closed at the door with a stated
reason — duplicate of an existing bead, or invalid. Nothing is left sitting
in an external queue: a GitHub issue gets a reply naming its bead, and it is
closed when that bead closes.

Security alerts map severity to priority: a critical or high alert becomes a
P1 bead and goes to the front of the order. Security work does not wait in
the backlog.

Intake must not depend on remembering to look. A recurring poll or a
session-start sweep checks the GitHub issue list and the Dependabot alert
list, so an alert filed overnight is a bead by the time the first batch is
selected.

### Validation

The codebase moves; beads rot. Before a bead is workable, confirm it is
still real: reproduce the bug or re-check the premise against current main,
confirm no merged PR or design decision has superseded it, confirm it
describes one rollback-coherent unit (split or merge if not), and confirm
its dependency links are correct. A stale bead is closed with a note stating
what was checked. A bloated bead is split. Validation covers the candidates
for the coming batch, not the whole backlog every time.

Dispatching a fix for a bug that no longer reproduces wastes a full mission
round; validation costs minutes.

### Assessment

Ordering is automatic in the steady state. The sort is: security severity,
then broken user journeys, then active epic continuity (an epic in flight
keeps its claim until done — interleaving epics is how a backlog churns
without shipping), then debt that blocks throughput, then features. Each
repo's `docs/WORKFLOW.md` states what each rank means for its product.

The operator is asked for a focus ruling only when the ordering hits a
genuine fork the rules cannot resolve: two epics competing to be active, a
strategic pivot, or a drift in the debt-versus-feature balance. Direction
belongs to the operator; sequencing inside a settled direction does not
require asking.

### Tiers: matching ceremony to design ambiguity

Selection also decides how much workflow a unit gets. The deciding factor is
**design ambiguity**, not size. Each tier maps to an ethos pipeline template
(§6); the pipeline determines which mission stages the work passes through.

| Tier | Scope | Pipeline | Tracking |
|------|-------|----------|----------|
| **T1** | Epics, cross-cutting work, competing design approaches | `full` | Beads with dependencies |
| **T2** | Features: multi-file, clear goal, needs exploration | `standard` | Beads + missions |
| **T3** | Tasks and bugs with an obvious implementation path, worth tracking | `quick` | Beads + one mission |
| **T4** | Trivial: typo, single-line fix, mechanical refactor with no design choice | none — direct change | No bead; the commit is the record |

T4 is the one exit from the funnel: work too trivial to track skips the bead
and the mission — the commit is its whole record. Default to T4 when in
doubt: the cost of under-tiering is one escalation; the cost of over-tiering
is ceremony on every trivial change.

**Nature overrides size.** When the work has a recognizable nature, use the
matching pipeline instead of the size-based default: `docs` for
documentation-only changes, `product` for new user-facing features (PR/FAQ
first), `formal` for stateful systems and protocols (spec first), `coe` for
cause-of-error investigations, `coverage` for targeted test-coverage work.
`ethos mission lint` suggests a pipeline from the contract's context and
write set; the suggestion is advisory and the leader decides.

**Escalation only goes up.** If T3 work reveals unexpected scope, escalate
to T2. Never demote mid-flight — the loop-frame scope rule applied to tiers.

### Beads vs session task lists

Beads are the record; in-session task lists are the display. Use the session
task list (e.g. `TaskCreate`) only to make the current batch visible to the
operator — one entry per claimed bead, marked complete as each bead closes.
Work that spans sessions must be a bead, never only a session task.

### Batch close-out and session close

Close-out is inside the loop: close the GitHub issues the merged PRs
resolved (linking each PR), send the batch recap, and return to intake.

Before ending any session:

```bash
git status              # Check for uncommitted work
git add <files>         # Stage changes
git commit -m "..."     # Commit
bd sync                 # Sync beads with git
git push                # Push to remote
```

Work is **not** complete until `git push` succeeds. (Mission workers stop at
the commit — the push belongs to the leader, per §6.)

---

## 5. Level 2 — The PR Loop

One iteration of the PR loop produces one merged pull request. It is entered
when the backlog loop hands down a unit of work sized for throughput, and it
runs the missions (Level 3) needed to build that unit. All repos require
PRs — no direct pushes to main, even for docs; branch protection enforces
this with zero bypass actors.

### Sizing: throughput, not purity

Nobody reads these diffs line by line for style. Agents review them, and
they squash-merge. So the size of a PR is an economic decision, not a
hygiene one:

- **The floor is transaction cost.** Every PR pays a roughly fixed
  overhead — branch, full-diff review rounds, verification, CI, remote
  review cycles, the merge gate, the recap. A PR too small pays that
  overhead for too little value.
- **The ceiling is reviewer effectiveness.** The reviewers are agents, and
  past a certain diff size their quality drops. A PR too large buys
  throughput at the cost of review quality.
- **The typical right size** is several small beads batched together, or one
  coherent slice of a larger bead. Related small fixes discovered in one
  validation or review pass ship as a single cohesive round-up PR — one
  rollback unit — rather than one PR per fix. A bead too large to slice into
  one PR is mis-filed: decompose it into an epic whose child beads fit the
  band.
- **Rollback coherence still binds.** Whatever merges must revert together
  sensibly. That is the one structural constraint — the same
  rollback-granularity criterion [PR and Review](pr-review.md) uses to
  prohibit micro-PRs. "Purity," "one concern per PR," and "keep the diff
  small" are not criteria — a docs fix, a debt paydown, or an adjacent bug
  fix riding along is welcome, and an improvement is never held back or
  split out for tidiness.

```text
function pr_loop(unit):

    # A. BUILD — missions, one at a time
    branch from main                      # feat/ fix/ refactor/ docs/ chore/
    if unit is architectural (new contract, new types, cross-cutting flow —
                              each repo's WORKFLOW.md names its classes):
        design mission first, with no prescribed write-set
        leader reviews the design end-to-end
        substantive issues go to the operator as concrete decisions (§7)
        implementation waits for the operator's ratification
    for mission in unit:
        mission_loop(mission)             # Level 3
        # bug fixes are TDD: a failing test reproduces the defect first
        # coverage rises with every mission

    # B. FULL-DIFF VERIFICATION (local, before any PR exists)
    make check                            # full gate on the accumulated diff
    repeat:
        findings = local review agents on the full diff   # pr-review.md
        fix every finding in this PR      # no deferrals
    until a round produces zero findings

    # C. VERIFY — drive the real entry point, not just the tests
    install the built artifact            # pr-review.md "What Installed Means"
    restart any long-running process      # a live daemon serves old code
                                          #   until restarted
    write down the expected outcome, then exercise the change through its
        real entry point; compare actual to expected
    the operator confirms what only a human can judge   # the demo — each
                                          # repo's WORKFLOW.md defines its own

    # D. SHIP
    bd close the bead(s)                  # close before push, once the unit
                                          #   is verified and merge-ready
    push; create the PR
    request Copilot review once, on open
    schedule a background poll            # never a blocking watch, never a
                                          #   foreground sleep loop

function poll_tick(pr):
    state = current reviews, threads, checks
    for finding in unaddressed(state):    # handled now, never on a later tick
        fix it in this PR                 # or dismiss with the exact finding,
                                          #   the specific reason it does not
                                          #   apply, and the code reference
        make check; commit; push          # each push restarts the gate
        resolve the thread                # the leader resolves, not the worker
    if merge_gate(state): merge (squash); close_out()

function merge_gate(state) -> bool:
    return CI green on the latest commit
       and Copilot has reviewed the latest commit   # it re-reviews on push
       and (Bugbot has reviewed the latest commit
            or Bugbot never reviewed this PR and more than six minutes
               have passed since CI went green)
       and zero unresolved review threads
       and the latest review round had zero material findings
    # When this returns true: merge. Do not ask, do not wait.

function close_out():
    cancel the poll loop
    delete the branch; checkout main; pull
    send the merge recap                  # every merge, unprompted
    start the next unit immediately       # no stopping to report
```

Entry and exit for one PR iteration. `merge_gate` in the pseudocode is the
pre-merge subset of these conditions; `ExitPR` describes the state after
close-out completes.

```text
EnterPR ≙ [ LoopState; unit : ℙ BEAD |
  unit ⊆ claimed
  ∧ rollbackCoherent(unit)                -- reverts together sensibly
  ∧ inThroughputBand(unit)                -- above transaction cost,
                                          --   below reviewer degradation
  ∧ (architectural(unit) ⇒ designRatified(unit)) ]  -- operator has ruled

ExitPR ≙ [ Δ LoopState; pr : PR |
  merged(pr)
  ∧ localFindings(pr) = ∅                 -- held BEFORE the PR opened
  ∧ verified(pr)                          -- driven through its real entry
                                          --   point BEFORE the PR opened;
                                          --   the operator confirmed the demo
                                          --   where only a human can judge
  ∧ ciGreen(head(pr))
  ∧ reviewedByBots(head(pr))              -- Copilot + Bugbot on the latest
                                          --   commit, per the merge_gate rules
  ∧ unresolvedThreads(pr) = ∅
  ∧ materialFindings(latestRound(pr)) = ∅
  ∧ beadsOf(pr) ⊆ closed′
  ∧ mergeRecapSent(pr) ]
```

### Branch discipline

All code changes go on feature branches. Never commit directly to main.

```bash
git checkout -b feat/short-description main
```

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code improvements |
| `docs/` | Documentation only |
| `release/` | Release version bumps |
| `chore/` | Maintenance and housekeeping |

Micro-commits: one logical change per commit, 1–5 files, quality gates pass
before every commit (§7). Commit messages follow Conventional Commits
format: `type(scope): description`.

Set a biff plan (`/plan "short description"`) before starting work so
teammates can see what you are doing. If `/who` shows another human or agent
active in the same repo, work in a worktree (`git worktree add` or the
`--worktree` session flag) to avoid file conflicts — mission workers should
run in isolated worktrees by default.

### Local review before the PR

Full-diff local review is where issues die cheaply: a local round costs
seconds; a remote review cycle costs minutes to hours. The review sequence —
per-mission review, the full-diff pass, agent selection, and the dismissal
documentation standard — is owned by [PR and Review](pr-review.md). Every
finding is fixed in this PR; opening a PR with unresolved local findings is
a procedural violation.

### The verification gate

`make check` passing means the code compiles and the tests pass. It does not
mean the feature works. Before any PR opens, the feature is driven through
its real entry point — the installed artifact, any long-running process
restarted so the running code is the just-built code — with the expected
outcome written down first, then compared against actual output
([PR and Review](pr-review.md) owns the mechanics and what "installed"
means per project type).

The human-judged part is the **demo**: the operator confirms what no
introspection API can attest — audio that sounded right, pixels that
rendered, a message actually delivered. Each repo's `docs/WORKFLOW.md`
defines its demo. This is a demo, not a diff: the operator verifies observed
behavior, never reviews code (§3). Docs-only changes are the one exception —
a lint pass and a read-through is their verification.

### Remote review and merge

Remote review (Copilot, Bugbot) is an automated second opinion on
already-clean code — sequencing, dismissal rules, and re-request protocol
are owned by [PR and Review](pr-review.md). The `merge_gate` predicate above
is the whole merge decision: when it returns true, merge — do not ask, do
not wait for one more empty round.

### Documentation in the diff

A PR that changes user-facing behavior updates its docs in the same diff —
the entry is part of what gets reviewed, never added retroactively on main.

- **CHANGELOG.** Projects that maintain a CHANGELOG follow
  [Keep a Changelog](https://keepachangelog.com/) format, with bracketed
  version headings (`## [Unreleased]`, `## [X.Y.Z] - YYYY-MM-DD`) — release
  tooling parses the brackets. Entries go under `## [Unreleased]`, grouped
  as Added, Changed, Fixed, Removed (omit empty groups). Internal-only
  changes (CI config, dev tooling, test-only) do not get entries.
- **DESIGN.md.** Use `DESIGN.md` at the repo root. Write an ADR entry when a
  decision is non-obvious, has rejected alternatives worth recording, or
  would confuse a future reader. Consult the log before proposing changes to
  settled architecture; do not revisit a settled decision without new
  evidence. See [Design Decision Log](../patterns/design-decision-log.md)
  for the full pattern.

### The merge recap

After merging a PR, send a recap email to <jim@punt-labs.com> via beadle —
every merge, unprompted.

- **Subject**: `[repo-name] PR #N merged: <title>`
- **Required**: bead ID, PR link, 1-paragraph summary of what changed, why,
  and how it left the system better
- **Include when relevant**: design decisions made, test coverage notes,
  follow-up work created

---

## 6. Level 3 — The Mission Loop

One iteration is one delegated mission: a single piece of design,
implementation, test, or review work executed by a specialist sub-agent
under an ethos mission contract. The next mission does not start until this
loop completes on the current one.

The mission loop is a do-while: the work runs at least once, and the
review-and-fix cycle repeats until a round comes back clean.

```text
function mission_loop(mission):
    contract = write_contract(mission)   # problem, invariants, quality bar,
                                         #   commit discipline — never a
                                         #   write-set for design work
    dispatch(contract)                   # mission create + background spawn;
                                         #   verify the worker is running
    do:
        worker designs / codes / tests   # tests lead; TDD for bug fixes
        worker commits locally           # each commit passes make check
        result   = worker submits
        findings = evaluator review      # a DISTINCT specialist
                 + leader verification   # run the change; review agents on
                                         #   the mission diff
        if findings: reflect(findings)   # another round, same mission
    while findings remain
    close(mission)
```

Entry and exit for one mission iteration:

```text
EnterMission ≙ [ LoopState; m : MISSION |
  contracted(m)                           -- problem, invariants, quality bar,
                                          --   commit-per-step discipline
  ∧ workerRunning(m)                      -- dispatch is two operations; a
                                          --   contract alone is orphaned work
  ∧ soleWriter(m)                         -- one writer per worktree; a second
                                          --   concurrent writer gets its own
                                          --   git worktree
  ∧ (formalClass(m) ⇒ modelChecked(m)) ]  -- each repo's WORKFLOW.md names the
                                          --   classes that require a model
                                          --   check before implementation (§7)

ExitMission ≙ [ Δ LoopState; m : MISSION |
  verdict(m) = accept                     -- from an evaluator ≠ worker
  ∧ findings(m) = ∅                       -- the do-while ran dry
  ∧ (∀ c : commitsOf(m) • checkGreen(c))  -- every commit passed make check
  ∧ testCount′ ≥ testCount                -- coverage never decreases
  ∧ missionClosed(m) ]
```

### Missions: typed delegation

Prose delegation fails in two known ways: the worker drifts (touches files
outside the intent, revises its own success criteria mid-round), and the
decision context evaporates (nobody can later answer why approach A beat
approach B). A **mission contract** fixes both. It is a typed YAML document
that declares, before any work starts:

- **leader**, **worker**, and **evaluator** — the evaluator's definition is
  content-hash-pinned at creation so review criteria cannot drift
  mid-mission
- **write set** — the files the worker may modify; the store refuses
  overlapping write sets between open missions and rejects self-review
  (evaluator same as worker or leader)
- **success criteria** — testable statements, verified before close
- **budget** — a bounded number of rounds, with a reflection recorded
  between rounds
- **results and reflections** — append-only artifacts that survive the
  session

The contract schema, archetype constraints, and validation rules are defined
in the ethos documentation — reference them, do not restate them:

- [Archetypes and Pipelines Guide](https://github.com/punt-labs/ethos/blob/main/docs/archetypes-and-pipelines.md)
  — contract fields, built-in archetypes, pipeline templates, worked examples
- [Audited Delegation](https://github.com/punt-labs/ethos/blob/main/docs/audited-delegation.md)
  — Tier A (ad-hoc) vs Tier B (contract-bound) spawns, audit records
- `ethos mission --help` — the CLI surface (create, dispatch, claim, show,
  log, results, reflect, advance, close)

### When a mission is required

A mission contract is **required** whenever code or normative-document work
is delegated to a worker at tiers T1–T3 (§4) — that is, any delegated change
that touches multiple files, alters user-facing behavior or a public
contract, or amends a standard consumed by other repos.

A mission is **not required** for:

- T4 changes — no bead, no mission; the commit is the record
- Review-cycle fix rounds — findings from local review agents or remote
  reviewers (Copilot, Bugbot) may be fixed by a bare `Agent()` spawn without
  a mission contract. The finding is the spec and the write set is obvious,
  so a contract adds nothing. Spawn the domain specialist, not a generic
  shell — a Python finding goes to the Python worker. The leader reviews the
  finding before delegating, which collapses (not skips) the design step.
  Bare spawns are still audit-tagged by ethos (Tier A audited delegation)
  but carry no write-set enforcement or evaluator. This is the one
  delegation that is not a mission.

A leader **may** still wrap either case in a mission when the audit surface
is worth the ceremony (e.g. a T4 change to release mechanics).

### Per-repo instantiation

Each repo's `CLAUDE.md` (or its `docs/WORKFLOW.md`) must carry a
worker/evaluator table mapping the repo's task types to identity handles —
the local instantiation of the mission harness. Example rows from punt-kit:

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| Standards doc authoring (`standards/*.md`) | `mdm` | `rop` |
| Python implementation (`punt` CLI) | `rmh` | `gvr` |

Within each row the worker and evaluator must be distinct handles, and the
leader is never the evaluator. Ethos enforces this at contract creation; the
table makes the assignment predictable before a contract exists.

### Who does what

The leader runs the workflow; the specialists produce the work. The boundary
is strict in both directions.

**The leader owns the workflow.** The backlog, the mission contract,
dispatch, monitoring, the local review agents (run on each mission's diff
and on the full diff), the verification, and every git and GitHub operation:
creating branches, pushing, opening the PR, driving remote review, resolving
threads, merging, and closing out. The leader does not write production
code.

**The worker owns the work.** The thinking and the code inside its mission —
the design decisions its contract leaves open, the tests, the
implementation, and local commits on the current branch, inside its write
set, on its own timeline. A worker never creates branches, never pushes,
never opens PRs, and never touches review threads — a worker that finishes
its write set reports a result; it does not ship. Putting workflow
operations into a worker's prompt is a contract defect.

**The evaluator** — always a different specialist from the worker, per the
repo's table — reviews the worker's result inside the mission before the
leader accepts it.

### The contract

The leader writes the mission contract: the problem, the invariants, the
quality bar, and the commit discipline. A design mission's contract never
prescribes a write-set — the specialist decides what to create, split, or
extract. The design brief must answer:

1. What this mission changes
2. How it leaves the system better — structural improvement, not just
   feature delivery: coupling, cohesion, naming, module boundaries
3. What approach was chosen and why

If the design reveals a non-obvious decision with rejected alternatives
worth recording, write a `DESIGN.md` ADR entry (§5). The commit message is
sufficient for most changes.

Every implementation mission must include commit-per-step in its success
criteria. Workers that accumulate uncommitted changes across many files are
a session-timeout liability — if the worker terminates mid-edit, the leader
must either commit by proxy or lose the work. Required criterion text:

> Commit incrementally — one commit per logical step (file group, single
> concern, or single PR-equivalent slice). Each commit must pass
> `make check`. Do not accumulate more than 30 minutes of uncommitted
> changes.

### Dispatch is two operations

`ethos mission create` (or `dispatch`) only writes the contract. The worker
is spawned by a separate
`Agent(subagent_type=<worker>, run_in_background=true)` call. After every
dispatch, verify the worker is actually running before considering the
mission active. Forgetting the spawn leaves the contract orphaned — nothing
happens, and nobody notices until the round budget is audited.

### Execution: tests lead

Write the failing test first, then the code that makes it pass — a bug fix
starts from a failing test that reproduces the defect, and the fix is done
when it passes. Tests and code land in the same commit. If writing the test
first is impractical, write the code first and the test immediately after —
the same-commit rule still holds. The test count never goes down.
Proportionality (what deserves how much testing) is owned by
[Agent Engineering](agent-engineering.md) §10.

If a worker hits a decision point mid-implementation, it stops and surfaces
the decision. Implementation does not resume until the design question is
answered — by the leader, or by the operator when the gate in §7 applies.

### Monitoring a running mission

Judge worker progress by the filesystem, never by commits. A worker editing
files is working, even with zero commits — analysis and reading are
invisible; the absence of a commit is not a stall and never a reason to
intervene, commit by proxy, or kill the agent. Only a genuine filesystem
stall (no edits changing over a long window) with an unresponsive worker
justifies a status message and, as a last resort, taking over.

---

## 7. Gates

The loops pass through gates at their handoffs. One is mechanical and binds
every commit at every level; the rest are where the human decides. The
operator's rulings are not advisory — work does not proceed past a gate
until the ruling exists.

### Quality gates bind every commit

`make check` is the quality-gate entry point and must pass before every
commit — not before the PR, before each commit, at every level of the loops:
the worker's commits inside a mission, the leader's fix commits on an open
PR. A commit that fails `make check` is a broken commit. The
[Makefile standard](makefile.md) owns what `check` composes per project
type.

Zero violations, zero errors, all tests green. When gates fail, fix the
issue — do not commit with known failures, and do not skip gates with
`--no-verify` or equivalent.

Suppressions (`# noqa`, `# type: ignore`, `xfail`, lint disables) are not an
authorized way to make gates pass. A suppression is permitted only when a
standard explicitly pre-authorizes its class, or the operator approves the
specific instance. The volume of errors does not change this rule — every
error is fixed or escalated, never suppressed autonomously.

### The design → implementation gate

Between a design mission closing and an implementation mission dispatching,
the leader **must** review the design for substantive issues and escalate
them to the operator. A **substantive issue** is anything that deviates from
the operator's stated structure or goals, introduces a layering violation,
breaks a documented invariant, creates a naming conflict, or would cost more
to fix in implementation than in the design.

Required pattern:

1. Read the merged design end-to-end. Cite file:line for each issue found.
2. For each issue, write a concrete "recommend X" alternative.
3. Present to the operator with an explicit ask per issue: "Decision needed
   on each before implementation dispatches."
4. Wait for the operator's ruling. Do not create the implementation
   contract, dispatch a worker, create branches, or write code in the
   interim.
5. If the operator says "proceed as designed," that is ratification —
   dispatch.
6. If the operator wants amendments, amend the design first, then dispatch
   against the amended design.

Forbidden patterns:

- Presenting issues without a recommendation per issue — a list of open
  questions hides the leader's judgment and gives the operator no clear ask.
- Dispatching implementation while a "should we discuss?" question is
  outstanding — the implementation builds on decisions the operator has not
  ratified.
- Treating discovery during implementation as equivalent to design-time
  resolution. Implementation discovery is expensive: each defect triggers an
  audit, an amendment, and a re-review cycle. Design-time resolution is one
  conversation.

### Formal models before code

Some defects are not fixable by writing another test. Each repo's
`docs/WORKFLOW.md` names its **formal classes** — typically stateful
protocols, concurrency and lock disciplines, and trust models — and a change
in a formal class is model-checked before the implementation mission
dispatches (the `formalClass(m) ⇒ modelChecked(m)` doorway in §6). One
trigger is org-wide: the moment the same class of defect surfaces across two
or more fix/review rounds, stop opening empirical rounds — formalize the
state machine and model-check it.

### Other operator gates

- **The demo** — the operator confirms observed behavior for user-facing
  changes before the PR opens (§5). A demo, never a diff review (§3).
- **Destructive operations** (`git reset --hard`, force pushes, deletions,
  migrations) require operator consent before execution.
- **Release approval** — the PyPI deployment gate; owned by
  [Release Process](release-process.md).

---

## 8. Invariants

1. **Beads are the single funnel.** Every piece of work above T4 is a bead
   before it is anything else; external queues (issues, alerts) drain into
   it at intake.
2. **A satisfied merge gate means merge now.** The gate is the only path to
   a merge, and nothing waits once it passes.
3. **Findings never wait.** Review feedback is handled the moment it
   arrives, not on the next poll tick and never in a follow-up PR.
4. **Every push restarts the merge gate.** Fresh CI and fresh reviews on the
   new commit, with the single Bugbot exception stated in the gate.
5. **Defects flow inward, scope flows outward.** A defect found while a PR
   is open is fixed in that PR. Only genuinely new lines of work become
   beads.
6. **The operator gates designs, demos, and direction — never diffs or
   sequencing.**
7. **Close-out is inside the loop.** The recap email, branch hygiene, and
   starting the next unit are steps of the loop, not afterthoughts.

---

## 9. Cross-Project Integration

Integrations must be optional (the project works fully without the
dependency), graceful (falls back silently when absent), and one-way (A uses
B; B does not know about A).

When a change affects a package consumed by other projects:

1. Producer runs `make build` and notifies the consumer via biff
2. Consumer installs from the built wheel and runs `make check`
3. Both proceed with independent PRs

Cross-repo breaking changes additionally require explicit agreement from the
consuming repo's owner before either side merges.

---

## Related Standards

- [PR and Review](pr-review.md) — PR boundaries, review sequencing, installed semantics
- [Agent Engineering](agent-engineering.md) — judgment defaults for AI coding agents
- [Makefile](makefile.md) — quality-gate composition
- [GitHub](github.md) — branch protection, CI, Copilot configuration
- [Release Process](release-process.md) — the release playbook
- [Archetypes and Pipelines Guide](https://github.com/punt-labs/ethos/blob/main/docs/archetypes-and-pipelines.md) — the mission harness reference
