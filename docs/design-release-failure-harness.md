# Design: Release Engine Failure-Path Test Harness

**Status:** ACCEPTED
**Epic:** pkit-f85t — release engine: phase logic fixes and a failure-path test harness
**Author:** adb (design mission m-2026-09-10-007)
**Beads reconciliation:** the hosted DoltDB was unreachable while this design
was written and recovered afterward. All 7 original epic children are closed
(fixed in earlier waves); the harness is the epic's remaining shared
deliverable. The design's own defect findings (§4) are filed as
pkit-f85t.5–.8. §4 was extended after that filing with **defect #8** (the
Phase 5 tag-then-push resume bug, P0) during a subsequent review round —
it is not yet covered by an existing `pkit-f85t` child; see §4 item 8 and
Wave 4 for the filing note. No child bead conflicts with this plan.

## 0. The pattern to kill

Every release-engine defect on record — `pkit-d7mz`, `pkit-plxh`, `pkit-dlv6`,
`pkit-d8ij`, `pkit-mjcb`, `pkit-8r6`, `pkit-9n6q`, `pkit-fwql`, the four
`pkit-f85t.1`–`.4` bugs, and the DES-029 vox v5.0.4 incident — was discovered
the same way: a live release broke with an operator watching, and the fix
followed a post-mortem reconstruction of what must have happened (DES-029's
own text: "no run log survived; the leading hypothesis is..."). Not one of
these thirteen defects (8 named beads + 4 `pkit-f85t` children + the DES-029
incident) has a regression test that existed *before* the incident that found
it. `tests/test_release.py` is 7,169 lines and already covers an
enormous amount of phase logic — but every one of those tests was written
*after* its failure mode was already live in production once.

This document is a design for closing that gap: a harness that lets an agent
write "what if `gh pr merge` returns a 502 here" or "what if SIGINT arrives
mid-Phase-10" as a test, before it happens to an operator. It is not a
rewrite of `tests/test_release.py` — it is an extension that reuses the
existing seams and adds the ones that are missing.

## 1. Survey: what test infrastructure already exists

`tests/test_release.py` is not a naive test file — it already implements
several of the load-bearing patterns a failure-path harness needs. Reading it
end to end (all ~230 test functions) before designing anything new is what
this section is for; duplicating any of the following would be waste.

### 1a. The `ReleaseOps` seam (already the harness's foundation)

`phases/shared/ops.py` defines `ReleaseOps` as a `Protocol` — `run`, `ok`,
`info`, `dry`, `warn`, `fail`. Every phase class and every shared collaborator
(`GithubRepo`, `PrMerger`, `RequiredChecksWaiter`, `SiblingRepo`, ...) takes
one at construction and never touches a bare `subprocess.run` or `print`
directly. `release.py`'s `_ReleaseOpsAdapter` is the only concrete
implementation, and it forwards to `release.py`'s own module-level `_run`,
`_ok`, `_info`, `_dry`, `_warn`, `_fail` names — which is what lets
`monkeypatch.setattr(release_mod, "_run", fake_run)` reach every collaborator
transitively, with zero changes to call sites.

This is the single biggest asset the harness has. It means a fault-injection
double does not need to know about 11 phase classes and a dozen shared
collaborators — it needs to know about one function signature
(`run(cmd, *, cwd, timeout, check, capture) -> CompletedProcess[str]`) and one
monkeypatch target (`release_mod._run`). Everything downstream of that single
patch point observes the fake.

### 1b. Real git repos, not git doubles

Every test that needs git state builds a *real* git repository in `tmp_path`
(`_init_git_repo`, `_make_release_project`) — actual commits, actual tags,
actual branches, an actual `origin` remote pointed at itself so `fetch`/`pull`
work. This is deliberate and correct: git's own behavior (merge-base
ancestry, `--porcelain` status line formats, ref resolution, `rev-parse`
short-SHA truncation) is exactly the kind of thing a hand-written fake would
get subtly wrong, and several of the historical defects (`pkit-9n6q`'s
ancestor check, `pkit-dlv6`'s prior-tag inspection) are precisely about git
plumbing edge cases. The harness must keep this pattern for anything git can
answer locally — it is the cheapest source of ground truth available and
should never be faked.

### 1c. Ad hoc `gh`/network fakes, per test

Where the existing suite is weakest is the boundary the real-git strategy
cannot reach: `gh` CLI output (PR state, CI run lists, GraphQL check-status
payloads) and PyPI. Today, each test that needs one writes its own closure
matching on `cmd` argv fragments — e.g. `_fake_gh_run` (line 3581),
`_fake_get_github_repo` (line 2380), `_fake_which` (line 6111), and dozens of
inline `def fake_run(cmd, **kw): if cmd[:2] == [...]: return
subprocess.CompletedProcess(...)` closures scattered through the file. This
works, and test-by-test it is readable, but it does not scale as a *fault
injection* surface for three reasons:

1. **No shared vocabulary for failure shapes.** Every test that wants to
   simulate "gh returns malformed JSON" or "gh times out" reinvents the
   `CompletedProcess`/`TimeoutExpired` construction from scratch. There is no
   single place that owns "the shapes gh can fail in."
2. **No contract check against real `gh` output.** A hand-rolled JSON fixture
   for `gh pr list --json number,state,headRefOid` can drift from what `gh`
   actually emits (a field renamed, a type changed from string to number)
   with nothing to catch it — see §3 for the fix.
3. **Fault injection is all-or-nothing per test.** A test either fully scripts
   a `fake_run` for its scenario or it doesn't touch that code path at all.
   There is no way to say "inject exactly one 502 on the third `gh pr merge`
   call, then let everything else through to the real fake" without writing
   a new bespoke closure.

### 1d. Timeout/sleep patching — three separate seams, not one

`punt_kit.release` imports `time` and keeps it importable (`# noqa: F401`)
specifically so `monkeypatch.setattr(release_mod, "time.sleep", ...)`-style
patches resolve. But **three other modules own their own `time` import and
call `time.sleep` directly, independent of `release.py`'s**:

| Module | Sleep call | Patched today via |
|---|---|---|
| `phases/shared/gh.py` (`RequiredChecksWaiter.wait`) | `time.sleep(15)` (multiple call sites) | tests shrink `NO_CHECKS_GRACE`/deadlines and patch `gh.time.sleep` directly, or accept real (short) sleeps |
| `phases/shared/pr_merge.py` (`PrMerger.merge`, retry loop) | `time.sleep(wait)`, `wait = 10 * (attempt+1)` | not patched anywhere in the current suite — retry-path tests either don't reach 6 attempts or eat real wall-clock time |
| `phases/shared/ci_run.py` (`TagRunSelector.poll`) | injectable `sleep: Callable[[float], None] = time.sleep` parameter | the one seam done right — tests pass a fast poller or shrink `attempts`/`interval` |

This is a real inconsistency, not a hypothetical one: `ci_run.py`'s
`TagRunSelector.poll` takes `sleep` as a constructor-injected callable, while
`gh.py` and `pr_merge.py` hard-code the module global. A harness that wants
to exercise `PrMerger.merge`'s 6-attempt transient-merge-block retry loop
without five real `time.sleep(10..50)` calls (up to 150s of real wall-clock
per test — the loop sleeps only after attempts 1–5, `wait = 10 * (attempt +
1)` for `attempt` in `0..4`; attempt 6 either succeeds or fails outright with
no sixth sleep) either has to monkeypatch three distinct dotted paths
(`punt_kit.release.time.sleep`, `punt_kit.phases.shared.gh.time.sleep`,
`punt_kit.phases.shared.pr_merge.time.sleep`) or accept the real delay. No
test today exercises the pr_merge retry loop's later attempts at all —
confirmed by grep: no test references `merge_attempt` or asserts on `attempt
4`/`5`/`6` behavior. That gap is itself in the fault-injection matrix (§4,
Phase 4/9/10 row).

### 1e. What is already covered well (do not re-litigate)

Reading `tests/test_release.py`'s ~230 test names (all enumerated during
research; the full list is not reproduced here) makes clear these areas are
already thoroughly covered and the harness should build *on* them, not
duplicate them:

- Preflight: dirty tree, untracked files, wrong branch, empty changelog,
  Makefile-vs-hardcoded-gates branching, stale prior tag detection (6+ tests).
- `RequiredChecksWaiter`: branch protection on/off, ruleset governance,
  malformed/slow/timing-out GraphQL, the no-checks grace window and its
  ceiling-division message, interrupt-during-wait (12+ tests).
- `TagRunSelector`: stale runs, late-arriving runs, wrong-branch/wrong-event/
  wrong-commit rejection, unresolvable tags, `gh` failures vs. genuine misses,
  malformed JSON, hung `run list`/`run watch` (18+ tests).
- Phase 10 propagation: concurrent execution, error collection across
  threads, sibling-branch recovery (feature branches left alone, propagation
  branches reset, mixed dirt), install-all.sh/marketplace/website matching
  by short-name vs. URL-with/without-`.git` (20+ tests).
- Phase 11 verify: every one of the 8 checks has both a pass and a fail case,
  including the `pkit-9n6q` ancestor-vs-resolves-only distinction for both
  the install-all.sh SHA and the profile SHA.
- Interrupt/timeout conversion at the `run_release` level: `TimeoutExpired`
  → diagnosed exit with `--resume-from`, propagation-failure-then-verify
  ordering, incomplete-release reporting.

## 2. Harness architecture

The harness is three additive pieces layered on the existing `ReleaseOps`
seam — none of it requires touching a phase class or a shared collaborator,
because every one of them already takes `ops` as a constructor argument.

### 2a. `FaultInjectingOps` — a scriptable `ReleaseOps` double

A single test double, `tests/harness/fault_ops.py`, implementing `ReleaseOps`
by wrapping a *real* `_run` (so real git calls still hit a real git binary
against the `tmp_path` repo per §1b) plus a **routing table** of fault rules:

```python
@dataclass(slots=True)
class FaultRule:
    """One scripted response for commands matching an argv prefix.

    ``match[0]`` compares against ``Path(argv[0]).name`` — production
    ``gh`` call sites resolve the binary via ``shutil.which("gh")``
    (pr_merge.py:96), so ``argv[0]`` is an absolute path like
    ``/usr/bin/gh``, never the bare string ``"gh"``. ``match[1:]`` compares
    exactly against ``argv[1:len(match)]``. This is the one normalization
    rule the router applies; everything else is literal prefix matching.
    """

    match: Sequence[str]  # argv prefix, e.g. ["gh", "pr", "merge"] — element
    # 0 matched by basename per the docstring above
    skip: int = 0  # ignore this many otherwise-matching calls before engaging
    times: int | None = 1  # None = every remaining match after `skip`
    response: CompletedProcessSpec | None = None
    responses: Sequence[CompletedProcessSpec] | None = None  # one response
    # per consumed match, in order — e.g. [open_pr, merged_pr] for an
    # OPEN -> MERGED transition across two calls to the same command
    raises: type[BaseException] | BaseException | None = None


class FaultInjectingOps:
    """A ReleaseOps that delegates to a real _run, except for scripted faults.

    Unmatched *network-touching* commands are a hard failure, not a
    silent passthrough — see the deny-by-default note below.
    """

    def __init__(
        self,
        *,
        real_run: RunFn,
        rules: Sequence[FaultRule],
        passthrough: Sequence[str] = (),
    ) -> None: ...

    def run(self, cmd, **kw) -> subprocess.CompletedProcess[str]:
        if rule := self._match(cmd):
            return rule.apply(cmd)
        if cmd[0:1] == ["git"] or Path(cmd[0]).name in self._passthrough_names:
            return self._real_run(cmd, **kw)
        raise AssertionError(
            f"unmatched network command in a fault-injection test: {cmd!r} — "
            "add a FaultRule or an explicit passthrough entry"
        )
```

This is the vocabulary §1c is missing: "the third `gh pr merge` call returns
exit 1 with `'required status check'` in stderr, then let the fourth through"
becomes `FaultRule(match=["gh", "pr", "merge"], skip=2, times=1, raises=...)`
(the "third call" is the third match after two skipped), and an OPEN→MERGED
state transition across repeated `gh pr view` polls becomes one `FaultRule`
with a two-element `responses` sequence — not a bespoke closure. Every
existing ad hoc `fake_run` in `tests/test_release.py` is expressible as one or
two `FaultRule`s, and new tests get a compact scenario-description style
instead of hand-rolled `CompletedProcess` construction. **This is additive** —
it does not replace `monkeypatch.setattr(release_mod, "_run", ...)`, it *is* a
thing that gets installed at that exact patch point. Existing tests using the
inline-closure style keep working unmodified.

