You are the worker on ethos mission m-2026-10-23-017 (bead pkit-ewox). It is a re-scoped successor to m-2026-10-23-016. Read the full contract first: `ethos mission show m-2026-10-23-017`. It covers five items, X1-X5, plus one ruling. gvr's reflection is in the worktree at .tmp/gvr-reflect-r2.yaml.

Worktree: <repo>/.claude/worktrees/release-legacy-helpers, branch refactor/release-legacy-helpers. Use absolute paths and one shell command per Bash call. Never chain a commit after a gate. Read the FULL `make check` output.

The work:
- X1: bring ThreadedStep.collect back to complexity <= 10.
- X2: one public operational-error classification, used by both the worker-thread path and the main-thread handler.
- X3: no test may reach a release.py private name through `vars()`. Extend the guard to catch that, and add a negative test.
- X4: move the last cross-module test fake to helpers.py, and drop its suppressions.
- X5: VERSION continuation, `typeset`, and a warning when a later assignment is computed.

Bar:
- Each behavior fix is test-first.
- `make check` green before every commit.
- The assertion count does not drop.
- The suppression count strictly falls.
- No file that was over 300 lines at 035fb7e grows past that.
- OO does not regress, and never by cutting docs.
- No CHANGELOG edits. List the user-visible changes in your result instead.

Commit one logical step at a time with `git add <file>` only, as Conventional Commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. If a command is denied, stop and report it.

When done, write <repo>/.tmp/missions/results/release-legacy-helpers-r10.md and submit it via `ethos mission result`. Include:
- each item, with its commit and evidence
- complexity before and after for X1
- suppression counts
- user-visible changes
- the final `make check` output