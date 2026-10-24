"""Contract tests: the recorded ``gh`` fixture library vs. the real parsers.

Every test here drives
the *actual production collaborator* (``GithubRepo``, ``RequiredChecksWaiter``,
``TagRunSelector``, ``PrMerger``, ``PrThreadResolver``, ``CiRunWatch``) against
a fixture's raw ``stdout`` via ``FaultInjectingOps`` and asserts on what that
real code extracts — never a hand-maintained mirror of ``gh``'s shapes. A
parsing change with no matching fixture update, or a fixture that no longer
matches what the parser expects, fails here; a live ``gh`` CLI shape change
that this static, committed library has not yet observed is caught by
``tools/record_gh_fixtures.py --check`` instead, never by this
file — this file is offline and runs on every CI invocation.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from punt_kit.detect import ProjectInfo
from punt_kit.phases.phase07_github_release import Phase7GithubRelease
from punt_kit.phases.shared.ci_run import CiRunWatch, TagRunSelector
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.gh import RequiredChecksWaiter
from punt_kit.phases.shared.github_repo import GithubRepo
from punt_kit.phases.shared.pr_merge import PrMerger
from punt_kit.phases.shared.pr_threads import PrThreadResolver
from punt_kit.phases.shared.timeouts import DEFAULT_RUN
from tests.harness.fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule
from tests.harness.gh_shapes import load_gh_fixture

if TYPE_CHECKING:
    import subprocess

    from tests.harness.fault_ops import RunFn

_OWNER = "acme-org"
_REPO = "sample-repo"

# Full argv prefixes, endpoint included, so a rule answers exactly the call it
# was recorded for and nothing else that starts with ``gh api``.
_PROTECTION_ARGV = ["gh", "api", f"repos/{_OWNER}/{_REPO}/branches/main/protection"]
_RULESET_ARGV = ["gh", "api", f"repos/{_OWNER}/{_REPO}/rules/branches/main"]
_GRAPHQL_ARGV = ["gh", "api", "graphql"]


def _real_run_stub() -> RunFn:
    """No test in this file expects a real git/gh call to escape the
    fixture-driven rules — anything that does is a test setup bug, not a
    scenario to silently tolerate.
    """

    def real_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected real dispatch: {cmd!r}")

    return real_run


def _ops_with(*rules: FaultRule) -> FaultInjectingOps:
    return FaultInjectingOps(real_run=_real_run_stub(), rules=list(rules))


def _rule(prefix: list[str], fixture: str) -> FaultRule:
    return FaultRule(match=prefix, response=FaultRule.from_fixture(fixture))


def _noop_sleep(_seconds: float) -> None:
    """Patched in for ``time.sleep`` — every release-engine module
    shares one ``import time``, so patching the bare module attribute
    reaches ``gh.py``'s poll loop with no dotted per-module path needed.
    """


def _fake_which(_name: str) -> str:
    """Patched in for ``shutil.which`` — the collaborators under test
    resolve ``gh`` themselves rather than taking it as an ``ops`` call, so
    this keeps the test independent of whether a real ``gh`` binary is on
    ``PATH``, matching ``tests/test_release.py``'s own convention.
    """
    return "gh"


def _no_wait_for_checks(_gh: str, _cwd: str, _pr: int) -> None:
    """A ``wait_for_checks`` stand-in — its own behavior is covered by the
    ``RequiredChecksWaiter.wait`` tests above; ``PrMerger.merge`` tests only
    need it to be a no-op.
    """


def _no_resolve_threads(_gh: str, _cwd: str, _pr: int) -> None:
    """A ``resolve_threads`` stand-in — its own behavior is covered by the
    ``PrThreadResolver.resolve`` tests above.
    """


# ---------------------------------------------------------------------------
# GithubRepo.has_branch_protection / has_ruleset
# ---------------------------------------------------------------------------


def test_has_branch_protection_false_on_the_documented_marker(tmp_path: Path) -> None:
    ops = _ops_with(
        _rule(_PROTECTION_ARGV, "gh_api_branch_protection_not_protected.json")
    )
    repo = GithubRepo(tmp_path, ops=ops)

    assert repo.has_branch_protection("gh", _OWNER, _REPO) is False


def test_has_branch_protection_true_when_configured(tmp_path: Path) -> None:
    ops = _ops_with(_rule(_PROTECTION_ARGV, "gh_api_branch_protection_protected.json"))
    repo = GithubRepo(tmp_path, ops=ops)

    assert repo.has_branch_protection("gh", _OWNER, _REPO) is True


def test_has_branch_protection_fails_safe_on_an_ambiguous_404(tmp_path: Path) -> None:
    """A 404 without the exact 'branch not protected' marker (e.g. an
    under-scoped token on a repo that IS protected) must not be read as
    unprotected — see GithubRepo.has_branch_protection's own docstring.
    """
    ops = _ops_with(
        _rule(_PROTECTION_ARGV, "gh_api_branch_protection_ambiguous_404.json")
    )
    repo = GithubRepo(tmp_path, ops=ops)

    assert repo.has_branch_protection("gh", _OWNER, _REPO) is True


def test_has_ruleset_true_on_a_governed_repo(tmp_path: Path) -> None:
    ops = _ops_with(_rule(_RULESET_ARGV, "gh_api_rules_branches_governed.json"))
    repo = GithubRepo(tmp_path, ops=ops)

    assert repo.has_ruleset("gh", _OWNER, _REPO) is True


def test_has_ruleset_false_on_an_ungoverned_repo(tmp_path: Path) -> None:
    ops = _ops_with(_rule(_RULESET_ARGV, "gh_api_rules_branches_ungoverned.json"))
    repo = GithubRepo(tmp_path, ops=ops)

    assert repo.has_ruleset("gh", _OWNER, _REPO) is False


# ---------------------------------------------------------------------------
# RequiredChecksWaiter.wait
# ---------------------------------------------------------------------------


def _governed_rules(*graphql_rules: FaultRule) -> list[FaultRule]:
    """``RequiredChecksWaiter.wait`` always issues exactly these two ``gh
    api`` calls before ever touching GraphQL: the branch-protection read,
    then the ruleset read. Each rule names its own endpoint, so the order
    they appear in here does not matter.
    """
    return [
        _rule(_PROTECTION_ARGV, "gh_api_branch_protection_not_protected.json"),
        _rule(_RULESET_ARGV, "gh_api_rules_branches_governed.json"),
        *graphql_rules,
    ]


def test_wait_reports_success_when_every_required_check_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ops = _ops_with(
        *_governed_rules(
            _rule(["gh", "api", "graphql"], "gh_graphql_required_checks_passed.json")
        )
    )
    waiter = RequiredChecksWaiter(GithubRepo(tmp_path, ops=ops), ops=ops)

    waiter.wait(
        "gh",
        str(tmp_path),
        355,
        resolve_repo=lambda _p: f"{_OWNER}/{_REPO}",
        interrupted=threading.Event(),
    )

    out = capsys.readouterr().out
    assert "Required CI checks passed" in out
    assert "docs" in out
    assert "lint" in out
    assert "test" in out


def test_wait_raises_naming_the_failed_required_check(tmp_path: Path) -> None:
    ops = _ops_with(
        *_governed_rules(
            _rule(["gh", "api", "graphql"], "gh_graphql_required_checks_failed.json")
        )
    )
    waiter = RequiredChecksWaiter(GithubRepo(tmp_path, ops=ops), ops=ops)

    with pytest.raises(
        ReleaseError, match=r"^Required CI checks failed on PR #42: test$"
    ):
        waiter.wait(
            "gh",
            str(tmp_path),
            42,
            resolve_repo=lambda _p: f"{_OWNER}/{_REPO}",
            interrupted=threading.Event(),
        )


def test_wait_survives_a_null_rollup_then_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A freshly-opened PR's first poll or two see a null ``statusCheckRollup``
    (no CheckRun has attached to the commit yet) — the waiter must treat this
    as 'still nothing to report' and keep polling, not crash or misreport.
    """
    monkeypatch.setattr("time.sleep", _noop_sleep)
    ops = _ops_with(
        *_governed_rules(
            FaultRule(
                match=["gh", "api", "graphql"],
                times=1,
                response=FaultRule.from_fixture(
                    "gh_graphql_required_checks_null_rollup.json"
                ),
            ),
            _rule(["gh", "api", "graphql"], "gh_graphql_required_checks_passed.json"),
        )
    )
    waiter = RequiredChecksWaiter(GithubRepo(tmp_path, ops=ops), ops=ops)

    waiter.wait(
        "gh",
        str(tmp_path),
        355,
        resolve_repo=lambda _p: f"{_OWNER}/{_REPO}",
        interrupted=threading.Event(),
    )

    assert "No checks registered on the commit yet" in capsys.readouterr().out


