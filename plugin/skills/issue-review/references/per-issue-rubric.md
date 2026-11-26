# Per-Issue Rubric

The six-step rubric applied to each Linear issue in `issue-review`'s Step 4.
Referenced once per audit run; apply the whole rubric per issue, in order,
in the same session running the outer skill. Every write below is a Linear
write on team `PL`, scoped by the repo's `repo:<name>` label. **Writes
are proposals:** the audit collects each intended `save_issue` or
comment, shows the batch in the final report, and asks the operator before
sending any of them.

Inputs the outer loop passes for each issue:

- `ID` — the issue identifier under review (e.g. `PL-1051`).
- `LABEL` — the repo label (`repo:<name>`) the audit is scoped to.
- `known-duplicate` (optional) — a survivor identifier, set by the outer
  loop's Step 3 for issues it designated as the cancel-side of a
  duplicate pair. The survivor is NOT passed this — its rubric run is
  ordinary.

## Step 1: Read

```text
get_issue(id=ID)
list_comments(issueId=ID)
```

Capture: title, description, priority, status, labels, `createdAt`,
`updatedAt`, assignee, and any relations. `get_issue` does not include the
discussion, so read the comments too. `createdAt` is a priority signal in
its own right — an issue open for months at Medium either deserves a bump
(something has quietly starved it) or should have been closed long ago.
Don't skip reading it.

If the outer loop marked this issue as a known-duplicate cancel-side, the
survivor has already been chosen (an In Progress issue always survives
regardless of age, then creation date, then completeness). Read the
survivor too, to confirm the pairing still holds:

```text
get_issue(id="<survivor identifier>")
```

If it does, treat this as an invalidity case (Step 3) and cancel this
issue with a comment pointing at the survivor. Do not re-decide which
member of the pair should close — that decision was made once, upstream.
If the pairing looks wrong on a closer read (not actually a duplicate),
fall through to a normal Step 2/3 review instead of canceling.

## Step 2: Assess clarity

Ask, reading only the title:

- Would someone unfamiliar with this work understand *what's wrong or
  needed* without opening the body?
- Is it specific ("CI: build, run, and E2E-test the biff-relay Docker
  image") or vague ("fix tests", "improve docs", "cleanup")?

Then ask, reading the full description:

- Does it explain the problem *and* why it matters, not just a symptom?
- Could a stranger pick this up and start working without pinging anyone
  for context?
- Is it formatted for a human — markdown structure, code blocks for
  file paths/commands/snippets, not a wall of undifferentiated prose?

An issue can be perfectly valid and still fail this bar. Note the verdict
(clear / needs-rewrite) but don't act yet — validity and priority come
first, since an invalid issue doesn't need a clarity fix at all.

## Step 3: Assess validity — verify, don't guess

If the issue makes a factual claim about the code (a bug exists, a feature
is missing, a file behaves a certain way), **check it against current
`origin/main`, never the checked-out branch** — a feature branch may
carry unmerged changes that make a bug look fixed or a feature look
present. Run `git -C "${REPO:-.}" fetch origin` once per audit, then read
files with `git show origin/main:<path>` and search with `git grep` on
`origin/main` (the Grep tool searches the working tree, so use it only
when the working tree is `main` at `origin/main`). Use `git grep` (works from anywhere inside the repo, unlike a
raw `grep` restricted to guessed paths like `src/`/`tests/`, which won't
exist or won't be the right layout in every repo):

```bash
git -C "${REPO:-.}" grep -n "<the specific thing described>" origin/main
```

Read the actual file(s) involved, at `origin/main`. Run the actual command described, if
it's cheap and safe to do so (`--dry-run`, `--collect-only`, a read-only
query). Do not cancel an issue on a hunch that it's "probably fixed by
now" — either find the code that proves it's resolved, or find the code
that proves it's still broken. If you can't find either after a real
search (not a token grep for one string — read the surrounding module),
that's a genuine "uncertain" case: leave it open, note the uncertainty in
the outer loop's report, and do not cancel it. Canceling requires
positive evidence, staying open does not.

Process, infrastructure, and product-decision issues (no single file to
check) don't have a code answer — judge these on whether the described
need still exists given what's shipped since the issue was filed (check
CHANGELOG.md, recent PRs, other Done issues referencing the same area).

