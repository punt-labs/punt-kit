# PR and Review Standard

**Updated:** 2026-10-26

## Philosophy

A pull request is not a review mechanism — it is a merge gate. All review
happens before the PR, locally, and code review is agent-owned end to end:
the local review agents before the PR, and remote review (Qodo, Bugbot) as
an automated second opinion on already-clean code, bounded to at most two
rounds. There is no human
code-review gate — the operator may read the diff in the IDE, but that
inspection is non-gating, feeds design discussion only, and nothing in this
sequence waits on it. Human judgment binds at the workflow standard's gates:
direction before code (design ratification) and behavior after (the
repo-specific demo, where a repo defines one) —
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
5. Run `local_review` on the diff (see "Local review" below): the reviewer
   set depends on the diff's size and content
6. Fix every finding. To dismiss a finding as inapplicable, document in the
   review record: (a) the exact finding text, (b) the specific reason it does
   not apply to this code, (c) the code reference. "Intentional," "expected,"
   "by design," and "pre-existing pattern" do not qualify as reasons.
7. `local_review` exits on the first round that produces no findings — there
   is no minimum round count — and never runs more than four fix rounds plus
   one verifying review.

### Before opening a PR

After all missions for the feature complete and each has passed per-mission
local review:

1. `make check` on the full accumulated diff
2. Run `local_review` on the complete diff, which is the unit's first full
   diff — cross-mission issues only appear when the full change is visible
3. Fix all findings using the same documentation standard as above
4. Operator IDE inspection **may** happen here — the operator reading the
   full diff in the IDE. It is optional and non-gating: anything it surfaces
   feeds design discussion (or is fixed like any other local finding), and
   nothing in this sequence waits on it.
5. Run the complete user-facing workflow from install through terminal output,
   including at least one path through a dependency (file I/O, network,
   subprocess). Record the output. Verify that the changed code was actually
   exercised by checking that expected behavior changed in the expected way.
6. Every fix diff goes through `local_review` again before it is pushed,
   including fixes made for PR findings

Only open the PR after step 6 passes. A PR opened before local review is clean
is a procedural violation. The repo's demo, if its `WORKFLOW.md` defines one
(see "Repo-specific human gate" below), runs against the PR head; it does not
change the review sequence.

### Local review

Local rounds are cheap and bugs die here; the PR gate stays short. Local
review is a function the leader runs on a diff, before the PR opens and before
every fix push:

```text
function local_review(diff):
    for round in 1..5:
        if this is the unit's first full diff or diff is 20 lines or more:
            reviewers = `qodo review` + silent_failure_hunter + code_reviewer
        else:
            reviewers = `qodo review`    # a small fix diff
        if diff touches credentials, secrets, or caller text that reaches
                a file, a log line, or a header:
            reviewers += djb             # whatever the diff's size
        if this is not the unit's first full diff:
            scope: regressions this diff introduces, and High findings
                inside it — nothing outside the diff, no Medium or Low on
                unchanged behaviour
        run reviewers in parallel        # qodo review from the worktree,
                                         #   against the pushed base
        re-run once any reviewer that did not complete (error, outage)
        if a reviewer still has not completed:
            report it to the operator
            return blocked               # a review that never ran is not
                                         #   clean
        findings = every reviewer's findings
        if round == 5 and a finding needs a fix:
            report the open findings to the operator
            return blocked
        answer each finding: fix it, or dismiss it with the exact finding,
            the specific reason, and the code reference
        close each local Qodo finding through the Qodo CLI
            (mark-implemented or dismiss, with its local_review_id) —
            an unclosed one comes back as still_open in every later run
        if no finding was fixed:
            return clean                 # nothing found, or all dismissed
        make check; commit
        diff = this round's fix diff     # every change is reviewed,
                                         #   Low fixes included
    # at most four fix rounds, plus a fifth review that only verifies the
    # fourth round's fixes. No deferral beads. Every caller acts only on
    # clean: on blocked, nothing opens and nothing is pushed until the
    # operator rules and local_review then returns clean.
```

The three reviewers are not substitutes — in the vox pilot each found defects
the other two missed — so every first full diff and every fix diff of 20 lines
or more gets all three. A fix diff under 20 lines gets `qodo review` alone.
`djb` (the security reviewer) joins any diff that touches credentials,
secrets, or caller text that reaches a file, a log line, or a header,
whatever its size.

From round 2 on, the review is scoped to what the diff changed: regressions
it introduces and Highs inside it. Without that boundary a failure-focused
reviewer walks outward into code the diff never touched and the rounds do not
converge.

