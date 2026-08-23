---
name: bead-review
description: Audit every open bead in a repo — clarity, validity, priority — closing invalid ones and rewriting the rest, grouped by theme for batch work
---

# bead-review — Full Backlog Audit

Review 100% of a repo's open beads, one at a time, in this same session,
against the per-bead rubric in `references/per-bead-rubric.md`. This is a
backlog *cleanup* pass, not implementation work — nothing gets fixed in
code here, only the beads describing the work get made accurate, clear,
and correctly prioritized (or closed if the work they describe is no
longer real).

**No per-bead confirmation.** The rubric makes the call on each bead
autonomously. This skill's job is to enumerate, apply the rubric,
reconcile, and produce one final report — not to relay N individual
questions to the user.

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

Sort by `created` (oldest first) — age is a priority signal per the
rubric, and reviewing oldest-first surfaces the beads most likely to be
stale or under/over-prioritized early, rather than at the end when
review fatigue is highest.

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

For each reported pair, decide **now, once, in this outer step** which
member is the one to close — never let each pair-mate's rubric pass
decide independently, or two independent reviews can close both (each
thinking it's the duplicate) or neither, regardless of review order. Use
status and `created_at` from Step 2's enumeration (already in hand, no
extra `bd` calls needed), status first:

- If exactly one member is `in_progress`, it is **always** the survivor
  regardless of age — someone is actively working it, and closing active
  work out from under an assignee is worse than leaving a duplicate open
  for a human to reconcile.
- Otherwise (both/neither `in_progress`), the older bead is the survivor,
  the newer one is the duplicate to close.
- If ages are equal or the choice is still ambiguous, prefer keeping the
  one with the more complete/specific title or body as the survivor.

Keep the pair map in context, then pass it into Step 4 so the designated
close-side of each pair is reviewed with `duplicate-of: <survivor-id>`
context — the survivor is reviewed normally, with no duplicate flag at
all.

## Step 4: Review each bead — apply the rubric

Read the rubric once. It lives at
`${CLAUDE_PLUGIN_ROOT}/skills/bead-review/references/per-bead-rubric.md`
— an ABSOLUTE plugin path, not relative to `$REPO`. Never `Read
references/per-bead-rubric.md` as a bare relative path: the Read tool
resolves that against the audited repo's cwd (a marketplace install has
the plugin under `~/.claude/plugins/cache/...`, nowhere near the
audited repo), so a bare relative read misses the rubric and Step 4
silently continues without it. The absolute plugin path resolves the
same way on every install (dev, marketplace, or the
`--plugin-dir` variant) because `${CLAUDE_PLUGIN_ROOT}` is set by the
command runner before this skill loads.

The rubric defines the six-step per-bead review (Read, Assess clarity,
Assess validity, Assess priority, Act, Theme label). For each bead ID
from Step 2, in order:

1. Apply the rubric end-to-end in this same session.
2. If Step 3 designated this bead as the close-side of a duplicate pair,
   the rubric's Step 1 handles the duplicate-close path using the
   survivor's ID.
3. Collect a one-line disposition (per the rubric's Step 7 report line
   shape) into an in-context list you'll use for Step 6.

Do not stop between beads to ask whether to proceed, whether a
disposition was correct, or whether to continue — that defeats the
purpose of an autonomous full-backlog pass. The only case the rubric
surfaces mid-run is `needs-human-review`, and that's a label + a bead
comment + a line in the final report, not a blocking question.

**Sequential, one bead at a time, in this same session.** No fanning to
fork agents, no splitting across sessions. Fork fan-out is unreliable
(subagents lack access to some tools; results drift; state loss across
the split boundary has been observed with duplicate pairs and partial
counts). If a backlog is too large for one sitting, that is a decision
for the human running this skill, not something to paper over.

## Step 5: Group by theme

Once every surviving bead has a `theme:*` label (from the rubric's Step
6), pull the grouping. Use the same non-closed status filter as Step 2 —
closed beads (including the ones this run just closed) must not appear in
a *future work* batching plan:

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
that looks complete but silently under-covers the backlog.

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
