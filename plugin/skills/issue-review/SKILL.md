---
name: issue-review
description: Audit every open Linear issue of a repo — clarity, validity, priority — closing invalid ones and rewriting the rest, grouped by theme for batch work.
disable-model-invocation: true
user-invocable: false
---

# issue-review — Full Backlog Audit

Review 100% of a repo's open Linear issues, one at a time, in this same
session, against the per-issue rubric in `references/per-issue-rubric.md`.
This is a backlog *cleanup* pass, not implementation work — nothing gets
fixed in code here, only the issues describing the work get made accurate,
clear, and correctly prioritized (or canceled if the work they describe is
no longer real).

**No per-issue confirmation.** The rubric makes the call on each issue
autonomously. This skill's job is to enumerate, apply the rubric,
reconcile, and produce one final report — not to relay N individual
questions to the user.

## Usage

`args` (optional): a repo directory to scope to (defaults to the current
working directory). All Punt Labs work lives on one Linear team (Punt
Labs, key `PL`); a repo's issues are the ones carrying its `repo:<name>`
label. To audit multiple repos, invoke this skill once per repo; it does
not fan out across repos on its own.

```text
Skill(issue-review)                      # audits the current repo
Skill(issue-review, args="../vox")       # audits a sibling repo
```

Set `REPO` once at the start of the run: `args` if given, otherwise the
current directory. **Never `cd`** — pass `REPO` to `git -C` where a git
command is needed.

## Step 1: Confirm scope

Read the repo's label from `$REPO/.punt-labs/punt/CLAUDE.md` or, failing
that, from `list_issue_labels` for team `PL` (the label is `repo:<name>`;
for some repos the label and the checkout name differ, and Linear is keyed
on the label). If you cannot determine the label, stop and say so — never
list issues without a repo label, which reads the whole team.

State the repo and label you are about to audit in one line before
starting — an announcement, not a question, so the run is legible if
watched.

## Step 2: Enumerate every open issue

"Open" means any status that is not Done or Canceled — Backlog, Todo, In
Progress, and blocked issues all need review:

```text
list_issues(team="PL", label="repo:<name>", includeArchived=false)
```

Drop issues whose status type is completed or canceled. Page with the
returned cursor until `hasNextPage` is false — the first page is not the
backlog. Sort oldest first by creation date: age is a priority signal per
the rubric, and reviewing oldest-first surfaces stale or mis-prioritized
issues early, before review fatigue sets in.

Record the total count. This is the number you are accountable for at the
end — every issue gets a disposition line in the final report, not a
sample.

## Step 3: Scan for duplicates once, up front

Linear has no whole-backlog duplicate finder. Compare titles and
descriptions from Step 2's enumeration (already in hand) and pair up
issues that describe the same work.

For each pair, decide **now, once, in this outer step** which member to
cancel — never let each pair-mate's rubric pass decide independently, or
two independent reviews can cancel both or neither. Use status and
creation date from Step 2:

- If exactly one member is In Progress, it is **always** the survivor
  regardless of age — someone is working it, and canceling active work out
  from under an assignee is worse than leaving a duplicate open for a
  human to reconcile.
- Otherwise the older issue is the survivor and the newer one is canceled.
- If ages are equal or the choice is still ambiguous, keep the one with
  the more complete, more specific title or description.

Keep the pair map in context and pass it into Step 4, so the designated
cancel-side of each pair is reviewed with `duplicate-of: <survivor
identifier>` context. The survivor is reviewed normally, with no duplicate
flag.

## Step 4: Review each issue — apply the rubric

Read the rubric once. It lives at
`${CLAUDE_PLUGIN_ROOT}/skills/issue-review/references/per-issue-rubric.md`
— an ABSOLUTE plugin path, not relative to `$REPO`. Never `Read
references/per-issue-rubric.md` as a bare relative path: the Read tool
resolves that against the audited repo's cwd (a marketplace install has
the plugin under `~/.claude/plugins/cache/...`, nowhere near the audited
repo), so a bare relative read misses the rubric and Step 4 silently
continues without it. The absolute plugin path resolves the same way on
every install because `${CLAUDE_PLUGIN_ROOT}` is set by the command runner
before this skill loads.

The rubric defines the six-step per-issue review (Read, Assess clarity,
Assess validity, Assess priority, Act, Theme label). For each issue from
Step 2, in order:

1. Apply the rubric end-to-end in this same session.
2. If Step 3 designated this issue as the cancel-side of a duplicate pair,
   the rubric's Step 1 handles the duplicate path using the survivor's
   identifier.
3. Collect a one-line disposition (per the rubric's Step 7 report line
   shape) into an in-context list you will use for Step 6.

Do not stop between issues to ask whether to proceed, whether a
disposition was correct, or whether to continue — that defeats the purpose
of an autonomous full-backlog pass. The only case the rubric surfaces
mid-run is `needs-human-review`, and that is a label + an issue comment +
a line in the final report, not a blocking question.

**Sequential, one issue at a time, in this same session.** No fanning to
fork agents, no splitting across sessions: results drift and state is lost
across the split boundary (duplicate pairs and partial counts have been
observed). If a backlog is too large for one sitting, that is a decision
for the human running this skill.

## Step 5: Group by theme

Once every surviving issue has a `theme:*` label (from the rubric's Step
6), pull the grouping with the same open-status filter as Step 2 —
canceled issues, including the ones this run just canceled, must not
appear in a *future work* batching plan:

```text
list_issues(team="PL", label="repo:<name>")
```

Group by `theme:` label; within each theme, sort by priority. This is the
artifact that makes the audit useful beyond "the backlog is now tidy" —
it is a batching plan: which groups of issues touch the same code and
could reasonably be worked together in one pass.

## Step 6: Final report

**Reconcile before printing.** Count the disposition lines collected in
Step 4 and compare that count to the total recorded in Step 2. If they
don't match, stop and report the discrepancy instead of printing a report
that looks complete but silently under-covers the backlog.

Print one report, not N questions. Every issue reviewed in Step 4 appears
in exactly one of the first four tables — including issues confirmed good
with no changes, which get their own (typically short) table:

```markdown
# Issue Review: <repo> (repo:<name>)

**Reviewed:** <total> open issues
**Canceled (invalid):** <count>
**Rewritten:** <count>
**Confirmed good (no change):** <count>
**Needs human review:** <count>

## Canceled

| Issue | Title (as it was) | Reason |
|-------|-------------------|--------|
| ... | ... | ... |

## Rewritten

| Issue | New title | Priority | Theme |
|-------|-----------|----------|-------|
| ... | ... | ... | ... |

## Confirmed good

| Issue | Title | Priority | Theme |
|-------|-------|----------|-------|
| ... | ... | ... | ... |

## Needs human review

| Issue | Title | Why uncertain |
|-------|-------|----------------|
| ... | ... | ... |

## Batching plan — by theme

### theme:<area> (<count> issues, oldest P<n>)

- <identifier> — <title> (P<n>)
- <identifier> — <title> (P<n>)

### theme:<area> (<count> issues, oldest P<n>)

...
```

The batching plan includes every surviving issue (Rewritten + Confirmed
good + Needs human review) — canceled issues are gone from future work by
definition and don't appear there.

This report is the deliverable. Nothing further happens automatically —
batching the actual fix work into missions and PRs is a separate, later
step the human decides on after reading this.
