---
name: bead-review-item
description: Review, rewrite, or close a single bead against clarity/validity/priority criteria — the inner loop of bead-review
disable-model-invocation: true
---

# bead-review-item — Single-Bead Audit

Given one bead ID, decide whether it is well-written, still valid, and
correctly prioritized — then act on that decision immediately. This skill
never asks the user for confirmation per bead; it makes the call, documents
why, and moves on. It is normally invoked by `bead-review` (the outer loop),
once per bead, but works standalone.

## Usage

`args` is a bead ID, optionally followed by `-C <repo-dir>` (pass every
`bd` call in this repo instead of the caller's cwd — needed when a caller
isn't already scoped there) and/or `duplicate-of: <other-id>` (set by the
outer loop when its one-time backlog-wide `bd find-duplicates` scan
already flagged this bead — specifically *this* bead, not its pair-mate —
as the one to close in favor of `<other-id>`). The outer loop only ever
attaches `duplicate-of:` to one member of a pair; its survivor is invoked
with no duplicate mention at all.

Use the plugin-namespaced skill ID that matches how you're running — the
`allowed-tools` permission list only covers the namespaced form, so a bare
`bead-review-item` may be blocked or fail to resolve:

```text
Skill(punt:bead-review-item, args="biff-kmv")
Skill(punt:bead-review-item, args="biff-kmv -C ../vox duplicate-of: biff-9zq")
Skill(punt-dev:bead-review-item, args="biff-kmv")   # from the [DEV] command
```