def test_wait_survives_a_pending_check_then_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("time.sleep", _noop_sleep)
    ops = _ops_with(
        *_governed_rules(
            FaultRule(
                match=["gh", "api", "graphql"],
                times=1,
                response=FaultRule.from_fixture(
                    "gh_graphql_required_checks_pending.json"
                ),
            ),
            _rule(["gh", "api", "graphql"], "gh_graphql_required_checks_passed.json"),
        )
    )
    waiter = RequiredChecksWaiter(GithubRepo(tmp_path, ops=ops), ops=ops)

    waiter.wait(
        "gh",
        str(tmp_path),
        355,
        resolve_repo=lambda _p: f"{_OWNER}/{_REPO}",
        interrupted=threading.Event(),
    )

    assert "Waiting for: test" in capsys.readouterr().out


def test_wait_treats_ungoverned_repo_as_waiting_on_every_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No branch protection and no ruleset — every check is waited on, not
    just the ones GraphQL happens to mark ``isRequired``.

    ``gh_graphql_required_checks_mixed_conclusions.json`` is hand-authored
    (not recorded live): an earlier version sourced it from a real,
    actively-updated PR, and two different recording passes captured two
    different states of the same PR's still-churning checks — one mid-run,
    one after everything had since settled to SUCCESS — silently
    invalidating whichever claim the fixture's name made at the time. A
    permanently-fixed, hand-authored mix (SUCCESS and NEUTRAL, required and
    non-required) is the only way this fixture's own name stays true.
    """
    fixture = load_gh_fixture("gh_graphql_required_checks_mixed_conclusions.json")
    non_required_names = [
        c["name"]
        for c in json.loads(fixture["stdout"])["data"]["repository"]["pullRequest"][
            "commits"
        ]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"]
        if not c["isRequired"]
    ]
    assert non_required_names, "the fixture carries no non-required check to assert"
    ops = _ops_with(
        _rule(_PROTECTION_ARGV, "gh_api_branch_protection_not_protected.json"),
        _rule(_RULESET_ARGV, "gh_api_rules_branches_ungoverned.json"),
        _rule(_GRAPHQL_ARGV, "gh_graphql_required_checks_mixed_conclusions.json"),
    )
    waiter = RequiredChecksWaiter(GithubRepo(tmp_path, ops=ops), ops=ops)

    waiter.wait(
        "gh",
        str(tmp_path),
        349,
        resolve_repo=lambda _p: f"{_OWNER}/{_REPO}",
        interrupted=threading.Event(),
    )

    out = capsys.readouterr().out
    assert "CI checks passed" in out
    assert "Required" not in out.split("CI checks passed")[0].splitlines()[-1]
    # A non-required check is still named in the final report — every check
    # is waited on and reported when the repo is ungoverned, not just the
    # ones GraphQL happens to mark isRequired.
    assert any(name in out for name in non_required_names)


# ---------------------------------------------------------------------------
# TagRunSelector
# ---------------------------------------------------------------------------


def test_tag_run_selector_matches_and_extracts_the_recorded_run() -> None:
    envelope = load_gh_fixture("gh_run_list_matching_tag.json")
    runs = json.loads(envelope["stdout"])
    run = runs[0]
    selector = TagRunSelector(tag=run["headBranch"], commit=run["headSha"])

    assert selector.matches(run) is True
    assert selector.run_id(run) == run["databaseId"]
    assert selector.poll(lambda: runs, attempts=1, interval=0) == run["databaseId"]


def test_tag_run_selector_rejects_a_run_at_a_different_commit() -> None:
    envelope = load_gh_fixture("gh_run_list_matching_tag.json")
    runs = json.loads(envelope["stdout"])
    run = runs[0]
    selector = TagRunSelector(tag=run["headBranch"], commit="0" * 40)

    assert selector.matches(run) is False
    assert "the local tag is at" in selector.describe_misses(runs)


# ---------------------------------------------------------------------------
# CiRunWatch.failure_message
# ---------------------------------------------------------------------------


def test_ci_run_watch_reports_could_not_confirm_on_a_healthy_run(
    tmp_path: Path,
) -> None:
    ops = _ops_with(_rule(["gh", "run", "view"], "gh_run_view_success.json"))

    message = CiRunWatch(ops=ops).failure_message("gh", tmp_path, 123, 1)

    assert "could not confirm" in message


def test_ci_run_watch_reports_the_conclusion_on_a_failed_run(tmp_path: Path) -> None:
    ops = _ops_with(_rule(["gh", "run", "view"], "gh_run_view_failure.json"))

    message = CiRunWatch(ops=ops).failure_message("gh", tmp_path, 123, 1)

    assert "concluded failure" in message


# ---------------------------------------------------------------------------
# PrMerger — existing-PR selection and merged-state reads, via merge()
# ---------------------------------------------------------------------------


def _pr_list_entry(fixture: str) -> dict[str, object]:
    """The one PR entry a `gh_pr_list_*` fixture carries — read from the
    fixture itself rather than hardcoded, since these fixtures are
    recorded live and their PR number/head SHA changes on every
    re-recording pass.
    """
    ops = _ops_with(_rule(["gh", "pr", "list"], fixture))
    # Wire boundary — a fixture's decoded stdout is `object` until narrowed
    # here to the shape every `gh_pr_list_*` fixture actually has (PY-TS-14).
    prs = cast(
        "list[dict[str, object]]", json.loads(ops.run(["gh", "pr", "list"]).stdout)
    )
    assert len(prs) == 1, f"{fixture} does not carry exactly one PR entry"
    return prs[0]


_MERGE_OID = "0123456789abcdef0123456789abcdef01234567"
_OID_RESPONSE = CompletedProcessSpec(stdout=f"{_MERGE_OID}\n")
_OK = CompletedProcessSpec(returncode=0)


def _selection_ops(
    pr_list_fixture: str, local_head: str, *rules: FaultRule
) -> FaultInjectingOps:
    """The calls ``PrMerger.merge`` makes up to and after PR selection.

    Anything not scripted — notably ``gh pr create`` on a path that must
    reuse an existing PR — is a deny-by-default failure, so which branch
    ``merge()`` took is pinned by the rules a test supplies.
    """
    return _ops_with(
        FaultRule(match=["git", "push"], response=_OK),
        FaultRule(
            match=["git", "rev-parse"], response=CompletedProcessSpec(stdout=local_head)
        ),
        _rule(["gh", "pr", "list"], pr_list_fixture),
        *rules,
        FaultRule(match=["git", "checkout"], response=_OK),
        FaultRule(match=["git", "pull"], response=_OK),
    )


def _run_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ops: FaultInjectingOps
) -> tuple[str, list[int]]:
    """Drive ``PrMerger.merge``; return its oid and the PRs it waited on."""
    monkeypatch.setattr("shutil.which", _fake_which)
    waited: list[int] = []

    def record_wait(_gh: str, _cwd: str, pr: int) -> None:
        waited.append(pr)

    oid = PrMerger(ops=ops).merge(
        cwd=tmp_path,
        branch="release/v1.2.3",
        title="chore: release v1.2.3",
        wait_for_checks=record_wait,
        resolve_threads=_no_resolve_threads,
    )
    return oid, waited


def test_merge_reuses_the_open_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _pr_list_entry("gh_pr_list_open.json")
    assert entry["state"] == "OPEN"
    ops = _selection_ops(
        "gh_pr_list_open.json",
        "irrelevant",
        FaultRule(
            match=["gh", "pr", "view"],
            responses=[FaultRule.from_fixture("gh_pr_view_open.json"), _OID_RESPONSE],
        ),
        FaultRule(match=["gh", "pr", "merge"], response=_OK),
    )

    oid, waited = _run_merge(tmp_path, monkeypatch, ops)

    assert (oid, waited) == (_MERGE_OID, [entry["number"]])


def test_merge_short_circuits_on_a_merged_pr_at_its_own_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _pr_list_entry("gh_pr_list_merged.json")
    assert entry["state"] == "MERGED"
    ops = _selection_ops(
        "gh_pr_list_merged.json",
        str(entry["headRefOid"]),
        FaultRule(match=["gh", "pr", "view"], response=_OID_RESPONSE),
    )

    oid, waited = _run_merge(tmp_path, monkeypatch, ops)

    assert (oid, waited) == (_MERGE_OID, [])


@pytest.mark.parametrize(
    ("fixture", "state", "local_head"),
    [
        pytest.param(
            "gh_pr_list_merged.json", "MERGED", "0" * 40, id="merged-at-stale-head"
        ),
        pytest.param("gh_pr_list_closed.json", "CLOSED", "irrelevant", id="closed"),
        pytest.param("gh_pr_list_empty.json", None, "irrelevant", id="empty"),
    ],
)
def test_merge_creates_a_fresh_pr_when_none_is_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: str,
    state: str | None,
    local_head: str,
) -> None:
    # The fixture must actually be in the state its id claims, or this test
    # would pass for the wrong reason.
    if state is None:
        assert json.loads(load_gh_fixture(fixture)["stdout"]) == []
    else:
        entry = _pr_list_entry(fixture)
        assert entry["state"] == state
        assert entry["headRefOid"] != local_head
    ops = _selection_ops(
        fixture,
        local_head,
        _rule(["gh", "pr", "create"], "gh_pr_create_success.json"),
        FaultRule(
            match=["gh", "pr", "view"],
            responses=[FaultRule.from_fixture("gh_pr_view_merged.json"), _OID_RESPONSE],
        ),
    )

    oid, waited = _run_merge(tmp_path, monkeypatch, ops)

    # 123 is the number in gh_pr_create_success.json's URL: the existing PR
    # (if any) was not the one waited on.
    assert (oid, waited) == (_MERGE_OID, [123])


def test_merge_treats_an_open_pr_state_as_not_merged_after_a_failed_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_is_merged`` reading OPEN means a non-zero ``gh pr merge`` is a failure."""
    open_view = FaultRule.from_fixture("gh_pr_view_open.json")
    ops = _selection_ops(
        "gh_pr_list_empty.json",
        "irrelevant",
        _rule(["gh", "pr", "create"], "gh_pr_create_success.json"),
        FaultRule(match=["gh", "pr", "view"], responses=[open_view, open_view]),
        _rule(["gh", "pr", "merge"], "gh_pr_merge_real_failure.json"),
    )

    with pytest.raises(ReleaseError, match="Failed to merge PR #123"):
        _run_merge(tmp_path, monkeypatch, ops)


