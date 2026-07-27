# PR and Review Standard

## Philosophy

A pull request is not a review mechanism — it is a merge gate. All review
happens before the PR, locally, and code review is agent-owned end to end:
the local review agents before the PR, and remote review (Copilot, Bugbot)
as an automated second opinion on already-clean code. There is no human
code-review gate — the operator may read the diff in the IDE, but that
inspection is non-gating, feeds design discussion only, and nothing in this
sequence waits on it. Human judgment binds at the workflow standard's gates:
direction before code (design ratification) and behavior after (the demo) —
never the diff between (see the Roles section of the
[Workflow standard](workflow.md)).

Coding is not the whole task. Code that compiles and passes tests has not been
verified. Verified means: installed, running, exercised manually and
automatically against the real integration target. A PR opened before this work
is done is premature.

This standard governs PR boundaries and review sequencing. Commit discipline
(micro-commits, 1–5 files per commit, quality gates per commit) is defined
separately in the "Branch Discipline" section of the workflow standard and is not relaxed here. Micro-commits
within a branch remain required; this standard prohibits micro-PRs across
branches.

## PR Boundaries

**One PR = one complete, locally-verified unit of work.**

A unit is defined by rollback granularity: if this change broke production,
what would you need to revert together? That is your PR. Split when you want
independent revert capability — not to manage reviewer cognitive load, not to
keep diffs small, not because the work is "getting big."

**Prohibited reasons to split a PR:**

- "The diff is large" — size is not a boundary criterion
- "I'll clean it up in a follow-on PR" — known work belongs in this PR
- "It's a separate concern" — if it ships together and reverts together, it belongs together

**Valid reasons to split a PR:**

- Independent rollback — you want to revert one part without the other
- Sequential dependency — the second PR cannot be written until the first merges
- Blast radius — the changes touch systems that are independently shippable and
  independently revertible. Test: if component A's tests fail, can component B
  ship without it? If no, they are not orthogonal and belong in one PR.

## The Review Sequence

Every change follows this sequence. Local gates run first. Remote gates run
last. Do not invert this.

```text
Mission → Code → Install → Test → Local Review → [repeat] → Next Mission
                                                              (repeat above)
All missions done → Full-diff Local Review → PR → Remote Review → Merge
```

### After each coding mission

Run local review immediately after each mission completes, before starting the
next mission. Starting a new mission without completing local review on the
prior mission is a procedural violation — equivalent to skipping `make check`.
If missions were batched without per-mission review, treat the entire batch as
one mission and run the full sequence on the combined diff before proceeding.

1. `make check` — must pass, zero exceptions
2. Install locally — see "What Installed Means" below
3. Run automated tests against the installed artifact
   - If the changed code has no automated test covering it, that is a required
     finding. Write the test before marking step 3 complete. Running a suite
     that does not cover the change is not verification.
4. Exercise the feature manually — run it, observe output
   - Before running: write down expected output for each case
   - After running: compare actual to expected. Differences are bugs.
   - Exercise failure modes, not just the happy path:
     - One case where input is invalid or malformed
     - One case where a dependency is unavailable or returns an error
     - One boundary condition (empty, oversized, or at the limit)
   - Paste the actual output. The paste is a record of the expected-vs-actual
     comparison, not proof that a command ran.
5. Run `feature-dev:code-reviewer` on the diff
6. Run `pr-review-toolkit:silent-failure-hunter` on the diff
7. Fix every finding. To dismiss a finding as inapplicable, document in the
   review record: (a) the exact finding text, (b) the specific reason it does
   not apply to this code, (c) the code reference. "Intentional," "expected,"
   "by design," and "pre-existing pattern" do not qualify as reasons.
8. Re-run both agents. Exit this loop on the first round that produces no
   findings — there is no minimum round count. Do not continue running rounds
   after both agents return clean.

### Before opening a PR

After all missions for the feature complete and each has passed per-mission
local review:

1. `make check` on the full accumulated diff
2. Run both local review agents on the complete diff — cross-mission issues
   only appear when the full change is visible
3. Fix all findings using the same documentation standard as above
4. Operator IDE inspection **may** happen here — the operator reading the
   full diff in the IDE. It is optional and non-gating: anything it surfaces
   feeds design discussion (or is fixed like any other local finding), and
   nothing in this sequence waits on it.
5. Run the complete user-facing workflow from install through terminal output,
   including at least one path through a dependency (file I/O, network,
   subprocess). Record the output. Verify that the changed code was actually
   exercised by checking that expected behavior changed in the expected way.
6. Re-run agents until clean

Only open the PR after step 6 passes. A PR opened before local review is clean
is a procedural violation.

### Remote review

Remote review (Copilot, Bugbot) is automated-only — there is no human
reviewer in this phase, and none earlier: code review is agent-owned
throughout (see Philosophy). Because local review already ran multiple
rounds, remote findings should be fewer and more targeted. Expect 2–6 remote
rounds, with the operational goal of driving this toward 1–2 as local review
improves.

Every remote finding requires a code fix. To dismiss a finding as inapplicable,
post in the PR thread: (a) the exact finding text, (b) the specific reason it
does not apply, (c) the code reference. Re-request review after posting. If the
reviewer raises the same finding again, the dismissal was insufficient — fix
the code.

Re-request review after each fix push. Merge only when the last remote cycle is
clean: no new comments, all checks green, all threads resolved.

## What "Installed" Means by Project Type

"Installed" means exercising the artifact the user receives, not the source
tree you developed against.

| Project type | What "installed" means |
|---|---|
| Python CLI | `uv build` → `uv tool install --force dist/*.whl` |
| Python MCP server | Register the server config, verify tool appears in Claude tool list. MCP server changes require a Claude restart — ask the user and wait. |
| Pure plugin | Copy to `~/.claude/plugins/`, verify command appears in `/help`. Plugin prompts reload automatically. |
| Go binary | `go install ./...`, verify binary is on PATH and runs |
| Library | Install wheel into a consumer project's venv, run the consumer's tests |

For all types: run the automated test suite against the installed artifact, not
via `uv run` or `go run` from the source tree.

## Anti-Patterns

**Micro-PR**: Opening a PR for each mission, each file, or each layer of a
feature. Each PR incurs remote review latency (4–7 minutes, fixed cost)
regardless of size. The correct unit is one rollback-coherent feature.

**Review at the end**: Running local review agents only before opening the PR.
Cross-mission interactions are only visible when the full diff is assembled —
but per-mission review catches the issues while the code is still fresh and
context is available. Both passes are required.

**Code as the deliverable**: Marking a mission complete when code compiles and
tests pass. The deliverable is verified, installed, running behavior — not
source code.

**Dismissal without documentation**: Calling a review finding "not valid"
without specifying why in the documented format. "I don't think this applies"
is not a dismissal — it is a skipped finding.

---

## Related Standards

- [Workflow](workflow.md) — development loop, branch discipline, commits
- [Agent Engineering](agent-engineering.md) — engineering principles including reversibility and test coverage
- Destructive git operations (`git reset --hard`, `git push --force`, `git stash drop`, etc.) require explicit operator consent before execution — see org-level `CLAUDE.md` § Destructive Operations
