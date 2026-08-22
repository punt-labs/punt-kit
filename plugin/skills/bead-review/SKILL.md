---
name: bead-review
description: Audit every open bead in a repo — clarity, validity, priority — closing invalid ones and rewriting the rest, grouped by theme for batch work
disable-model-invocation: true
---

# bead-review — Full Backlog Audit (Outer Loop)

Review 100% of a repo's open beads, one at a time, using the
`bead-review-item` skill as the per-bead rubric. This is a backlog
*cleanup* pass, not implementation work — nothing gets fixed in code here,
only the beads describing the work get made accurate, clear, and
correctly prioritized (or closed if the work they describe is no longer
real).

**No per-bead confirmation.** `bead-review-item` makes the call on each
bead autonomously. This skill's job is to enumerate, delegate, and produce
one final report — not to relay 40 individual questions to the user.

## Usage

`args` (optional): a repo directory to scope to (defaults to the current
working directory). Beads are stored in a shared org-wide database but
scoped per repo via `.beads/metadata.json`'s prefix. To audit multiple
repos, invoke this skill once per repo; it does not fan out across repos
on its own.

```text
Skill(bead-review)                      # audits the current repo
Skill(bead-review, args="../vox")       # audits a sibling repo
```

Set `REPO` once at the start of the run: `args` if given, otherwise the
current directory. **Never `cd`** — every `bd` command below takes `-C
"$REPO"` instead, so the skill works regardless of what tools are
allow-listed for the invoking command.

## Step 1: Confirm scope

```bash
cat "$REPO/.beads/metadata.json"   # confirm the prefix, sanity-check this is the right db
```

State the repo and prefix you're about to audit in one line before
starting — this is not a confirmation question, just an announcement, so
the run is legible if it's being watched.

## Step 2: Enumerate every open bead

"Open" means any non-closed status, not just `bd ready`'s narrower
no-blockers view — blocked and deferred beads still need clarity/validity
review even if they can't be worked yet. Do **not** add `--all` here — that
flag means "include closed issues too," the opposite of what this step
wants; the explicit `--status` list is the complete filter on its own:

```bash
bd -C "$REPO" list --status open,in_progress,blocked,deferred -n 0 --no-pager --sort created --json
```

Sort by `created` (oldest first) — age is a priority signal per
`bead-review-item`, and reviewing oldest-first surfaces the beads most
likely to be stale or under/over-prioritized early, rather than at the
end when review fatigue is highest.

Record the total count. This is the number you're accountable for at the
end — every single one gets a disposition line in the final report, not a
sample.

## Step 3: Scan for duplicates once, up front

`bd find-duplicates` operates on the whole backlog in one call — it has no
per-bead `--id` mode, so this only runs once here, not inside the per-bead
loop. Use the same status set as Step 2 ("open" means
`open,in_progress,blocked,deferred` throughout this skill — a narrower
filter here would silently miss duplicate pairs where one member is
`in_progress`, `blocked`, or `deferred`):

```bash
bd -C "$REPO" find-duplicates --status open,in_progress,blocked,deferred --json
```