def test_merge_continues_when_a_failed_merge_left_the_pr_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_is_merged`` reading MERGED means the failed ``gh pr merge`` (a branch
    deletion error after the merge) still counts as a merge.
    """
    ops = _selection_ops(
        "gh_pr_list_empty.json",
        "irrelevant",
        _rule(["gh", "pr", "create"], "gh_pr_create_success.json"),
        FaultRule(
            match=["gh", "pr", "view"],
            responses=[
                FaultRule.from_fixture("gh_pr_view_open.json"),
                FaultRule.from_fixture("gh_pr_view_merged.json"),
                _OID_RESPONSE,
            ],
        ),
        _rule(["gh", "pr", "merge"], "gh_pr_merge_real_failure.json"),
    )

    oid, waited = _run_merge(tmp_path, monkeypatch, ops)

    assert (oid, waited) == (_MERGE_OID, [123])


# ---------------------------------------------------------------------------
# PrThreadResolver
# ---------------------------------------------------------------------------


def _thread_resolver_ops(*rules: FaultRule) -> FaultInjectingOps:
    """``PrThreadResolver.resolve`` opens with a real ``GithubRepo.resolve_slug()``
    git-remote lookup before ever touching ``gh`` — every scenario needs that
    one rule regardless of which threads fixture it drives.
    """
    origin_rule = FaultRule(
        match=["git", "remote", "get-url", "origin"],
        response=CompletedProcessSpec(stdout=f"git@github.com:{_OWNER}/{_REPO}.git\n"),
    )
    return _ops_with(origin_rule, *rules)


def test_pr_thread_resolver_no_op_when_nothing_unresolved(tmp_path: Path) -> None:
    ops = _thread_resolver_ops(
        _rule(["gh", "api", "graphql"], "gh_graphql_pr_threads_none_unresolved.json")
    )
    resolver = PrThreadResolver(GithubRepo(tmp_path, ops=ops), ops=ops)

    resolver.resolve("gh", str(tmp_path), 355)  # must not raise, must not mutate


def test_pr_thread_resolver_no_op_when_pr_has_no_threads_at_all(tmp_path: Path) -> None:
    """A PR with no Copilot/Bugbot review posted yet — ``reviewThreads.nodes``
    is an empty array rather than absent entirely.
    """
    ops = _thread_resolver_ops(
        _rule(["gh", "api", "graphql"], "gh_graphql_pr_threads_empty.json")
    )
    resolver = PrThreadResolver(GithubRepo(tmp_path, ops=ops), ops=ops)

    resolver.resolve("gh", str(tmp_path), 42)  # must not raise, must not mutate


def test_pr_thread_resolver_resolves_the_recorded_unresolved_thread(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = _rule(["gh", "api", "graphql"], "gh_graphql_pr_threads.json")
    # The listing fixture (recorded live) has exactly one unresolved thread,
    # so the resolver issues exactly one follow-up resolution mutation —
    # scripted here as a plain success, since a mutation's outcome is never
    # something the read-only recorder can capture.
    # No ``skip`` needed: ``listing`` claims the first matching call itself
    # (its own ``times=1`` default), so this rule — later in the list —
    # only ever sees calls ``listing`` has already exhausted, i.e. the
    # follow-up mutation.
    mutation = FaultRule(
        match=["gh", "api", "graphql"],
        response=CompletedProcessSpec(returncode=0),
    )
    ops = _thread_resolver_ops(listing, mutation)
    resolver = PrThreadResolver(GithubRepo(tmp_path, ops=ops), ops=ops)

    resolver.resolve("gh", str(tmp_path), 355)

    assert "Resolved 1/1 review thread(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# PrMerger.merge — the full push-through-squash-merge path, including the
# is_transient retry classification the two gh_pr_merge_*.json fixtures
# exist specifically to validate (mutation-outcome shapes are not exempt from
# validation just because they weren't captured live).
# ---------------------------------------------------------------------------


def _merge_env_ops(*merge_rules: FaultRule) -> FaultInjectingOps:
    """Every ``git``/``gh`` call ``PrMerger.merge`` issues around the
    ``gh pr merge`` retry loop itself, scripted rather than delegated to a
    real repo — matching the established convention in
    ``tests/test_release.py``'s own ``_fake_gh_run`` for exercising this
    exact call sequence.
    """
    ok = CompletedProcessSpec(returncode=0)
    return _ops_with(
        FaultRule(match=["git", "push"], response=ok, times=None),
        FaultRule(
            match=["git", "rev-parse"],
            response=CompletedProcessSpec(stdout="abc1234\n"),
            times=None,
        ),
        _rule(["gh", "pr", "list"], "gh_pr_list_empty.json"),
        _rule(["gh", "pr", "create"], "gh_pr_create_success.json"),
        FaultRule(
            match=["gh", "pr", "view"],
            response=FaultRule.from_fixture("gh_pr_view_open.json"),
            times=None,
        ),
        *merge_rules,
        FaultRule(match=["git", "checkout"], response=ok, times=None),
        FaultRule(match=["git", "pull"], response=ok, times=None),
    )


def test_merge_retries_past_a_transient_block_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", _fake_which)
    monkeypatch.setattr("time.sleep", _noop_sleep)
    ops = _merge_env_ops(
        FaultRule(
            match=["gh", "pr", "merge"],
            responses=[
                FaultRule.from_fixture("gh_pr_merge_transient_block.json"),
                CompletedProcessSpec(returncode=0),
            ],
        )
    )
    merger = PrMerger(ops=ops)

    sha = merger.merge(
        cwd=tmp_path,
        branch="release/v1.2.3",
        title="chore: release v1.2.3",
        wait_for_checks=_no_wait_for_checks,
        resolve_threads=_no_resolve_threads,
    )

    assert sha  # reached the post-merge git rev-parse, so the retry worked


def test_merge_fails_loud_on_a_genuine_merge_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gh_pr_merge_real_failure.json``'s stderr text does not match any of
    ``is_transient``'s substrings — this must fail immediately, not retry.
    """
    monkeypatch.setattr("shutil.which", _fake_which)
    ops = _merge_env_ops(_rule(["gh", "pr", "merge"], "gh_pr_merge_real_failure.json"))
    merger = PrMerger(ops=ops)

    with pytest.raises(ReleaseError, match="not mergeable"):
        merger.merge(
            cwd=tmp_path,
            branch="release/v1.2.3",
            title="chore: release v1.2.3",
            wait_for_checks=_no_wait_for_checks,
            resolve_threads=_no_resolve_threads,
        )