Parse `args` into `ID`, `REPO` (the `-C` value if one was given, else
`.`), and an optional known-duplicate ID. **Never `cd`** — every `bd` call
below is qualified with `-C "${REPO:-.}"` unconditionally, so a repo path
containing spaces still quotes correctly (a conditional
`$([ -n "$REPO" ] && echo -C "$REPO")` word-splits on expansion and loses
the quoting, so don't build the flag that way).

## Step 1: Read

```bash
bd -C "${REPO:-.}" show "$ID" --json
```

Capture: title, description, priority, status, labels, `created_at`,
`updated_at`, assignee, and any linked dependencies. `created_at` is a
priority signal in its own right — a bead open for months at P2 either
deserves a bump (something's been quietly starving it) or is a sign it
should have been closed long ago. Don't skip reading it.

If the caller passed a `duplicate-of:` ID, the outer loop has already
compared this bead against its pair-mate (using status — an `in_progress`
bead always survives regardless of age — then `created_at`, then
completeness) and determined **this** bead — not the other one — is the
one to close. Read the other bead too, to confirm the pairing still holds
(`bd -C "${REPO:-.}" show "<other-id>" --json`):
if it does, treat this as an invalidity case (Step 3) and close this bead
with a reason pointing at the surviving bead. Do not re-decide which
member of the pair should close — that decision was made once, upstream,
specifically so that two independent reviews of the same pair (which can
run concurrently under fork fan-out) never both decide to close, or both
decide to survive. If the pairing looks wrong on a closer read (not
actually a duplicate), fall through to a normal Step 2/3 review instead of
closing.

## Step 2: Assess clarity

Ask, reading only the title:

- Would someone unfamiliar with this work understand *what's wrong or
  needed* without opening the body?
- Is it specific ("CI: build, run, and E2E-test the biff-relay Docker
  image") or vague ("fix tests", "improve docs", "cleanup")?

Then ask, reading the full body:

- Does it explain the problem *and* why it matters, not just a symptom?
- Could a stranger pick this up and start working without pinging anyone
  for context?
- Is it formatted for a human — markdown structure, code blocks for
  file paths/commands/snippets, not a wall of undifferentiated prose?

A bead can be perfectly valid and still fail this bar. Note the verdict
(clear / needs-rewrite) but don't act yet — validity and priority come
first, since a bead that turns out to be invalid doesn't need a clarity
fix at all.

## Step 3: Assess validity — verify, don't guess

If the bead makes a factual claim about the code (a bug exists, a feature
is missing, a file behaves a certain way), **check it directly** — use the
Grep tool, or `git grep` (works from anywhere inside the repo, unlike a
raw `grep` restricted to guessed paths like `src/`/`tests/`, which won't
exist or won't be the right layout in every repo):

```bash
git -C "${REPO:-.}" grep -n "<the specific thing described>"
```

Read the actual file(s) involved. Run the actual command described, if it's
cheap and safe to do so (`--dry-run`, `--collect-only`, a read-only query).
Do not close a bead on a hunch that it's "probably fixed by now" — either
find the code that proves it's resolved, or find the code that proves it's
still broken. If you can't find either after a real search (not a token
grep for one string — read the surrounding module), that's a genuine
"uncertain" case: leave it open, note the uncertainty in the outer loop's
report, and do not close it. Closing requires positive evidence, staying
open does not.

Process/infra/product-decision beads (no single file to check) don't have
a code answer — judge these on whether the described need still exists
given what's shipped since the bead was filed (check CHANGELOG.md,
recent PRs, other closed beads referencing the same area).

**Disposition:**

- **Invalid** (resolved, superseded by a later bead, or the premise was
  wrong) → go to Step 5a (close).
- **Valid** → continue to Step 4.
- **Genuinely uncertain after a real check** → leave open, do not rewrite
  title/priority. Add the `needs-human-review` label *and* still add a
  `theme:<area>` label (Step 6) — an uncertain bead is still real work
  that belongs in the batching plan, it just needs a human's eyes before
  anyone acts on it. Record what you checked directly on the bead, not
  only in the outer loop's transient report output, so the reasoning
  survives independently of that one run:

  ```bash
  bd -C "${REPO:-.}" comment "$ID" \
    "bead-review: uncertain after checking <what you checked> — <why it's still ambiguous>"
  ```

  This is the only case where the loop should flag something back to a
  human — and it should be rare, not the default outcome.

## Step 4: Assess priority

Given what Step 3 confirmed about current severity/impact, and the bead's
age from Step 1:

| Priority | Meaning |
|----------|---------|
| P0 | Critical — security, data loss, broken builds |
| P1 | High — major features, important bugs |
| P2 | Medium — default |
| P3 | Low — polish, optimization |
| P4 | Backlog — future ideas |

Re-prioritize if the current value doesn't match reality — not just
"this feels more important," but tied to a concrete reason (blocks
something now open, affects data integrity, was filed reactively at P1
but turned out to be cosmetic, etc.).

## Step 5: Act

### 5a. Invalid — close

```bash
bd -C "${REPO:-.}" close "$ID" --reason "<what you checked, file:line if applicable, and why it's resolved/superseded/obsolete>"
```

The reason must cite evidence (a file, a PR, a CHANGELOG entry, another
bead ID), never just "no longer needed."

### 5b. Valid, needs a rewrite

Rewrite title and/or body and/or priority in one `bd update` call. Body
should be markdown: a short problem statement, why it matters, and (if
scope is knowable) what "done" looks like. Include code snippets, file
paths, or command output when they make the bead self-contained instead
of requiring the reader to go dig.

```bash
bd -C "${REPO:-.}" update "$ID" \
  --title "<clear, specific, action-oriented title>" \
  --priority <P0-P4> \
  --description "$(cat <<'EOF'
## Problem

<what's wrong, concretely — cite file:line or a command's actual output>

## Why it matters

<impact, one or two sentences>

## Scope

<what "done" looks like, if known>
EOF
)"
```

### 5c. Valid, already good

No title/body/priority change. Still add the theme label (Step 6) — this
bead was genuinely reviewed, not skipped, and the outer loop's report
should reflect that (a confirmed-good bead is a result, not a non-event).

## Step 6: Theme label

Add (don't remove existing unrelated labels) a `theme:<area>` label based
on what part of the codebase/system this touches, so the outer loop can
group the final set for batch work. Applies to every disposition except
5a (closed beads don't need a theme — they're leaving the backlog):

```bash
bd -C "${REPO:-.}" label add "$ID" "theme:<area>"
```

Pick from existing `theme:*` labels already in use where one fits before
inventing a new one — the point is batching, which only works if the
same theme is spelled the same way across beads. Listing labels needs no
shell `grep` pipe: run `bd -C "${REPO:-.}" label list-all` and read the
`theme:*` entries directly from its output (the Grep *tool* is fine to
use elsewhere in this skill — it's shell `| grep` piping specifically
that isn't available here).

## Step 7: Report back

Return one line, in this exact shape, to whatever invoked you (the outer
loop collects these verbatim into its final report):

```text
<id> | <disposition: closed|rewritten|confirmed-good|needs-human-review> | theme:<area> | <one-line reason>
```