**Disposition:**

- **Invalid** (resolved, superseded by a later issue, or the premise was
  wrong) → go to Step 5a (cancel).
- **Valid** → continue to Step 4.
- **Genuinely uncertain after a real check** → leave open, do not rewrite
  title/priority. Add the `needs-human-review` label *and* still add a
  `theme:<area>` label (Step 6) — an uncertain issue is still real work
  that belongs in the batching plan, it just needs a human's eyes before
  anyone acts on it. Record what you checked directly on the issue, not
  only in the outer loop's transient report, so the reasoning survives
  independently of that one run:

  ```text
  save_comment(issueId=ID, body="issue-review: uncertain after checking <what you checked> — <why it's still ambiguous>")
  ```

  This is the only case where the loop should flag something back to a
  human — and it should be rare, not the default outcome.

## Step 4: Assess priority

Given what Step 3 confirmed about current severity/impact, and the issue's
age from Step 1, use Linear's priority levels:

| Priority | Meaning |
|----------|---------|
| Urgent | Critical — security, data loss, broken builds |
| High | Major features, important bugs |
| Medium | Default |
| Low | Polish, optimization |
| No priority | Future ideas — prefer Low, or Backlog status |

Re-prioritize if the current value doesn't match reality — not just "this
feels more important," but tied to a concrete reason (blocks something now
open, affects data integrity, was filed reactively as High but turned out
to be cosmetic, etc.).

## Step 5: Act

### 5a. Invalid — cancel

Comment first, then set the status:

```text
save_comment(issueId=ID, body="<what you checked, file:line if applicable, and why it's resolved/superseded/obsolete>")
save_issue(id=ID, state="Canceled")
```

The reason must cite evidence (a file, a PR, a CHANGELOG entry, another
issue identifier), never just "no longer needed." Use Done instead of
Canceled when the work was in fact completed.

### 5b. Valid, needs a rewrite

Rewrite title and/or description and/or priority in one `save_issue`
call. The description should be markdown: a short problem statement, why
it matters, and (if scope is knowable) what "done" looks like. Include
code snippets, file paths, or command output when they make the issue
self-contained instead of requiring the reader to go dig. To change part
of a long description, pass `patch` instead of resending the whole body.

```text
save_issue(id=ID, title="<clear, specific, action-oriented title>", priority=<1-4>, description="""
## Problem

<what's wrong, concretely — cite file:line or a command's actual output>

## Why it matters

<impact, one or two sentences>

## Scope

<what "done" looks like, if known>
""")
```

Any subset of `title`, `priority`, `description` is a real rewrite — a
priority-only change still counts; don't touch fields that were already
good.

### 5c. Valid, already good

No title/description/priority change. Still add the theme label (Step 6)
— this issue was genuinely reviewed, not skipped, and the outer loop's
report should reflect that (a confirmed-good issue is a result, not a
non-event).

## Step 6: Theme label

Add (don't remove existing labels) a `theme:<area>` label based on what
part of the codebase/system this touches, so the outer loop can group the
final set for batch work. Applies to every disposition except 5a
(canceled issues don't need a theme — they're leaving the backlog). Use
`addLabels`, never `labels`, which replaces the whole set and would drop
the `repo:<name>` label:

```text
save_issue(id=ID, addLabels=["theme:<area>"])
```

Pick from existing `theme:*` labels already in use where one fits before
inventing a new one — the point is batching, which only works if the same
theme is spelled the same way across issues. Run `list_issue_labels` for
team `PL` and read the `theme:*` entries.

## Step 7: Record the disposition line

Add one line, in this exact shape, to the in-context list the outer loop
uses for its Step 6 reconciliation and tables:

```text
<identifier> | <disposition: canceled|rewritten|confirmed-good|needs-human-review> | theme:<area> | <one-line reason>
```

Then continue to the next issue — do not stop, do not ask, do not emit
anything else to the user between issues.