# ---------------------------------------------------------------------------
# Phase7GithubRelease — the already-released short-circuit and the
# create-from-changelog path, driving gh_release_view_exists.json,
# gh_release_view_missing.json, and gh_release_create_success.json.
# ---------------------------------------------------------------------------


def test_phase7_short_circuits_when_the_release_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("shutil.which", _fake_which)
    ops = _ops_with(_rule(["gh", "release", "view"], "gh_release_view_exists.json"))
    info = ProjectInfo(root=tmp_path)

    Phase7GithubRelease(info, "1.2.3", dry_run=False, ops=ops).run()

    assert "already exists" in capsys.readouterr().out


def test_phase7_creates_the_release_from_the_changelog_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("shutil.which", _fake_which)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.2.3] - 2026-01-01\n\n### Added\n\n- Something.\n"
    )
    ops = _ops_with(
        _rule(["gh", "release", "view"], "gh_release_view_missing.json"),
        _rule(["gh", "release", "create"], "gh_release_create_success.json"),
    )
    info = ProjectInfo(root=tmp_path)

    Phase7GithubRelease(info, "1.2.3", dry_run=False, ops=ops).run()

    assert "created" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# FaultRule.from_fixture against the real, committed fixture library
# ---------------------------------------------------------------------------


def test_from_fixture_reads_the_real_fixture_library_by_default() -> None:
    """``from_fixture``'s default ``fixtures_dir`` resolves to the actual
    committed library, not only a fixture a test creates inline — the
    end-to-end wiring the loader exists to provide.

    Compares against ``load_gh_fixture`` reading the same file directly,
    rather than a hardcoded PR number/SHA: ``gh_pr_list_open.json`` is
    recorded live and its content changes on every re-recording pass, so a
    literal expected value here would be exactly as fragile as the
    fixture's own real-world data — the wiring being tested doesn't depend
    on what that data currently is.
    """
    spec = FaultRule.from_fixture("gh_pr_list_open.json")
    envelope = load_gh_fixture("gh_pr_list_open.json")

    assert spec.returncode == envelope["returncode"]
    assert spec.stdout == envelope["stdout"]
    entries = json.loads(spec.stdout)
    assert len(entries) == 1
    assert entries[0]["state"] == "OPEN"