**Deny-by-default for network commands.** §1b keeps real git delegation
(git plumbing is cheap ground truth and stays real for anything unmatched).
`gh` is different: it is the one command class that reaches the live network
and a real GitHub org. An unmatched `gh` call must not silently fall through
to `real_run` — a test that intends to inject exactly one fault and forgot
that a later phase also calls `gh` would otherwise execute that later call
against production GitHub with no warning, exactly the failure mode this
design exists to prevent. `FaultInjectingOps` therefore raises
`AssertionError` on any unmatched command whose basename is not `git` and is
not in the constructor's `passthrough` allowlist (for the rare case — e.g.
`gh --version` — where hitting the real binary but not the network is
genuinely safe and desired). This is a Wave 0 acceptance criterion: a unit
test asserts that an unrouted `gh` call raises rather than delegates.

### 2b. Recorded-fixture library + contract test (drift avoidance)

The mission's evaluation criteria require the fake `gh`/git surfaces to be
"contract-tested against real tool output shapes or generated from recorded
fixtures" — this is the mechanism:

1. **Recording.** A `tools/record_gh_fixtures.py` script (run manually,
   never in CI, against a real punt-labs repo with a real `gh` session) shells
   out to every `gh` invocation shape the release engine makes — `gh pr list
   --json ...`, `gh run list --json ...`, `gh api graphql -f query=...` for
   both a governed and ungoverned repo, `gh pr view --json state`, `gh pr
   merge` success and a real transient-block failure if one can be captured —
   and writes each response to `tests/fixtures/gh/<name>.json`, with secrets
   (tokens, usernames beyond the punt-labs org, private repo names) scrubbed.
2. **Contract test.** `tests/test_gh_fixture_contracts.py` asserts, for each
   fixture, that the **shape** the release engine's parsing code expects
   (top-level keys, value types, nested structure) matches the recorded
   fixture. The production code (`phase06_ci_wait.py`, `gh.py`) does not
   define `TypedDict`s — it narrows `object`/`dict[str, object]` with
   `cast(...)`, which is a static-only annotation with zero runtime effect;
   reusing those casts in a test would type-check but assert nothing. The
   contract test instead needs its own runtime schema, owned by the harness:
   a small `tests/harness/gh_shapes.py` module defining a `TypedDict` per
   response shape (for readability and mypy coverage of the test file
   itself) *plus* an explicit validator function per shape — `assert
   set(payload) >= {"number", "state", "headRefOid"}`,
   `isinstance(payload["number"], int)`, and so on down through nested
   structure — that actually walks the fixture at test time and fails loudly
   on a missing key, a renamed field, or a type that changed shape. The
   `TypedDict` documents the contract; the validator function enforces it.
   If `gh`'s CLI changes a field name or a JSON shape in a future version,
   this test fails on the *fixture*, independent of any hand-rolled fake in
   a specific test — catching drift at its source instead of at whichever
   test happens to exercise that shape.