`qodo review` is the engine that later reviews the PR, so what it finds
locally does not come back as a PR round. Close each local Qodo finding
through the Qodo CLI (`mark-implemented` or `dismiss`, with its
`local_review_id`); an unclosed finding returns as `still_open` in every
later run.

### Remote review: Qodo and Bugbot, at most two rounds

Remote review is automated-only — there is no human reviewer in this phase,
and none earlier: code review is agent-owned throughout (see Philosophy).
Because local review already ran to clean, remote findings should be few.
The remote budget is fixed: at most two rounds, and the second only after a
High was fixed.

**Qodo** is the primary remote reviewer, configured by `.pr_agent.toml` (from
the punt-kit `pr_agent.toml` template). It reviews once, when the PR opens,
and never on push. High findings post inline as threads; the
`required_review_thread_resolution` ruleset rule makes each one block the
merge. Medium findings appear in the summary. Lows are dropped by
`comments_routing`.

**Bugbot** reviews each PR once, on its own, when the PR opens (Cursor
dashboard setting: once per PR). Round 1 needs no `bugbot run` comment, and a
push draws no Bugbot review. Its findings are handled whenever they arrive.

**Round 2** — one `/agentic_review` comment plus one `bugbot run` comment —
happens only when round 1's fixes included a High, and it is the last round. A
new High in round 2 goes to the operator; it is never fixed or dismissed on
the leader's own authority.

**Copilot is not a default reviewer.** Repo rulesets carry no
`copilot_code_review` rule (as of 2026-10-26), so Copilot reviews only when
requested. A repo may request one Copilot review per PR, at open and
never on push; its findings are findings like any other.

The model holds only when these settings are in place:

- `.pr_agent.toml` is on the default branch. Qodo reads it from there, so a PR
  opened before it merged runs on the portal defaults.
- "Review every push" is Disabled in the Qodo portal (the portal default is
  Enabled).
- Bugbot is set to review each PR once, at open, in the Cursor dashboard.
- The ruleset has no `copilot_code_review` rule.

If a push still starts a Bugbot run, its findings are findings like any
other.

#### Terms

All terms are read from GitHub; Qodo's login is `qodo-code-review[bot]`.

```text
round(pr)    = 1 + the number of "/agentic_review" comments the leader has
               posted on the PR
trigger(N)   = the PR open, for N = 1; the leader's (N-1)th
               "/agentic_review" comment, for N > 1
head(N)      = the PR head commit when trigger(N) happened
qodo_in(N)   = `qodo read pr-review-session findings --pr-url <url>` reports
               review_session.status "completed" with a commit_sha that is
               head(N) or a later commit on the branch; or the outage
               fallback ran for round N. A late reply to an earlier round
               never completes round N, and a clean review counts like any
               other.
bugbot_in(N) = a "Cursor Bugbot" check run on head(N) or a later branch
               commit, started at or after trigger(N) — the PR open for
               N = 1 (Bugbot's automatic run), round 2's "bugbot run" comment
               for N = 2 — and completed with any conclusion except
               cancelled; or 30 minutes since trigger(N). A run a push
               cancelled reviewed nothing, so it does not count; a later
               push does not undo a completed run. A clean run posts no
               review, so read the check run.
copilot_in   = no Copilot review was requested on the PR, or one was and
               (a review by copilot-pull-request-reviewer exists or 30
               minutes have passed since the request)
pending(pr)  = not skipped(pr) and (not qodo_in(round(pr))
               or not bugbot_in(round(pr)) or not copilot_in)
finding      = any unresolved review thread, from any author, or any Medium
               in Qodo's summary — whenever it arrives, late ones included
answered(f)  = one path per source, never both:
               - a finding with a Qodo id (from the CLI read): its
                 attribution_status is closed (implemented, dismissed,
                 outdated); close it with `qodo pr-review-session
                 mark-implemented` or `dismiss` plus the reason and
                 file:line. A ledger line does not close it.
               - any other finding — Bugbot, a security automation, Copilot,
                 a human, the local outage fallback: fixed by a commit on
                 the PR head, or a ledger comment gives the reason and
                 file:line.
               A finding repeated from an earlier round keeps its answer.
new High     = a High not raised in an earlier round; a manual review may
               re-scan the whole PR and repeat old findings
escalation   = the leader's "escalated:" comment on one new round-2 High;
               closed by a later ledger entry recording the operator's
               ruling and how it was applied
skipped(pr)  = the PR author is a bot ([github_app] ignore_bot_pr in
               .pr_agent.toml); no title or label lets an author skip
reviewed_head = the newest commit covered by a Qodo review, the outage
               fallback, or the local delta review below
bugbot_open  = a Cursor Bugbot check run on the head whose status is not
               completed (queued or in progress) and that was created under
               30 minutes ago
```