# ---------------------------------------------------------------------------
# The CI-safe version-stamp gate (the offline half of the live --check)
# ---------------------------------------------------------------------------


def _all_fixture_names() -> list[str]:
    fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "gh"
    return sorted(p.name for p in fixtures_dir.glob("*.json"))


@pytest.mark.parametrize("name", _all_fixture_names())
def test_every_fixture_carries_a_version_stamp(name: str) -> None:
    """Every envelope must record what it was recorded/authored against —
    the input the live ``--check`` drift detector and any future recording
    pass need to reason about staleness. A fixture with no stamp cannot be
    told apart from one recorded before the stamp existed at all.
    """
    meta = load_gh_fixture(name)["_meta"]

    assert meta["gh_version"], f"{name}: _meta.gh_version is empty"
    assert meta["recorded_at"], f"{name}: _meta.recorded_at is empty"
    assert isinstance(meta["hand_authored"], bool)


@pytest.mark.parametrize("name", _all_fixture_names())
def test_recorded_fixtures_carry_a_replayable_command(name: str) -> None:
    """A fixture not marked hand-authored must carry the exact command
    ``--check`` needs to replay it live — otherwise a live
    upgrade could silently drift with nothing able to notice.
    """
    meta = load_gh_fixture(name)["_meta"]
    if meta["hand_authored"]:
        pytest.skip(f"{name} is hand-authored — nothing to replay live")

    assert meta["command"], f"{name}: recorded fixture has no _meta.command"