3. **Fixture reuse.** `FaultRule.response` can load a recorded fixture by
   name (`FaultRule.from_fixture("gh_pr_list_open.json")`) instead of an
   inline dict literal — so a scenario test's "what does a normal `gh pr
   list` response look like" reuses the same ground truth the contract test
   checks, rather than each test maintaining its own drifted copy.
4. **Refresh cadence.** Recording is not automated (it requires a live `gh`
   session and a real repo) — it is a manual step run when `gh`'s CLI version
   bumps materially, or when a new response shape is added to the release
   engine's parsing. `tools/record_gh_fixtures.py --check` (a lightweight
   mode using `gh --version` plus a page of the CLI's own changelog) can flag
   "fixtures are N versions of `gh` old" as an informational note, not a
   gate — actual gate is the contract test in step 2, which fails
   deterministically without any live network access.

This closes the reality-drift risk without requiring network access or live
credentials in CI: the contract test runs offline against static fixtures;
only the (manual, out-of-band) recording step touches the network.

### 2c. Simulating what git and `gh` cannot express

Three failure classes fall outside "a subprocess returns a different exit
code or stdout," and need dedicated harness support:

**SIGINT / interrupt timing — two distinct mechanisms for two distinct
claims.** `_interrupted` is a module-level `threading.Event` on `release.py`;
`RequiredChecksWaiter.wait` is the one poll loop that checks it (per
DES-029). The harness needs two different primitives here, not one, because
they reproduce different things:

- `interrupt_after(ops, after_match: FaultRule)` sets `release._interrupted`
  immediately *after* a specific rule-matched call to `.run()` returns —
  anchored to a rule match (see the anchoring note below), not a raw call
  count. This models "the interrupt arrived and was observed at the next
  poll boundary *after* this subprocess call completed" — i.e. it tests
  interrupt-*observation* ordering (does the next `.wait()` iteration see
  the flag and exit promptly?), not interrupt-*during*-a-call timing. This
  is the right and sufficient tool for most of §3's SIGINT rows, and it is
  strictly more reproducible than a real OS `SIGINT` (which nothing in the
  current suite sends, and which would be flaky under pytest-xdist) because
  it pins the interrupt to an exact point in the call sequence instead of a
  wall-clock race.
- **What `interrupt_after` cannot do:** reproduce DES-029's actual failure
  mechanism — a subprocess call that is *itself* still blocked when the
  interrupt arrives, with `ThreadPoolExecutor.__exit__`'s `shutdown(wait=True)`
  join stuck behind it. Setting the event after `.run()` returns can never
  model "in flight during the call" because there is no in-flight moment to
  model. Wave 3 (the wave that targets matrix row 36's actual mechanism, not
  just its post-fix reporting path) needs a second primitive: a `FaultRule`
  whose `apply()` blocks on a `threading.Event` the test controls directly —
  the test thread starts the phase call on a worker thread, waits until the
  blocking rule signals it has been entered, sets `release._interrupted`
  while the call is still blocked, then releases the rule's `Event` and
  asserts the join returns promptly instead of waiting out the blocked call.
  This is a distinct harness helper (`BlockingFaultRule` or an `apply=`
  callable hook on `FaultRule`), not a variant of `interrupt_after`.

**Anchoring the interrupt point to a rule match, not a global call count.**
An earlier version of this design keyed `interrupt_after` to `.run()`'s Nth
call across the whole test. That does not work: each phase issues a variable
number of calls depending on preflight state, PR existence, and retry counts,
so there is no stable global call number that means "phase N just
completed" — and Phase 9/10 run concurrently, so even a stable per-phase call
count would interleave nondeterministically across the two worker threads,
making "call 14" mean a different thing on every run. `interrupt_after`
therefore anchors to a *rule match* instead: `after_match` names a
`FaultRule` (typically one already in the test's rule list, e.g. "the final
`git push origin <tag>` of Phase 5") and the event fires when that specific
rule's Nth consumption completes, independent of how many other calls
happened before or concurrently with it. This is the same seam
`FaultRule.skip`/`times` already provide (§2a) — `interrupt_after` is a thin
wrapper that fires the event as a rule's `apply()` side effect rather than
introducing a second counting mechanism.

**Concurrency interleaving (Phase 9/10).** The three Phase 10 propagators and
the Phase 9/10 pair run in real `ThreadPoolExecutor`s. `FaultInjectingOps`
must be thread-safe (an internal lock around the routing-table match-and-
consume, since `FaultRule.times` decrements shared state) — this is new work
relative to today's single-threaded closures, several of which are not
safe to share across the pool workers a Phase 10 test spins up. The existing
Phase 10 concurrency tests (`test_phase10_propagate_runs_concurrently`,
`test_phases_9_10_run_concurrently`) already prove the *pattern* works with
today's simpler fakes; the harness generalizes it.

**Timeouts.** `FaultRule.raises = subprocess.TimeoutExpired(cmd=..., timeout=N)`
covers the "this subprocess hangs" class directly — no real sleep needed, and
it exercises the exact exception type `_run` raises on a genuine wedge,
against the exact `except subprocess.TimeoutExpired` handlers already in
`release.py`, `phase06_ci_wait.py`, and `ci_run.py`.

### 2d. What remains genuinely out of reach (name it, don't fake it)

Some failure modes are not worth simulating because faking them would test
the fake, not the release engine:

- **Actual GitHub API rate limiting / auth expiry mid-run.** The engine's
  behavior on "gh returns a 401" is already exercised via a scripted non-zero
  exit + stderr text (§2a covers this). What is out of reach is *timing* —
  whether an hours-long release genuinely hits a token expiry — and that is
  an operational/monitoring concern, not a unit-test concern.
- **PyPI's actual propagation delay** (publish succeeds, index takes minutes
  to reflect it). Phase 8/11's PyPI checks are already designed around this
  (`--no-cache --reinstall` forces an index query) — the harness can simulate
  "index query fails" via a scripted `uv pip install --dry-run` non-zero
  exit, but cannot simulate "PyPI's own eventual-consistency window," because
  that is a property of PyPI's infrastructure, not of this codebase.
- **Real hook latency** (`bd hooks run` against a networked Dolt server,
  which is why `GIT_HOOK = 600` exists). The harness can and should test that
  the *timeout budget* is applied to the right call sites (there is already
  `test_hook_firing_git_calls_do_not_use_default_timeout` doing exactly
  this) — but cannot usefully simulate "Dolt is slow today" beyond asserting
  the budget, because the actual latency is exogenous.

## 3. Fault-injection matrix

Coverage legend: **✅ Covered today** (a passing test in `tests/test_release.py`
already exercises this exact failure mode) · **🔧 Enabled by harness** (no
test exists today; §2's primitives make it straightforward to add, sized into
a wave in §5) · **⛔ Out of scope** (§2d — not worth simulating, with
rationale).

| # | Phase | Failure mode | Test scenario | Status |
|---|-------|--------------|----------------|--------|
| 1 | 1 Preflight | Dirty working tree / untracked files | `test_preflight_fails_dirty_tree`, `_fails_untracked_file` | ✅ |
| 2 | 1 Preflight | Wrong branch | `test_preflight_fails_wrong_branch` | ✅ |
| 3 | 1 Preflight | `git fetch origin` fails (network) | `fetch.returncode != 0` path in code; no test forcing a non-zero fetch | 🔧 |
| 4 | 1 Preflight | Empty `[Unreleased]` section | `test_preflight_fails_empty_unreleased` | ✅ |
| 5 | 1 Preflight | `make check` fails (quality gate) | `test_preflight_python_make_check_failure_aborts_phase` | ✅ |
| 6 | 1 Preflight | Quality-gate subprocess itself times out (hangs, not fails) | no test — `ops.run(..., timeout=QUALITY_GATE)` raising `TimeoutExpired` is unexercised at this call site | 🔧 |
| 7 | 1 Preflight | Sibling repo present but on wrong branch / dirty | `test_validate_sibling_fails_wrong_branch`, `_fails_dirty` | ✅ |
| 8 | 1 Preflight | Stale prior tag (name still `-dev`, or version mismatch) | `test_preflight_warns_when_prior_tag_still_carries_dev_name`, `_version_mismatches` | ✅ |
| 9 | 2 Version bump | Bundled template pin points at a different package | `test_template_pin_unrelated_package_untouched` | ✅ |
| 10 | 2 Version bump | Commit accidentally sweeps untracked files | `test_version_bump_commit_excludes_untracked` | ✅ |
| 11 | 2 Version bump | Go project: version resolved from tags, not pyproject | `test_get_project_version_go_unaffected`, `test_get_latest_tag_version` | ✅ |
| 11a | 2 Version bump | `_get_project_version` falls back to `plugin.json` for plugin-only projects (pkit-f85t.1) | `test_get_project_version_plugin_only_reads_plugin_json` | ✅ |
| 12 | 3 Build | `uv build`/`twine check` failure | no dedicated test found for phase 3 build failure path | 🔧 |
| 13 | 4 Release PR | Commit fails mid-plugin-swap (hook rejects), retry must consult HEAD not working tree | code comment documents the failure mode explicitly (phase04_release_pr.py:65-74); no test forces a failed commit and asserts the HEAD-consult retry | 🔧 |
| 14 | 4 Release PR | Existing PR: OPEN / stale MERGED / CLOSED selection | `test_select_existing_pr_*` (5 tests), `test_pr_merge_ignores_closed_pr_creates_fresh`, `_stale_merged_pr_not_treated_as_current`, `_matching_merged_pr_short_circuits` | ✅ |
| 15 | 4 Release PR | Branch deletion 404 after auto-delete-head-branches | `test_pr_merge_branch_deletion_404_is_success` | ✅ |
| 16 | 4 Release PR | Genuine merge failure (not the 404 case) | `test_pr_merge_real_merge_failure_still_fails` | ✅ |
| 17 | 4 Release PR | Squash-merge blocked by transient policy, retries 1–5 succeed | not exercised — no test drives `merge_attempt` past 0 | 🔧 |
| 18 | 4 Release PR | Squash-merge blocked, all 6 attempts exhausted (real failure) | not exercised | 🔧 |
| 19 | 4 Release PR | Thread-resolution fails mid-retry (best-effort re-resolve swallows error) | `except (ReleaseError, SystemExit, CalledProcessError)` at pr_merge.py:269 has no covering test | 🔧 |
| 20 | 5 Tag | Tag push fails / tag already exists at different commit | no dedicated Phase 5 failure test found | 🔧 |
| 20a | 5 Tag | Resume after a local-tag-created/push-failed partial state (defect #8) | `Phase5Tag.run` (phase05_tag.py:57-79) creates the local tag *before* pushing it; if `push()` then fails, the tag is left at HEAD locally. A later `--resume-from tag` re-enters `run()`, finds the tag already exists and already points at HEAD, logs "already exists", and returns — the push never retries. No test asserts this state today, and the code has no fix yet: this is not just a coverage gap, the resume path is genuinely wrong | 🔧 |
| 21 | 6 CI wait | `release.yml` missing for hybrid/CLI project | `test_phase6_fails_actionably_when_python_project_missing_release_yml`, `_hybrid_missing_release_yml_still_fails` | ✅ |
| 21a | 6 CI wait | CI wait skips for pure-plugin projects with no `release.yml` (pkit-f85t.2) | `test_phase6_skips_for_pure_plugin_without_release_yml` | ✅ |
| 22 | 6 CI wait | No run found / stale run / late-arriving run / wrong branch-event-commit | `test_phase6_fails_on_stale_success_with_no_matching_run` + 7 sibling tests | ✅ |
| 23 | 6 CI wait | `gh run list` hung, malformed, wrong-shaped JSON | `test_phase6_survives_unparseable_gh_output`, `_survives_wrong_shaped_gh_json`, `_treats_a_hung_run_list_as_a_failed_lookup` | ✅ |
| 24 | 6 CI wait | `gh run watch` exits non-zero but the run is actually healthy/unreachable | `test_phase6_does_not_call_an_unreachable_run_a_ci_failure`, `_still_reports_a_genuine_ci_failure_as_one` | ✅ |
| 25 | 6 CI wait | `gh run watch` outlasts `CI_WATCH` (pypi approval gate pending) | `test_phase6_timeout_explains_itself_instead_of_raising` | ✅ |
| 26 | 6 CI wait | Required-checks GraphQL: null rollup, malformed shape, 5-consecutive-error abort, ruleset vs. legacy protection, no-checks grace window | 12+ tests under `test_wait_for_required_checks_*` and `test_has_ruleset_*` | ✅ |
| 27 | 6 CI wait | SIGINT while blocked in `RequiredChecksWaiter.wait` (worker thread) | `test_wait_for_required_checks_stops_promptly_when_interrupted` | ✅ |
| 28 | 7 GitHub release | Release notes extraction for a missing version | `test_extract_version_notes_missing` | ✅ |
| 29 | 7 GitHub release | `gh release create` itself fails (network/permission) | no dedicated test found | 🔧 |
| 30 | 8 Verify PyPI | Published version present / absent on index | `test_phase11_verify_pypi_present_passes` / `_absent_fails` (Phase 11's equivalent check; Phase 8 itself has no isolated failure test) | ✅ (11) / 🔧 (8) |
| 31 | 8 Verify PyPI | `uv pip install --dry-run` hangs (index unreachable) | no test forces a `TimeoutExpired` at this call site | 🔧 |
| 32 | 9 Post-release | Restore script's committed-but-partial state (hook rejects commit) | code comment documents the exact failure (`phase09_post_release.py:88-97`); no test forces a failed restore commit and asserts the HEAD-consult retry | 🔧 |
| 33 | 9 Post-release | No post-release changes needed (idempotent short-circuit) | `test_phase09_post_release_commit_never_marks_skip_ci`, resume tests | ✅ |
| 34 | 9/10 concurrent | Both phases fail simultaneously, both errors surfaced | `test_phases_9_10_both_fail_reports_both` | ✅ |
| 35 | 9/10 concurrent | One phase raises `SystemExit`, must still cross the thread boundary as a diagnosed failure | `test_phases_9_10_p9_systemexit_propagates` | ✅ |
| 36 | 9/10 concurrent | SIGINT during the `ThreadPoolExecutor.__exit__` join (the DES-029 incident itself) | `test_run_release_reports_incomplete_release_on_interrupt` — covers the *reporting* path; does not reproduce the original two-hour-join mechanism because `RequiredChecksWaiter` already checks `interrupted` | ✅ (post-fix) |
| 37 | 10 Propagate | `.github` sibling absent (workspace meta-repo case) | `test_propagate_install_all_skips_when_github_absent` | ✅ |
| 38 | 10 Propagate | `install-all.sh` present in sibling but missing the project's entry | `test_propagate_install_all_fails_when_install_all_missing` | ✅ |
| 39 | 10 Propagate | Marketplace matching by short name vs. URL, with/without `.git` | `test_propagate_marketplace_matches_by_marketplace_short_name`, `_matches_url_with_and_without_git_suffix` | ✅ |
| 40 | 10 Propagate | No marketplace entry matches any candidate | `test_propagate_marketplace_fails_when_no_entry_matches_any_candidate` | ✅ |
| 41 | 10 Propagate | Website sibling/entry absent (optional propagator) | `test_propagate_website_skipped_when_missing` | ✅ |
| 42 | 10 Propagate | Profile README pin repaired after a stale prior release | `test_propagate_install_all_repairs_stale_profile` | ✅ |
| 43 | 10 Propagate | Sibling left on a `propagate/v*` branch by a prior interrupt | `test_reset_propagation_siblings_resets_propagation_branch` | ✅ |
| 44 | 10 Propagate | Sibling left with a dirty *owned* file (write-before-merge residue) | `test_reset_propagation_siblings_restores_dirty_owned_file`, `_mixed_dirt_preserves_unrelated` | ✅ |
| 45 | 10 Propagate | Sibling on a genuine feature branch — must NOT be touched | `test_reset_propagation_siblings_skips_feature_branches` | ✅ |
| 46 | 10 Propagate | Checkout-to-main fails inside `merge_in_sibling`'s `finally` (secondary failure during cleanup) | code path exists (pr_merge.py:329-350, logs `info` only, no hard fail, nothing recorded in `SkipRecorder`); no test | 🔧 |
| 47 | 10 Propagate | `_sync_profile_readme`'s `git log` call uses `check=True` (default) — a failure raises raw `CalledProcessError`, not a diagnosed `ReleaseError` | no test forces this call to fail | 🔧 |
| 48 | 10 Propagate | SIGINT mid-propagation, siblings mid-write | `test_run_release_reports_incomplete_release_on_interrupt` covers reporting; no test asserts `reset_propagation_siblings(fail_on_error=False)` actually restores a specific owned-file residue in the *interrupt* path specifically (as opposed to the next-run auto-recovery path, #43/#44 above) | 🔧 |
| 49 | 11 Verify | Every one of the 8 checks, pass and fail, including SHA-resolves-but-not-ancestor for both install-all.sh and profile SHA | 20+ tests, exhaustively covering `pkit-9n6q` | ✅ |
| 50 | 11 Verify | `git merge-base --is-ancestor` itself errors (exit ≥128, missing ref) vs. returns "not an ancestor" (exit 1) | `test_phase11_verify_install_all_sha_fails_when_not_ancestor_of_tag` covers exit 1; the ≥128 branch (`ancestor.returncode != 0` after excluding 1) has no dedicated test | 🔧 |
| 51 | 11 Verify | Marketplace-pin chain for marketplace-only plugins (no `install.sh`) | `test_phase11_verify_profile_sha_marketplace_chain_*` (4 tests) | ✅ |
| 52 | 11 Verify | All 8 checks running against a hybrid/CLI project (not plugin) with `install.sh` present but no `plugin.json` | implied by existing python-project tests; not isolated as its own scenario | 🔧 |
| 53 | All phases | `--resume-from` at every one of the 11 valid names, from a state where the phase-being-resumed-from is genuinely incomplete | `test_phase_names_cover_all_phases`, `test_phase_name_round_trips_through_phase_names`, plus scattered per-phase resume tests (`test_phase4_resumes_when_prior_swap_staged_but_uncommitted`, `test_phase9_resumes_when_prior_restore_staged_but_uncommitted`) — not exhaustive across all 11 | 🔧 (partial) |
| 54 | All phases | `subprocess.TimeoutExpired` at a call site that forgot to opt into a named timeout budget (falls through to `DEFAULT_RUN = 60`) | `test_run_default_timeout_is_short`, `test_git_hook_timeout_exceeds_beads_hook_ceiling`, `test_hook_firing_git_calls_do_not_use_default_timeout` verify the *budgets themselves*; no test forces an actual 60s-default timeout to fire and checks the diagnosis message end-to-end | 🔧 |
| 55 | All phases (Go) | Go-specific `make check`/`go vet`/`go test -race` failure paths | `test_go_dry_run_no_side_effects` covers the dry-run path only; no Go quality-gate-failure test parallel to the Python one (#5) | 🔧 |
| 56 | Cross-cutting | Real GitHub API rate limiting / token expiry timing during an hours-long release | N/A | ⛔ — operational concern, not unit-testable; §2d |
| 57 | Cross-cutting | PyPI eventual-consistency window after a genuine publish | N/A | ⛔ — exogenous to this codebase; §2d |
| 58 | Cross-cutting | Real `bd hooks run` / Dolt server latency variance | `test_git_hook_timeout_exceeds_beads_hook_ceiling` asserts the *budget*; the real latency is exogenous | ⛔ — §2d |

**Coverage counts (recounted directly against the table above):** 61 rows
total — 37 rows ✅ covered today, 21 rows 🔧 enabled-by-harness (the delivery
plan in §5 sequences these), 3 rows ⛔ out of scope with stated rationale.
Only **row 30** is an actual ✅/🔧 split (`✅ (11) / 🔧 (8)` — Phase 11's PyPI
check is covered, Phase 8's own isolated check is not); it is tallied once,
under 🔧, since Phase 8 itself is the gap. **Row 53** is not a split — its
status is a single `🔧 (partial)` cell (some phases have a resume test,
none is exhaustive across all 11), tallied under 🔧 directly. **Row 36** (the
DES-029 mechanism) carries a `✅ (post-fix)` qualifier and is tallied under
✅, since the reporting path it names is genuinely covered — Wave 3 targets
reproducing the *original* mechanism, a distinct scenario from what row 36
already covers, and does not change row 36's own status.

## 4. Known phase-logic defect inventory

These are read from the code directly (§ marks the file:line), cross-checked
against `CHANGELOG.md` and `DESIGN.md` to confirm none duplicate an
already-fixed defect. Ranked by severity: **P0** (silent wrong-state / data
loss risk), **P1** (loud failure but with a worse diagnosis than the
existing bar), **P2** (inconsistency/hardening, no known live incident yet).

1. **P1 — Three independent `time.sleep` seams, only one injectable (§1d).**
   `phases/shared/pr_merge.py`'s 6-attempt squash-merge retry loop
   (`merge_attempt` range, `wait = 10 * (attempt + 1)`) has **no test
   covering attempts 2 through 6** — confirmed by grep, zero hits for
   `merge_attempt` outside the source file. If the retry logic itself has a
   bug at attempt 3+ (off-by-one in the wait formula, the re-resolve-threads
   exception swallow at line 269 masking a real failure), nothing today would
   catch it. This is exactly the shape of every prior incident: an
   unexercised branch that only executes under a real, rare production
   condition (a merge blocked long enough to need a 4th+ retry).

2. **P1 — `merge_in_sibling`'s cleanup `finally` block degrades to an info
   log on a secondary failure (pr_merge.py:329-350).** If `merge()` raises
   (the primary failure, correctly propagated) and the subsequent "return
   sibling to main" checkout *also* fails, the code path only calls
   `self._ops.info(f"Warning: could not return sibling {name} to main: ...")`
   — not `SkipRecorder.record`, not a hard fail. The primary exception still
   propagates (so the release does fail overall), but the secondary failure
   — "and by the way, this sibling is now in an even worse state than the
   primary failure alone would suggest" — is not in the end-of-run
   "Manual action required" recap `ReleasePipeline.print_manual_actions`
   drains. An operator fixing the primary failure and re-running has no
   signal that the sibling needs closer inspection than usual. Recommend:
   route this specific secondary-failure branch through `SkipRecorder` — but
   note the plumbing is not free. `SkipRecorder` (`_skips` in release.py) is
   injected into `Phase10Propagate` and `InstallAllPropagator` directly;
   `PrMerger` (`phases/shared/pr_merge.py`) takes only `ops` at construction
   (`__new__(cls, *, ops: ReleaseOps)`), and `_sibling_pr_merge`
   (release.py:491-505) constructs `PrMerger(ops=_ops)` with no recorder in
   reach. The fix has to add an optional `skips: SkipRecorder | None = None`
   parameter to `PrMerger.__new__` and pass `_skips` at the one call site
   that needs it (`_sibling_pr_merge`); `_pr_merge` (release.py:356-366,
   backing Phase 4's own release-PR merge, which has no sibling-recording
   concept) keeps constructing `PrMerger(ops=_ops)` with the default `None`.
   `merge_in_sibling`'s `finally` block then calls `self._skips.record(...)`
   when a recorder is present and falls back to today's `self._ops.info(...)`
   when it is not.

3. **P1 — Inconsistent error-diagnosis quality across subprocess call
   sites.** Most `ops.run(...)` call sites either pass `check=False` and
   build a specific `ops.fail(...)` message, or accept the propagating
   `ReleaseError`. A few — e.g. `InstallAllPropagator._sync_profile_readme`'s
   `git log -1 --format=%h -- install-all.sh` (phase10_propagate.py:171-174)
   — use the default `check=True` with no surrounding message. A failure
   there raises a raw `subprocess.CalledProcessError`, which
   `ThreadedStep.collect`'s catch-all `except BaseException as e` does
   correctly catch and report (so it is not silent), but the message an
   operator sees is `CalledProcessError`'s default repr instead of a
   diagnosis naming what the release engine was trying to do. This is a
   hardening gap, not a correctness bug — but it is exactly the class of gap
   that turns a 30-second diagnosis into a 10-minute one during an actual
   incident.

4. **P2 — `RequiredChecksWaiter.wait`'s hard-coded 7200s deadline
   (gh.py:208) duplicates `timeouts.CI_WATCH` instead of importing it.**
   `phase06_ci_wait.py` imports and uses `CI_WATCH` from
   `phases/shared/timeouts.py` for its own `gh run watch` budget; `gh.py`'s
   `RequiredChecksWaiter.wait` computes `deadline = time.time() + 7200`
   inline rather than `+ CI_WATCH`. The two values happen to agree today
   (both 7200), but nothing enforces that agreement — a future change to
   `CI_WATCH` (e.g. shortening it because the PyPI approval gate moves) would
   silently leave `RequiredChecksWaiter`'s PR-check wait at the old value.
   Low severity today because the values match; flagged because it is
   exactly the kind of drift the harness's contract-testing philosophy (§2b)
   argues against, applied to internal constants rather than external tool
   output.

5. **P2 — Phase 3 (Build) and Phase 5 (Tag) have no isolated failure-path
   tests.** Both are short phase classes (69 and 79 lines respectively) with
   comparatively simple logic, which is presumably why they were not
   prioritized during the incidents that built out the rest of the suite —
   but "simple" is not the same as "exercised." Phase 5 in particular writes
   a git tag and pushes it; a failure mode worth a named test is "tag push
   succeeds locally but the remote already has a tag of the same name
   pointing at a different commit" (the exact residue `TagRunSelector`'s
   `matches()` docstring already describes handling on the *reading* side —
   nothing tests the *writing* side that would produce that residue).

6. **P2 — No isolated Phase 7 (github-release) or Phase 8
   (verify-pypi)-as-its-own-phase failure test.** Phase 11's equivalent PyPI
   check (`test_phase11_verify_pypi_present_passes`/`_absent_fails`) is well
   covered, but Phase 8 itself — which runs earlier, right after PyPI
   publish, specifically to catch the just-published version not yet being
   resolvable — has no dedicated test forcing its own `ops.run(...)` to fail
   or hang. Given Phase 8 and Phase 11's PyPI check share near-identical
   logic (`uv pip install --dry-run --no-deps --no-cache --reinstall`), this
   is lower risk than it would be for two independently-implemented checks,
   but the two are not tested via a shared helper, so a future edit to one
   could silently diverge from the other with nothing to notice.

7. **P2 — No test exhaustively drives `--resume-from` for all 11 phase
   names against a genuinely-incomplete state at that phase.**
   `test_phase_names_cover_all_phases` and
   `test_phase_name_round_trips_through_phase_names` (`tests/test_release.py`)
   already iterate the imported `PHASE_NAMES` mapping directly — not a `bd`
   command; `PHASE_NAMES` is `release.py`'s own module-level dict — and a
   handful of individual phases have their own resume test. Nothing
   parametrizes "start the pipeline fresh,
   kill it after phase N completes, then run `--resume-from
   <phase-N+1's-name>` and assert the run picks up cleanly" across all 11
   phases in one sweep. This is precisely the shape of test the harness's
   `FaultInjectingOps` + `interrupt_after` helpers (§2c) make cheap to write
   as one parametrized test instead of eleven bespoke ones.

