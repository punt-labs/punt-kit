# Git Standard

**Introduced:** 2026-07-27

The mechanical git operations between starting work and pushing it: which
branch a commit lands on, how a branch's history is protected once it is
pushed, how base conflicts are resolved, how local refs are cleaned up after a
merge, when a worktree is warranted and how it is retired, how submodules are
carried, and which operations stop for the operator. This standard owns the
commands; the *workflow* those commands serve — the loops, the PR gate, the
review sequence — belongs to neighboring documents.

Every rule here traces to a failure that happened: a commit on the wrong
branch, a checkout left on a feature branch, a `branch -d` warning after a
squash merge, seven stale worktrees in one repo, a conflict resolved correctly
but recorded nowhere. The mechanics are simple; getting them wrong is
expensive.

---

## 1. Scope and Ownership

This standard owns git mechanics only. Adjacent concerns are owned elsewhere —
cross-reference them, never restate them:

| Concern | Owning standard |
|---------|-----------------|
| Branch-prefix table, commit-message format, the PR loop, poll tick, and merge gate | [Workflow](workflow.md) |
| Local and remote review sequencing, thread resolution, dismissal rules | [PR and Review](pr-review.md) |
| Branch protection, CI, Copilot configuration, merge-button settings | [GitHub](github.md) |
| Destructive-operation consent and the pre-operation safety checks | org-level `CLAUDE.md` § Destructive Operations |

What remains — and what this document specifies — is the sequence of git
commands an agent runs by hand: the branch check, the no-rewrite rule,
conflict resolution, post-merge cleanup, worktree lifecycle, submodule
handling, mission-traceability trailers, the stop-and-ask list, and the
session-close push.

---

## 2. Check the branch before every commit

Before any commit, run:

```bash
git branch --show-current
```

If it prints `main`, stop and create a branch first
([Workflow](workflow.md) owns the prefix table):

```bash
git checkout -b <prefix>/short-description main
```

`main` has branch protection in every repo; direct pushes are rejected
([GitHub](github.md) § Branch Protection). A commit on `main` is not a
shortcut — it is work that cannot be pushed, made in a tree that another
session may be sharing. The check is one command and it precedes *every*
commit, including docs-only and single-line fixes. An agent working in the
main tree rather than a worktree checks the branch each time precisely because
nothing else guards it.

---

## 3. Never rewrite a pushed branch's history

**Never `git rebase` or `git push --force` (or `--force-with-lease`) on a
branch with an open PR.** A force-push rewrites commit SHAs. Reviewers —
Copilot, Bugbot, and any human — anchor their in-flight comments to SHAs;
rewriting the SHAs orphans every one of those comments, and the review round
restarts from nothing.

When the branch falls behind `main` and needs the base, **merge — do not
rebase:**

```bash
git fetch origin main
git merge origin/main
git push
```

Or click **Update branch** in the PR UI. Both add a merge commit and preserve
every existing SHA, so open review threads stay attached. A conflict is
resolved the same way: merge `origin/main` into the branch, fix the conflict,
commit, push. This is the mechanism behind the CHANGELOG-only conflict a recent
session resolved correctly but recorded nowhere — merging the base in is
SHA-preserving and correct; it is written here so it is no longer folklore.

---

## 4. Post-merge cleanup

After a squash merge, four commands in this order:

```bash
git checkout main
git pull --ff-only origin main
git branch -d <branch>
git fetch --prune origin
```

**The order is load-bearing.** A squash merge writes a *new* commit on `main`,
so the feature branch's tip is not reachable from `main`. `git branch -d`
verifies the branch is merged against its **upstream** — the remote-tracking
ref `origin/<branch>` it tracks (falling back to `HEAD` when no upstream is
set) — and `origin/<branch>` still points at the branch tip, so the check
passes and the delete succeeds. If you prune first, that upstream ref is gone,
`-d` can no longer prove the branch merged, and it refuses with a warning —
forcing a `-D` that discards the safety check entirely.

Use `-D` only after confirming the branch carries nothing unmerged:

```bash
git log <branch> ^main        # empty output → safe to -D
```

The `--delete-branch` flag on the merge already removed the *remote* branch;
this sequence cleans up the local branch and stale remote-tracking refs, which
git never removes on its own. A merged PR whose local branch is left behind is
unfinished work — and a checkout left on that dead branch is how the next
session commits into a stale base.

---

## 5. Worktrees

The default is one working tree per repo, one writer in it — the sole-writer
invariant from [Workflow](workflow.md) § Level 3. A worktree is warranted when
that invariant would otherwise break: two or more sessions must write the same
repo at once. `/who` showing another active agent is the trigger.

```bash
git worktree add ../<repo>-<branch> -b <prefix>/short-description main
# ... work, commit, push, merge the PR ...
git worktree remove ../<repo>-<branch>
```

**Removal is an obligation, not a courtesy.** A worktree outlives the branch
that justified it unless you remove it; unremoved, they accumulate — one repo
reached seven stale worktrees before anyone noticed. Remove the worktree as
soon as its branch merges, in the same close-out as the branch delete.

