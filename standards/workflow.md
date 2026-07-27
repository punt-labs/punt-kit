# Workflow Standards

**Updated:** 2026-07-26

How Punt Labs teams track work, delegate it, develop code, and ship it. The
unit of delegation is the **ethos mission** — a typed contract that replaces
prose instructions with declared roles, file boundaries, success criteria,
and bounded review rounds.

---

## 1. Scope and Ownership

This standard owns the work lifecycle: issue tracking, workflow tiers,
mission-based delegation, human-in-the-loop gates, branch and commit
discipline, quality gates, and session protocol. Adjacent concerns are owned
by neighboring documents — cross-reference them, do not restate them:

| Concern | Owning standard |
|---------|-----------------|
| PR boundaries, local and remote review sequencing, what "installed" means | [PR and Review](pr-review.md) |
| Judgment defaults: reversibility, test proportionality, confidence calibration | [Agent Engineering](agent-engineering.md) |
| `make check` targets and gate composition | [Makefile](makefile.md) |
| Branch protection, CI, Copilot configuration | [GitHub](github.md) |
| Release phases and cross-repo propagation | [Release Process](release-process.md) |
| Mission contract schema, archetypes, pipeline templates, mission CLI | ethos documentation (see §4) |

Terms used throughout:

- **Operator** — the human accountable for the repo.
- **Leader** — the session (human or agent, e.g. `claude`) that owns the
  branch, dispatches missions, and merges.
- **Worker** — the specialist a mission delegates work to (e.g. `rmh`).
- **Evaluator** — the reviewer named in the mission contract, distinct from
  both leader and worker.

---

## 2. Issue Tracking

All projects use **beads** (`bd`) for issue tracking. Beads are the durable,
cross-session source of truth for what work exists and what state it is in.

### Setup

Every repo must have beads initialized (`bd init`). The `.beads/` directory
is committed to git.

### Workflow

- `bd create "title"` to create issues with `--type` (task, bug, feature,
  spike) and `--priority` (1-5)
- `bd ready` to find available work
- `bd update <id> --status in_progress` before starting
- `bd close <id>` when complete
- Work is not complete until `git push` succeeds

### Issue quality

Issues must have:

- A clear title in imperative form
- A description with enough context for another engineer (or agent) to act on
- Correct type and priority
- Dependencies declared (`--blocks`, `--blocked-by`) when applicable

### Beads vs session task lists

Beads are the record; in-session task lists are the display. Use the session
task list (e.g. `TaskCreate`) only to make the current batch visible to the
operator — one entry per claimed bead, marked complete as each bead closes.
Work that spans sessions must be a bead, never only a session task.

### Batch hygiene: validate first

Bug reports age. Before dispatching fixes for a batch of old bug beads,
validate that each still reproduces at current HEAD. Close the ones that no
longer reproduce, with a note stating what was checked. Dispatch missions
only for confirmed defects. Fixing a bug that no longer exists wastes a full
mission round; validation costs minutes.

---

## 3. Workflow Tiers

Match the workflow to the scope. The deciding factor is **design ambiguity**,
not size. Each tier maps to an ethos pipeline template (§4); the pipeline
determines which mission stages the work passes through.

| Tier | Scope | Pipeline | Tracking |
|------|-------|----------|----------|
| **T1** | Epics, cross-cutting work, competing design approaches | `full` | Beads with dependencies |
| **T2** | Features: multi-file, clear goal, needs exploration | `standard` | Beads + missions |
| **T3** | Tasks and bugs with an obvious implementation path, worth tracking | `quick` | Beads + one mission |
| **T4** | Trivial: typo, single-line fix, mechanical refactor with no design choice | none — direct change | No bead; the commit is the record |

### Nature overrides size

When the work has a recognizable nature, use the matching pipeline instead of
the size-based default: `docs` for documentation-only changes, `product` for
new user-facing features (PR/FAQ first), `formal` for stateful systems and
protocols (spec first), `coe` for cause-of-error investigations, `coverage`
for targeted test-coverage work. `ethos mission lint` suggests a pipeline
from the contract's context and write set; the suggestion is advisory and
the leader decides.

### Escalation

Escalation only goes up. If T3 work reveals unexpected scope, escalate to T2.
Never demote mid-flight. Default to T4 when in doubt — the cost of
under-tiering is one escalation; the cost of over-tiering is ceremony on
every trivial change.

### Where bare `Agent()` fits

Review-cycle fix rounds — addressing findings from local review agents or
remote reviewers (Copilot, Bugbot) — may use a bare `Agent()` spawn without
a mission contract. The finding is the spec and the write set is obvious, so
a contract adds nothing. Every other delegated code change goes through a
mission (§4). Bare spawns are still audit-tagged by ethos (Tier A audited
delegation), but carry no write-set enforcement or evaluator.