8. **P0 — Phase 5's local-tag-before-push ordering makes `--resume-from tag`
   silently skip the retry it exists to enable (matrix row 20a).**
   `Phase5Tag.run` (phase05_tag.py:57-79) creates the git tag locally
   (`git tag {tag}`) *before* pushing it (`workspace.push(tag)`). If the
   push fails — network blip, transient auth failure, anything —
   `git tag` already succeeded, so the tag sits at HEAD locally while the
   remote has nothing. The exception from the failed push propagates and
   the release run stops, per design; the problem is what happens next.
   Re-running with `--resume-from tag` re-enters `Phase5Tag.run`, which
   checks `git tag --list {tag}` first (line 57), finds it, confirms
   `tag_sha == head_sha` (line 64), logs "Tag {tag} already exists at HEAD"
   (line 65), and returns — `workspace.push(tag)` is never called. The
   release proceeds to Phase 6 waiting on a CI run for a tag that was never
   pushed, and CI wait times out or reports "no run found" with no signal
   that the real cause is an unpushed local tag. This is a P0, not a P2 like
   defect #5's general "Phase 5 is thin" observation, because it is a
   correctness bug in the resume path specifically, not just a coverage
   gap: the existing-tag branch needs to distinguish "exists locally and
   was already pushed" from "exists locally and was never pushed" (e.g. by
   also checking `git ls-remote origin {tag}` or by pushing unconditionally
   when the tag was just created in this same run) before it is safe to
   short-circuit. **Flagged here as a defect candidate for the epic; no bead
   ID assigned by this document — filing is the leader's call.**