"Ledger comment" is a PR comment that records one finding, its reason, and
the code reference. "Pre-existing," "intentional," "expected," and "by
design" are not reasons.

#### The poll loop

The leader polls the PR in the background, never with a blocking watch and
never with a foreground sleep loop. Cadence is 3 minutes while anything is
pending and 15 minutes after, when only CI or a late thread can change state.

```text
function poll_tick(pr):
    state = current reviews, threads, checks
    N = round(pr)
    if CI failed: fix in this PR
    if not skipped(pr) and not qodo_in(N)
            and 30 minutes have passed since trigger(N)
            and the fallback has not yet run for round N:
        run code_reviewer locally on the diff Qodo was asked to review;
            it completes round N for qodo_in; its findings have no Qodo
            id, so they take the ledger path       # outage fallback
    for each finding not answered(f) and not under an open escalation:
        if N == 2 and f is a new High:
            post an escalation comment; the operator rules
        else:
            fix it now, or answer it by its source's path (answered(f))
            # never re-litigated; Qodo Lows are dropped by comments_routing;
            # no deferral beads
    for each escalation the operator has ruled on:
        apply the ruling; record it in a ledger comment
        if the finding has a Qodo id: also close it through the Qodo CLI
            (mark-implemented or dismiss, per answered(f)); a ledger line
            alone leaves it unanswered and the next tick escalates it again
    if fixes were made: delegate them to a bare agent; make check; commit
        if local_review(the fix diff) is blocked:
            stop; the operator rules
        push once                          # every fix reaches the PR head
    resolve each thread that is answered, one by one — the leader
        resolves, not the agent
    if not skipped(pr) and not pending(pr) and N == 1
            and a High was fixed since trigger(1):
        comment "/agentic_review"; comment "bugbot run"   # opens round 2,
                                                          #   the last
    if not pending(pr) and the PR head is newer
            than reviewed_head:
        run code_reviewer locally on the reviewed_head..head delta; its
            findings are findings like any other   # bounded rounds, but
                                                   #   no unreviewed merge
    if the repo defines a demo and it is not confirmed for the head
            and nothing was pushed this tick:
        run it per the repo's WORKFLOW.md      # see "Repo-specific human
                                               #   gate" below
    if not pending(pr) and not bugbot_open and no finding is unanswered:
        cadence = 15m
    else: cadence = 3m
    if the poll's interval is not cadence:
        cancel the poll job; schedule the poll at cadence in its place
    re-read state                          # the gate must see this tick's
                                           #   push and comment
    if merge_gate(state): merge (squash); close_out()

function merge_gate(state) -> bool:
    return CI green on the latest commit
       and not pending(pr)                 # no requested review outstanding
       and not bugbot_open                 # a push-started run's findings
                                           #   land before the merge
       and (skipped(pr) or reviewed_head is the PR head)
       and every finding is answered
       and zero unresolved review threads
       and round(pr) <= 2
       and no escalation is open
       and demo_ok(pr)                     # true when the repo defines no demo
    # A push restarts CI, not review. When this returns true: merge
    # explicitly. No auto-merge. No admin override. Do not ask, do not wait.
```

A finding that arrives late is handled the moment it arrives, like any other.
A fix push is reviewed locally first (`local_review` on the fix diff) and is
never followed by a request for another remote review; the only way back into
remote review is round 2, and only after a High fix.

#### Repo-specific human gate (demo)

Some behavior only a human can judge. Each repo's `docs/WORKFLOW.md` defines
its demo — what is driven, through which entry point, and what the operator
confirms — or states that it has none. `demo_ok(pr)` is true when the repo
defines no demo, or when the demo was confirmed on a commit that is the PR
head or an ancestor of it with nothing demo-relevant landed since. A failed
demo is a finding like any other. The demo is a human check on observed
behavior, never a diff review.

#### Close-out

```text
function close_out():
    cancel the poll loop
    delete the branch; checkout main; pull
    send the merge recap                   # every merge, unprompted, with the
                                           #   review data block below
    start the next unit immediately        # no stopping to report
```

The merge recap carries a review data block, pasted verbatim, from the
workspace script (`.bin/review-metrics.py` in the `punt-labs` workspace repo):

```bash
.bin/review-metrics.py pr <owner/repo> <N> --format recap
```

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
- [Git](git.md) — git mechanics: no-rewrite rule, conflict resolution, post-merge cleanup, worktrees, submodules, stop-and-ask
- [Agent Engineering](agent-engineering.md) — engineering principles including reversibility and test coverage
- Destructive git operations (`git reset --hard`, `git push --force`, `git stash drop`, etc.) require explicit operator consent before execution — see org-level `CLAUDE.md` § Destructive Operations