---

## 4. Missions: Typed Delegation

Prose delegation fails in two known ways: the worker drifts (touches files
outside the intent, revises its own success criteria mid-round), and the
decision context evaporates (nobody can later answer why approach A beat
approach B). A **mission contract** fixes both. It is a typed YAML document
that declares, before any work starts:

- **leader**, **worker**, and **evaluator** — the evaluator's definition is
  content-hash-pinned at creation so review criteria cannot drift mid-mission
- **write set** — the files the worker may modify; the store refuses
  overlapping write sets between open missions and rejects self-review
  (evaluator same as worker or leader)
- **success criteria** — testable statements, verified before close
- **budget** — a bounded number of rounds, with a reflection recorded
  between rounds
- **results and reflections** — append-only artifacts that survive the session

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
is delegated to a worker at tiers T1–T3 — that is, any delegated change that
touches multiple files, alters user-facing behavior or a public contract, or
amends a standard consumed by other repos.

A mission is **not required** for:

- T4 changes — no bead, no mission; the commit is the record
- Review-cycle fix rounds — bare `Agent()` per §3

A leader **may** still wrap either case in a mission when the audit surface
is worth the ceremony (e.g. a T4 change to release mechanics).

### Per-repo instantiation

Each repo's `CLAUDE.md` must carry a worker/evaluator table mapping the
repo's task types to identity handles — this is the local instantiation of
the mission harness. Example rows from punt-kit:

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| Standards doc authoring (`standards/*.md`) | `mdm` | `rop` |
| Python implementation (`punt` CLI) | `rmh` | `gvr` |

Within each row the worker and evaluator must be distinct handles, and the
leader is never the evaluator. Ethos enforces this at contract creation; the
table makes the assignment predictable before a contract exists.

### Dispatch is two operations

`ethos mission create` (or `dispatch`) only writes the contract. The worker
is spawned by a separate `Agent(subagent_type=<worker>, run_in_background=true)`
call. After every dispatch, verify the worker is actually running before
considering the mission active. Forgetting the spawn leaves the contract
orphaned — nothing happens, and nobody notices until the round budget is
audited.

### Required contract clauses

Every implementation mission must include commit-per-step in its success
criteria. Workers that accumulate uncommitted changes across many files are
a session-timeout liability — if the worker terminates mid-edit, the leader
must either commit by proxy or lose the work. Required criterion text:

> Commit incrementally — one commit per logical step (file group, single
> concern, or single PR-equivalent slice). Each commit must pass
> `make check`. Do not accumulate more than 30 minutes of uncommitted
> changes.

### Push and merge stay with the leader

Workers commit their own work, on their own timeline, inside their write
set. Workers never push, never open PRs, and never merge — the leader owns
pushing and the PR lifecycle (see §9). A worker that finishes its write set
reports a result; it does not ship.

### Monitoring a running mission

Judge worker progress by the filesystem, never by commits. A worker editing
files is working, even with zero commits — the absence of a commit is not a
stall and never a reason to intervene, commit by proxy, or kill the agent.
Only a genuine filesystem stall (no edits changing over a long window) with
an unresponsive worker justifies a status message and, as a last resort,
taking over.

### Fix rounds route to the domain specialist

Review findings are fixed by the same specialist who would implement the
area — a Python finding goes to the Python worker, not a generic agent. The
finding itself is the spec; the leader reviews it before delegating, which
collapses (not skips) the design step. The documentation standard for
dismissing a finding is owned by [PR and Review](pr-review.md).

---

## 5. Human-in-the-Loop Gates

Missions bound what agents may do. These gates are where the human decides.
The operator's rulings are not advisory — work does not proceed past a gate
until the ruling exists.

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

### Other operator gates

- **Human IDE review** of the full diff before a PR opens — the only human
  code review in the process; owned by [PR and Review](pr-review.md).
- **Destructive operations** (`git reset --hard`, force pushes, deletions,
  migrations) require operator consent before execution.
- **Release approval** — the PyPI deployment gate; owned by
  [Release Process](release-process.md).

---

## 6. Branch Discipline

All code changes go on feature branches. Never commit directly to main.
Branch protection rulesets enforce this — there are zero bypass actors.

```bash
git checkout -b feat/short-description main
```

### Branch prefixes

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code improvements |
| `docs/` | Documentation only |
| `release/` | Release version bumps |
| `chore/` | Maintenance and housekeeping |

### Commits

Micro-commits: one logical change per commit, 1–5 files, quality gates pass
before every commit. Commit messages follow Conventional Commits format:
`type(scope): description`.

### Coordination

Set a biff plan (`/plan "short description"`) before starting work so
teammates can see what you are doing. If `/who` shows another human or agent
active in the same repo, work in a worktree (`git worktree add` or the
`--worktree` session flag) to avoid file conflicts — mission workers should
run in isolated worktrees by default.

