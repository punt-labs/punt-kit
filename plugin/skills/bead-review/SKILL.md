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
scoped per repo via `.beads/metadata.json`'s prefix — running this from
inside a repo, or passing that repo's path, is what determines scope. To
audit multiple repos, invoke this skill once per repo; it does not fan
out across repos on its own.

```text
Skill(bead-review)                      # audits the current repo
Skill(bead-review, args="../vox")       # audits a sibling repo
```

## Step 1: Confirm scope

```bash
cd <target-repo>   # only if args gave a different repo
cat .beads/metadata.json   # confirm the prefix, sanity-check this is the right db
```

State the repo and prefix you're about to audit in one line before
starting — this is not a confirmation question, just an announcement, so
the run is legible if it's being watched.

## Step 2: Enumerate every open bead

"Open" means any non-closed status, not just `bd ready`'s narrower
no-blockers view — blocked and deferred beads still need clarity/validity
review even if they can't be worked yet:

```bash
bd list --status open,in_progress,blocked,deferred --all -n 0 --no-pager --sort created --json
```

Sort by `created` (oldest first) — age is a priority signal per
`bead-review-item`, and reviewing oldest-first surfaces the beads most
likely to be stale or under/over-prioritized early, rather than at the
end when review fatigue is highest.

Record the total count. This is the number you're accountable for at the
end — every single one gets a disposition line in the final report, not a
sample.

## Step 3: Review each bead

For each bead ID from Step 2, in order:

```text
Skill(bead-review-item, args="<id>")
```

Collect that skill's one-line report output. Do not stop between beads to
ask whether to proceed, whether a disposition was correct, or whether to
continue — that defeats the purpose of an autonomous full-backlog pass.
The only case `bead-review-item` surfaces mid-run is `needs-human-review`,
and that's a label + a line in the final report, not a blocking question.

**Batch size for large backlogs:** if the repo has more than ~30 open
beads, this can be slow run one at a time in the main loop. In that case,
fan out `bead-review-item` across fork agents in batches (e.g. 5-10
concurrent), collecting each fork's one-line report the same way. Do not
parallelize by skipping the per-bead rubric — every bead still gets the
full read/assess/verify/act sequence, just concurrently rather than
strictly sequentially.

## Step 4: Group by theme

Once every bead has a `theme:*` label (from `bead-review-item` Step 6),
pull the grouping:

```bash
bd list --label-pattern "theme:*" --all -n 0 --no-pager --sort priority --json
```

Group the surviving (non-closed) beads by their `theme:` label. Within
each theme, sort by priority. This is the artifact that makes the audit
useful beyond "the backlog is now tidy" — it's a batching plan: which
groups of beads touch the same code and could reasonably be worked
together in one pass.

## Step 5: Final report

Print one report, not N questions. Structure:

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

Every bead reviewed appears in exactly one of the first three tables
(Closed / Rewritten / Needs human review) — beads that were confirmed
good with no changes don't need their own row, but the summary count at
the top must still include them, and they still appear in the batching
plan since they're still open and still need eventual work.

This report is the deliverable. Nothing further happens automatically —
batching the actual fix work into missions/PRs is a separate, later step
the human decides on after reading this.