## 5. Incremental delivery plan

Each wave is sized to be one implementation mission — a bounded write-set,
one worker/evaluator pair, landable independently, and each wave's tests pass
`make check` on their own before the next wave starts.

### Wave 0 — Harness primitives (foundation, no new test scenarios)

Deliverable: `tests/harness/fault_ops.py` (`FaultRule`, `FaultInjectingOps`,
`interrupt_after`, the blocking-rule mechanism for Wave 3), plus a thin
`tests/harness/__init__.py`. Migrate **zero** existing tests in this wave —
the goal is landing the primitive with its own unit tests, including as
explicit acceptance criteria:

- `argv[0]` matching compares `Path(argv[0]).name`, not exact string equality
  — a rule with `match=["gh", ...]` matches a real `shutil.which("gh")`
  absolute path.
- an unmatched `git` command still delegates to real `_run` (§1b preserved);
  an unmatched `gh` command (not in `passthrough`) raises `AssertionError`
  rather than silently reaching the network (the deny-by-default posture).
- `skip`/`times`-bounded rules correctly select the Nth match, not just the
  first.
- a `responses` sequence returns one value per consumed match, in order.
- injected exceptions (`raises`) propagate correctly.
- the routing table stays correct under concurrent `.run()` calls from a
  `ThreadPoolExecutor` (an internal lock around match-and-consume).