---

## 7. Quality Gates

`make check` is the quality-gate entry point and must pass before every
commit — not before the PR, before each commit. A commit that fails
`make check` is a broken commit. The [Makefile standard](makefile.md) owns
what `check` composes per project type.

Zero violations, zero errors, all tests green. When gates fail, fix the
issue — do not commit with known failures, and do not skip gates with
`--no-verify` or equivalent.

Suppressions (`# noqa`, `# type: ignore`, `xfail`, lint disables) are not an
authorized way to make gates pass. A suppression is permitted only when a
standard explicitly pre-authorizes its class, or the operator approves the
specific instance. The volume of errors does not change this rule — every
error is fixed or escalated, never suppressed autonomously.

---

## 8. Development Loop

Every feature follows two nested loops. The inner loop governs a single
mission; the outer loop governs the feature before it becomes a PR. The
verification and review steps inside both loops are specified in
[PR and Review](pr-review.md) — this section owns the loop structure and
the design obligations.

```text
outer loop (per feature):
  branch, open draft PR                     # CI runs on every push
  for each pipeline stage:
    inner loop (per mission):
      design mission → leader review → operator ratification   (§5)
      implementation mission                                    (§4)
      verify + local review    (pr-review.md "After each coding mission")
      worker commits; leader pushes
  full-diff local review, human IDE review,
  end-to-end exercise          (pr-review.md "Before opening a PR")
  mark PR ready → remote review → merge     (pr-review.md "Remote review")
```

### Design obligations

Before any code is written for a mission, the approach is decided by a
design stage delegated to the right specialist. The design brief must
answer:

1. What this mission changes
2. How it leaves the system better — structural improvement, not just
   feature delivery: coupling, cohesion, naming, module boundaries
3. What approach was chosen and why

If the design reveals a non-obvious decision with rejected alternatives
worth recording, write a `DESIGN.md` ADR entry (§13). The commit message is
sufficient for most changes.

If a worker hits a decision point mid-implementation, it stops and surfaces
the decision. Implementation does not resume until the design question is
answered — by the leader, or by the operator when the gate in §5 applies.

### Tests

Write the failing test first, then the code that makes it pass. Tests and
code land in the same commit. If writing the test first is impractical,
write the code first and the test immediately after — the same-commit rule
still holds. Proportionality (what deserves how much testing) is owned by
[Agent Engineering](agent-engineering.md) §10.

---

## 9. Review and Merge

PR boundaries, the local review sequence, human IDE review, and remote
review (Copilot, Bugbot) are owned end-to-end by
[PR and Review](pr-review.md). Summary of the division: all human review
happens locally before the PR opens; the PR is a merge gate, not a review
mechanism; remote review is an automated second opinion.

One workflow-level rule: related small fixes discovered in one validation or
review pass **should** ship as a single cohesive round-up PR — one rollback
unit — rather than one PR per fix. This is the same rollback-granularity
criterion pr-review.md uses to prohibit micro-PRs, applied to housekeeping
batches.

---

## 10. CHANGELOG Discipline

Projects that maintain a CHANGELOG follow
[Keep a Changelog](https://keepachangelog.com/) format, with bracketed
version headings (`## [Unreleased]`, `## [X.Y.Z] - YYYY-MM-DD`) — release
tooling parses the brackets.

- Entries are written **in the PR branch, before merge** — not
  retroactively on main. The entry is part of the reviewed diff.
- Entries go under `## [Unreleased]`, grouped as Added, Changed, Fixed,
  Removed (omit empty groups).
- Internal-only changes (CI config, dev tooling, test-only) do not get
  entries.

---

## 11. Session Close

Before ending any session:

```bash
git status              # Check for uncommitted work
git add <files>         # Stage changes
git commit -m "..."     # Commit
bd sync                 # Sync beads with git
git push                # Push to remote
```

Work is **not** complete until `git push` succeeds. (Mission workers stop at
the commit — the push belongs to the leader, per §4.)

---

## 12. Work Recap

After merging a PR, send a recap email to <jim@punt-labs.com> via beadle.

- **Subject**: `[repo-name] PR #N merged: <title>`
- **Required**: bead ID, PR link, 1-paragraph summary of what changed, why,
  and how it left the system better
- **Include when relevant**: design decisions made, test coverage notes,
  follow-up work created

---

## 13. Design Decision Logs

Use `DESIGN.md` at the repo root. Write an ADR entry when a decision is
non-obvious, has rejected alternatives worth recording, or would confuse a
future reader. Consult the log before proposing changes to settled
architecture. Do not revisit a settled decision without new evidence. See
[Design Decision Log](../patterns/design-decision-log.md) for the full
pattern.

---

## 14. Cross-Project Integration

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