For each reported pair, decide **now, once, in the outer loop** which
member is the one to close — never let both members of a pair each decide
independently, or two independent reviews can close both (each thinking
it's the duplicate) or neither, regardless of review order. Use status
and `created_at` from Step 2's
enumeration (already in hand, no extra `bd` calls needed), status first:

- If exactly one member is `in_progress`, it is **always** the survivor
  regardless of age — someone is actively working it, and closing active
  work out from under an assignee is worse than leaving a duplicate open
  for a human to reconcile.
- Otherwise (both/neither `in_progress`), the older bead is the survivor,
  the newer one is the duplicate to close.
- If ages are equal or the choice is still ambiguous, prefer keeping the
  one with the more complete/specific title or body as the survivor.

Keep the resulting pairs in context, but only pass `duplicate-of:` to the
bead you've designated as the one to close in Step 4 — the survivor is
reviewed normally, with no duplicate flag at all, since it isn't a
duplicate-disposition case.

## Step 4: Review each bead

For each bead ID from Step 2, in order, using the same plugin namespace
that invoked this skill (`punt` from `/bead-review`, `punt-dev` from
`/bead-review-dev` — the command `allowed-tools` only permit the matching
namespaced form, so a bare `bead-review-item` may be blocked):

```text
Skill(punt:bead-review-item, args="<id> [-C <REPO>] [duplicate-of: <other-id>]")
Skill(punt-dev:bead-review-item, args="<id> [-C <REPO>] [duplicate-of: <other-id>]")
```

Pass `-C "$REPO"` in the args so the inner skill's `bd` calls target the
right database without needing its own `cd`. If Step 3 designated this
bead as the one to close in a duplicate pair, say so in the args
(`duplicate-of: <survivor-id>`) — only the designated bead gets this flag;
its surviving pair-mate is invoked with no duplicate mention at all.

Collect that skill's one-line report output. Do not stop between beads to
ask whether to proceed, whether a disposition was correct, or whether to
continue — that defeats the purpose of an autonomous full-backlog pass.
The only case `bead-review-item` surfaces mid-run is `needs-human-review`,
and that's a label + a bead comment + a line in the final report, not a
blocking question.

**Large backlogs run sequentially, not fanned out to fork agents.**
`bead-review-item` has `disable-model-invocation: true`, and that blocks
the Skill tool for forked/sub-agent callers — only the top-level session
that received this skill's own instructions can reliably invoke it.
Delegating batches to fork agents was tried against a real 46-bead
backlog and mostly failed: 7 of 8 forks got a hard tool-layer refusal
("cannot be used with Skill tool due to disable-model-invocation... do
not replicate this skill's workflow by other means"), not a permission
prompt, so there is nothing to grant your way past. The 8th fork never
issued the Skill call at all: instead of calling the tool and hitting
that refusal, it hand-replicated `bead-review-item`'s steps directly from
this document's text, producing an unreviewed, drifting copy of the
rubric rather than a real run of it — a self-directed workaround, not a
response to the refusal. Do not rely on forking working, and do not
accept a result that arrived this way instead of through a real call —
see "Discard second-hand results" below.

Review every bead in this same top-level session, one at a time, in
order, for however many beads that takes, regardless of backlog size.
This is slower than the concurrent fan-out this section originally
described, but it is the only reliable path that actually executes
`bead-review-item` as designed. **There is no supported way to split a
single audit run across multiple sessions or agents** — every attempt at
that (fork fan-out; a since-removed multi-session split) turned out to
lose or duplicate state across the split boundary (a discovered duplicate
pair, a partial count, a bead silently dropped from one slice's
enumeration) with no reliable way to detect the loss after the fact. If a
backlog is too large for one sitting, that is a decision for the human
running this skill, not something this skill should paper over with an
unverified splitting procedure.

**Discard second-hand results.** A disposition line is only good if this
session itself made the `Skill(punt:bead-review-item, ...)` (or
`punt-dev:`) call that produced it — matching Step 7's shape is not
sufficient evidence, since a hand-replicated fabrication (as the 8th fork
produced) reproduces that shape too. Before accepting a line into the
final report, confirm the bead's actual state in `bd` matches the claimed
disposition — a `closed` line has a real `bd close --reason` on the bead,
a `confirmed-good`/`rewritten` line has the `theme:*` label Step 6 of
`bead-review-item` adds. If a line's claimed disposition doesn't match
what `bd show` actually returns for that bead, discard it and redo the
bead yourself, in this session, via the real call.

## Step 5: Group by theme

Once every surviving bead has a `theme:*` label (from `bead-review-item`
Step 6), pull the grouping. Use the same non-closed status filter as
Step 2 — closed beads (including the ones this run just closed) must not
appear in a *future work* batching plan:

```bash
bd -C "$REPO" list --status open,in_progress,blocked,deferred --label-pattern "theme:*" -n 0 --no-pager --sort priority --json
```

Group by `theme:` label; within each theme, sort by priority. This is the
artifact that makes the audit useful beyond "the backlog is now tidy" —
it's a batching plan: which groups of beads touch the same code and could
reasonably be worked together in one pass.

## Step 6: Final report

**Reconcile before printing.** Count the disposition lines collected in
Step 4 and compare that count to the total recorded in Step 2. If they
don't match, stop and report the discrepancy instead of printing a report
that looks complete but silently under-covers the backlog — this is the
check that would have caught the incident that prompted the "discard
second-hand results" rule above, had it slipped past that rule too.

Print one report, not N questions. Every bead reviewed in Step 4 appears
in exactly one of the first four tables — including beads that were
confirmed good with no changes, which get their own (typically short)
table rather than being silently omitted:

```markdown
# Bead Review: <repo> (<prefix>)

**Reviewed:** <total> open beads
**Closed (invalid):** <count>
**Rewritten:** <count>
**Confirmed good (no change):** <count>
**Needs human review:** <count>

## Closed

| ID | Title (as it was) | Reason |
|----|--------------------|--------|
| ... | ... | ... |

## Rewritten

| ID | New title | Priority | Theme |
|----|-----------|----------|-------|
| ... | ... | ... | ... |

## Confirmed good

| ID | Title | Priority | Theme |
|----|-------|----------|-------|
| ... | ... | ... | ... |

## Needs human review

| ID | Title | Why uncertain |
|----|-------|----------------|
| ... | ... | ... |

## Batching plan — by theme

### theme:<area> (<count> beads, oldest P<n>)

- <id> — <title> (P<n>)
- <id> — <title> (P<n>)

### theme:<area> (<count> beads, oldest P<n>)

...
```

The batching plan includes every surviving bead (Rewritten + Confirmed
good + Needs human review) — Closed beads are gone from future work by
definition and don't appear there.

This report is the deliverable. Nothing further happens automatically —
batching the actual fix work into missions/PRs is a separate, later step
the human decides on after reading this.
