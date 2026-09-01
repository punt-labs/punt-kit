"""Timeout budgets for subprocess calls made during a release.

Legitimate PY-OO-7 primitives module — no class here, nothing to be
"missing methods on".
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _run's default budget and the named opt-ins for longer-running call sites.
# ---------------------------------------------------------------------------
# The default is short by design. Metadata calls — git rev-parse, gh api
# graphql, gh pr view, git status — return promptly or not at all, so a call
# that outlives this budget has hung, and the release surfaces that as a
# diagnosis instead of a two-hour stall. Long-running call sites opt in
# explicitly to one of the named budgets below.
DEFAULT_RUN = 60

# uv resolves dependencies, downloads wheels, and may build native bindings.
# A first-run resolve on a cold cache takes minutes; anything past ten is a
# wedge, not a slow install.
UV = 600

# git fetch/push/pull over the network. Usually finishes in a second; the
# budget is wide enough to swallow a transient hiccup but narrower than a
# wedge on a broken socket.
GIT_NETWORK = 300

# git commands that fire a repo hook — checkout, commit, merge, push, pull.
# Every punt-labs repo installs beads client hooks (post-checkout,
# pre-commit, post-commit, post-merge, pre-push) that run
# `bd hooks run <event>` against a networked Dolt server with its own
# BEADS_HOOK_TIMEOUT default of 300s. Under phase 9 + phase 10 concurrency,
# several hooks hit Dolt at once and the tail latency runs up against that
# ceiling. The budget here must live above the hook's own tolerance — not
# equal to it — because git does its own I/O around the hook (write index,
# resolve refs, network for push/pull). Raising the shared metadata
# default is the wrong lever: 60s is what turns a two-hour hang into a
# one-minute diagnosis for genuine metadata calls, and must stay that way.
GIT_HOOK = 600

# Quality gates — mypy, pyright, pytest, ruff, `make check`, `go test`. The
# full test suite on a cold cache can take a few minutes; a release aborts if
# it cannot complete inside the budget.
QUALITY_GATE = 1800

# ---------------------------------------------------------------------------
# Phase 6 (CI wait) budgets.
# ---------------------------------------------------------------------------
# GitHub does not register a tag-triggered run instantly, so phase 6 polls
# rather than sleeping a fixed interval: a slow registration extends the wait
# instead of selecting whatever run happens to be newest at the moment we look.
CI_RUN_POLL_INTERVAL = 5.0
CI_RUN_POLL_ATTEMPTS = 24

# Conclusions that are a genuine verdict from CI, as opposed to gh being
# unable to tell us one. Anything outside this set means the watch exited
# non-zero for a reason of its own — a deleted run, an expired token, a
# dropped connection — and phase 6 has no verdict to report.
CI_ADVERSE_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
)
CI_WATCH = 7200
# Listing runs is a fast metadata call, so it does not inherit the watch's
# two-hour budget — a listing that blocks that long has failed, and waiting
# on it burns the poll window that exists to find the run.
CI_RUN_LIST = 60

# ---------------------------------------------------------------------------
# RequiredChecksWaiter's no-checks grace window.
# ---------------------------------------------------------------------------
# A commit that will never register a single check — [skip ci] on the head
# commit, or every workflow's `paths:` filter excluding every changed file —
# looks identical, from the poll loop's point of view, to a commit whose
# checks just haven't started yet. Left unbounded, the loop waits out the
# full CI_WATCH deadline (two hours) before failing, which is what let the
# ethos #496 post-release PR (carrying [skip ci]) hang the release instead of
# failing fast. Five minutes is long enough for GitHub to attach the first
# CheckRun to a commit that has any workflows to run at all, and short
# enough that a genuine zero-checks misconfiguration surfaces as a fast,
# actionable failure instead of a silent multi-hour stall.
NO_CHECKS_GRACE = 300