Audit what exists:

```bash
git worktree list           # every worktree and its checked-out branch
git worktree prune          # drop administrative refs for deleted directories
```

When two workers genuinely must share one worktree, sequence them so no two
edit the same uncommitted lines at once — the constraint is not losing work,
not isolating scope (deployed practice, quarry `docs/WORKFLOW.md`).

---

## 6. Submodules

A submodule is a **gitlink**: the parent repo records one commit SHA of the
child, not its files. The team/identity registry mounted at `.punt-labs/ethos/`
is the canonical instance (org-level `CLAUDE.md` § Team Registry).

- **Detached HEAD is normal.** A submodule checks out a specific commit, not a
  branch. `git status` inside it showing detached HEAD is the expected state,
  not an error.
- **Updating the pinned ref is one parent commit.** Advancing the child is a
  detached checkout of the new commit — not a commit itself; only the parent
  records a commit, staging the moved gitlink:

  ```bash
  git -C .punt-labs/ethos fetch origin
  git -C .punt-labs/ethos checkout origin/main   # detached checkout, no commit
  git add .punt-labs/ethos                        # stages the new gitlink SHA
  git commit -m "chore: update ethos submodule"   # the one commit
  ```

  That parent commit moves the pin; consuming repos see the change only after
  their own pin is updated.
- **A leading `-` in `git submodule status` means uninitialized** — the
  submodule's files are not checked out. Initialize before use:

  ```bash
  git submodule update --init
  ```

---

## 7. Commit trailers for mission traceability

Commit-message *format* — Conventional Commits, `type(scope): description` —
is owned by [Workflow](workflow.md) § Branch discipline; do not restate the
prefix table here.

This standard adds one convention. A commit produced under an ethos mission
**should** carry `Mission:` and `Delegation:` git trailers, so the chain
`git blame → commit → trailer → mission contract` is reconstructable — a line
of code leads back to the contract that authorized it, and from there to the
prompt and the audit record.

```text
feat(release): pin org profile to post-merge installer SHA

Mission: m-2026-07-27-020
Delegation: claude → mdm (eval rop)
```

The intended mechanism is a commit-msg hook that stamps the trailers from the
active mission, so an agent never types them by hand. That hook is future work
on the ethos side; until it ships, the convention is specified but not
enforced by tooling — do not require a stamp that does not exist yet. A code
commit missing the trailers is not yet a defect; once the hook lands, an
un-stamped code commit means the work skipped the mission process.

---

## 8. Stop and ask

The following change shared state in ways that are hard to reverse. **Stop and
ask the operator before running any of them.** This list sharpens the
authoritative enumeration in the org-level `CLAUDE.md` § Destructive
Operations — where a rule there is broader, that rule governs:

- `git push --force` / `--force-with-lease` on a branch with an open PR (§3)
- `git rebase` on a branch with an open PR (§3)
- `git reset --hard` anywhere except a worktree you just created and have not
  pushed
- `git branch -D` before `git log <branch> ^main` confirms nothing unmerged
  (§4)
- `git clean -f` and `git stash drop` — both discard work git cannot recover
- Closing or re-opening a PR
- Deleting a branch the operator may not have pulled

Before any destructive git operation, run the safety checks the org standard
requires: `biff who`, `biff finger @<agent>`, then `git branch` and
`git status`. If another agent is active in the repo, confine writes to
`.tmp/`.

---

## 9. Session close and PR prose

**Work is not complete until `git push` succeeds.** A session that ends with
commits sitting only in the local repo has stranded that work. Session close's
job is to push the *current* branch's committed work (the full close-out
sequence lives in [Workflow](workflow.md) § Batch close-out):

```bash
git push                      # push the current branch's commits to its upstream
bd dolt push                  # where the repo tracks issues in dolt
git status                    # must report the branch up to date with its upstream
```

Do not `git pull --ff-only origin main` here: on a feature branch that
fast-forwards the *current* branch toward `origin/main`, which fails or, worse,
drags main's history onto the branch. Updating local `main` belongs to
post-merge cleanup (§4), which runs on `main` after the merge — not to session
close, which runs on whatever branch you are on.

**Plain English over git internals in PR prose.** In a PR title, body, or
review reply, name the commit in words a reader need not decode: "the latest
commit" or a pasted SHA — never `HEAD`. `HEAD` is a pointer whose meaning
depends on who is reading and when; a pasted SHA is unambiguous forever.

---

## Related Standards

- [Workflow](workflow.md) — the three loops, branch-prefix table, commit format, PR loop, merge gate, session close-out
- [PR and Review](pr-review.md) — review sequencing, thread resolution, dismissal rules
- [GitHub](github.md) — branch protection, CI, Copilot configuration, merge-button settings
- org-level `CLAUDE.md` § Destructive Operations — the authoritative consent list and pre-operation safety checks