- `interrupt_after` fires exactly when its anchoring rule match completes,
  not before and not on an unrelated call.

Sized deliberately small so the primitive itself gets scrutinized before
anything depends on it.

### Wave 1 — Recorded-fixture library + contract tests (§2b)

Deliverable: `tools/record_gh_fixtures.py` (manual recording script, not run
in CI), an initial `tests/fixtures/gh/*.json` set covering the shapes rows
21–27 and 39–40 of the matrix already exercise informally, and
`tests/test_gh_fixture_contracts.py` asserting shape agreement between each
fixture and the production parsing code's expectations. No release-engine
source changes. This wave is independent of Wave 0 and could run in
parallel, but is sequenced second because reviewing it benefits from Wave 0's
`FaultRule.from_fixture` hook already existing to show the intended
consumer.

### Wave 2 — Retry-loop and cleanup-path coverage (matrix rows 17–19, 46)

Deliverable: tests for `PrMerger.merge`'s full 6-attempt retry loop
(transient-block-then-succeed at attempts 2–5, exhaustion at attempt 6, the
thread-re-resolve exception swallow at line 269), plus the
`merge_in_sibling` `finally`-block secondary-failure path (matrix row 46 /
defect #2), plus injecting `pr_merge.py`'s `time.sleep` seam (per
`ci_run.py`'s injectable-callable pattern, or a documented monkeypatch
target) so the retry tests don't consume real wall-clock. This wave pairs
naturally with fixing defect #2 (route the secondary failure through
`SkipRecorder`) since the fix and its regression test are the same unit of
work — one implementation mission, not two. Per defect #2's plumbing note
above, this includes adding the optional `skips: SkipRecorder | None = None`
parameter to `PrMerger.__new__` and threading `_skips` through
`_sibling_pr_merge`'s `PrMerger(...)` construction — that plumbing is part of
Wave 2's write-set, not a separate step. The fixes this wave carries are
filed as explicit beads: **pkit-f85t.6** (SkipRecorder routing for
`merge_in_sibling`'s secondary cleanup failure — defect #2) and
**pkit-f85t.8** (`gh.py` imports `CI_WATCH` instead of hardcoding 7200, with
a constant-derivation test — defect #4).

### Wave 3 — SIGINT/concurrency scenarios (matrix rows 36, 48)

Deliverable: tests reproducing the DES-029 mechanism directly, using both
Wave 0 primitives per §2c's split — `interrupt_after` for the
observation-ordering cases, and the blocking-`FaultRule` mechanism for the
mechanism DES-029 actually hit: a Phase 10 propagator's `gh` call is a
scripted blocking rule, the test thread sets `_interrupted` while that call
is still blocked, and the assertion is that `ThreadPoolExecutor.__exit__`
returns promptly rather than waiting out the join, with
`reset_propagation_siblings(fail_on_error=False)` running against the exact
residue state — rather than only the post-fix reporting path the current
suite covers. This wave depends on both Wave 0 primitives and should not
start before they land.

### Wave 4 — Thin-phase coverage (matrix rows 3, 6, 12, 20, 20a, 29, 31, 55, defects #5–6)

Deliverable: the isolated failure-path tests for Phases 3, 5, 7, 8 that §4
identifies as missing, plus the Go quality-gate failure test parallel to the
existing Python one, plus a forced-timeout test for the `DEFAULT_RUN`
fallback case (matrix row 54), plus the **pkit-f85t.7** sweep (defect #3:
convert call sites leaking raw `CalledProcessError` to `check=False` with a
diagnosed `ops.fail` message). These are independent of each other and can
be split across two workers if scheduling favors parallelism, but are
grouped into one wave here because each is small (one or two tests per
phase) and none has a design dependency on Waves 1–3.

Matrix row 20a (defect #8, the Phase 5 resume-skips-the-retry bug) is **not**
a same-shape item as the rest of this wave — it is a P0 correctness fix, not
only a coverage gap, and its regression test and its fix are one unit of
work (same pattern as Wave 2 pairing defect #2's fix with its test). It is
listed in this wave's scope because it shares Phase 5 with row 20's other
coverage work, not because it is equally low-risk; the worker for this wave
should treat 20a as the first item, not an afterthought, once a bead exists
for it.

### Wave 5 — Exhaustive resume-point sweep (matrix row 53, defect #7)

Deliverable: one parametrized test driving `run_release` fresh, interrupting
after each of the 11 phases in turn (via Wave 0's `interrupt_after`), and
asserting `--resume-from <name>` completes cleanly from that exact state, for
all 11 names. Sequenced last because it is the highest-value integration
test but also the one most likely to surface interactions the earlier,
narrower waves would have caught first at lower cost — landing it last means
any failure it finds is more likely to point at a genuine gap rather than a
harness bug.

### Epic reconciliation

The DoltDB recovered after this design was drafted, and the plan has been
reconciled against the epic: all 7 original `pkit-f85t` children are closed
(fixed in earlier waves), the harness is the epic's remaining shared
deliverable, this design's own defect findings are filed as pkit-f85t.5–.8
(carried by Waves 2 and 4 above), and no child conflicts with this plan.
Defect #8 (Phase 5's resume bug, added in a later review round) still needs
its own bead filed before Wave 4 can carry it as more than a coverage item —
flagged for the epic owner, not assigned an ID by this document.
