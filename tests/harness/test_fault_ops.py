"""Unit tests for the Wave 0 fault-injection primitives themselves.

Exercises ``FaultRule``/``FaultInjectingOps`` in isolation — no release
phase, no real git repo. Wave 0 is deliberately scoped to the primitives;
migrating ``tests/test_release.py`` scenarios onto them is a later wave.
"""

from __future__ import annotations

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.ops import ReleaseOps
from tests.harness.fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule

if TYPE_CHECKING:
    from pathlib import Path

    from tests.harness.fault_ops import RunFn


def _real_run_stub(tag: str, calls: list[list[str]] | None = None) -> RunFn:
    """A stand-in "real ``_run``" that tags its output so a test can tell a
    real-dispatch result apart from a scripted one.
    """

    def real_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=tag, stderr=""
        )

    return real_run


# ---------------------------------------------------------------------------
# Argv matching and routing
# ---------------------------------------------------------------------------


def test_match_compares_argv0_by_basename_not_exact_string() -> None:
    rule = FaultRule(
        match=["gh", "pr", "merge"], response=CompletedProcessSpec(stdout="merged")
    )
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    result = ops.run(["/usr/bin/gh", "pr", "merge"])

    assert result.stdout == "merged"


def test_unmatched_git_command_delegates_to_real_run() -> None:
    calls: list[list[str]] = []
    ops = FaultInjectingOps(real_run=_real_run_stub("real", calls), rules=[])

    result = ops.run(["git", "status", "--porcelain"])

    assert result.stdout == "real"
    assert calls == [["git", "status", "--porcelain"]]


def test_unmatched_gh_command_raises_instead_of_reaching_the_network() -> None:
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[])

    with pytest.raises(AssertionError, match="unmatched network command"):
        ops.run(["/usr/bin/gh", "pr", "list"])


def test_run_rejects_an_empty_argv() -> None:
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[])

    with pytest.raises(ValueError, match="non-empty"):
        ops.run([])


def test_passthrough_prefix_admits_only_the_declared_shape() -> None:
    """A passthrough entry is an argv PREFIX, never a bare binary name —
    sanctioning ``["gh", "--version"]`` must not sanction every other ``gh``
    invocation. Required negative test per §2a's Wave 0 acceptance list.
    """
    calls: list[list[str]] = []
    ops = FaultInjectingOps(
        real_run=_real_run_stub("real", calls),
        rules=[],
        passthrough=[["gh", "--version"]],
    )

    result = ops.run(["/usr/bin/gh", "--version"])
    assert result.stdout == "real"
    assert calls == [["/usr/bin/gh", "--version"]]

    with pytest.raises(AssertionError, match="unmatched network command"):
        ops.run(["/usr/bin/gh", "pr", "merge"])


# ---------------------------------------------------------------------------
# skip / times / responses
# ---------------------------------------------------------------------------


def test_skip_and_times_select_the_nth_match_not_the_first() -> None:
    calls: list[list[str]] = []
    rule = FaultRule(
        match=["fake", "cmd"],
        skip=2,
        times=1,
        raises=RuntimeError("third call blocked"),
    )
    ops = FaultInjectingOps(
        real_run=_real_run_stub("real", calls),
        rules=[rule],
        passthrough=[["fake", "cmd"]],
    )

    first = ops.run(["fake", "cmd"])
    second = ops.run(["fake", "cmd"])
    assert first.stdout == "real"
    assert second.stdout == "real"

    with pytest.raises(RuntimeError, match="third call blocked"):
        ops.run(["fake", "cmd"])

    fourth = ops.run(["fake", "cmd"])
    assert fourth.stdout == "real"
    assert calls == [["fake", "cmd"]] * 3


def test_responses_returns_one_value_per_match_in_order_and_times_derives() -> None:
    rule = FaultRule(
        match=["gh", "pr", "view"],
        responses=[
            CompletedProcessSpec(stdout="OPEN"),
            CompletedProcessSpec(stdout="MERGED"),
        ],
    )
    ops = FaultInjectingOps(
        real_run=_real_run_stub("real"),
        rules=[rule],
        passthrough=[["gh", "pr", "view"]],
    )

    outcomes = [ops.run(["/usr/bin/gh", "pr", "view"]).stdout for _ in range(3)]

    assert outcomes == ["OPEN", "MERGED", "real"]


def test_times_none_cycles_through_responses_for_every_remaining_match() -> None:
    rule = FaultRule(
        match=["gh", "api", "graphql"],
        times=None,
        responses=[CompletedProcessSpec(stdout="pending")],
    )
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    outcomes = [ops.run(["/usr/bin/gh", "api", "graphql"]).stdout for _ in range(5)]

    assert outcomes == ["pending"] * 5


def test_explicit_times_overrides_the_responses_length_derivation() -> None:
    rule = FaultRule(
        match=["gh", "api", "graphql"],
        times=3,
        responses=[CompletedProcessSpec(stdout="pending")],
    )
    ops = FaultInjectingOps(
        real_run=_real_run_stub("real"),
        rules=[rule],
        passthrough=[["gh", "api", "graphql"]],
    )

    outcomes = [ops.run(["/usr/bin/gh", "api", "graphql"]).stdout for _ in range(4)]

    assert outcomes == ["pending", "pending", "pending", "real"]


# ---------------------------------------------------------------------------
# Injected exceptions
# ---------------------------------------------------------------------------


def test_raises_instance_propagates_unchanged() -> None:
    boom = ValueError("boom")
    rule = FaultRule(match=["gh"], raises=boom)
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    with pytest.raises(ValueError) as excinfo:
        ops.run(["/usr/bin/gh"])

    assert excinfo.value is boom


def test_raises_keyboardinterrupt_class_is_constructed_fresh() -> None:
    rule = FaultRule(match=["gh"], raises=KeyboardInterrupt)
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    with pytest.raises(KeyboardInterrupt):
        ops.run(["/usr/bin/gh"])


def test_raises_timeout_expired_preserves_its_attributes() -> None:
    timeout_exc = subprocess.TimeoutExpired(cmd=["gh", "run", "watch"], timeout=7200)
    rule = FaultRule(match=["gh", "run", "watch"], raises=timeout_exc)
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        ops.run(["/usr/bin/gh", "run", "watch"])

    assert excinfo.value.timeout == 7200


# ---------------------------------------------------------------------------
# FaultRule construction — invalid and boundary configurations
# ---------------------------------------------------------------------------


def test_faultrule_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FaultRule(match=["gh"])
    with pytest.raises(ValueError, match="exactly one"):
        FaultRule(match=["gh"], response=CompletedProcessSpec(), raises=ValueError())


def test_faultrule_skip_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="skip"):
        FaultRule(match=["gh"], skip=-1, response=CompletedProcessSpec())


def test_faultrule_explicit_times_must_be_positive() -> None:
    with pytest.raises(ValueError, match="times"):
        FaultRule(match=["gh"], times=0, response=CompletedProcessSpec())


def test_faultrule_responses_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="responses"):
        FaultRule(match=["gh"], responses=())


def test_faultrule_match_must_be_non_empty() -> None:
    """An empty ``match`` can never match any argv — ``_matches_argv_prefix``
    rejects everything against it — so it silently builds a rule that can
    never inject its scripted outcome. Reject it at construction instead of
    letting it fail later with an unrelated deny-by-default assertion.
    """
    with pytest.raises(ValueError, match="match"):
        FaultRule(match=[], response=CompletedProcessSpec())


def test_faultrule_match_executable_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="match"):
        FaultRule(match=[""], response=CompletedProcessSpec())


def test_passthrough_prefix_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="passthrough"):
        FaultInjectingOps(real_run=_real_run_stub("real"), rules=[], passthrough=[[]])


def test_passthrough_executable_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="passthrough"):
        FaultInjectingOps(real_run=_real_run_stub("real"), rules=[], passthrough=[[""]])


# ---------------------------------------------------------------------------
# interrupt_after — rule-anchored, not a phase-boundary tool
# ---------------------------------------------------------------------------


def test_interrupt_after_fires_exactly_on_the_anchor_matches_completion() -> None:
    event = threading.Event()
    anchor = FaultRule(match=["gh", "pr", "merge"], response=CompletedProcessSpec())
    anchor.interrupt_after(event)
    unrelated = FaultRule(match=["gh", "pr", "view"], response=CompletedProcessSpec())
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[anchor, unrelated])

    assert not event.is_set()

    ops.run(["/usr/bin/gh", "pr", "view"])
    assert not event.is_set(), (
        "an unrelated rule's match must not fire the anchor's event"
    )

    ops.run(["/usr/bin/gh", "pr", "merge"])
    assert event.is_set()


def test_interrupt_after_does_not_fire_when_the_anchor_raises() -> None:
    """A raising match never "returns" — §2c fires the interrupt as a side
    effect of the matched call *returning*, so an anchored rule that raises
    must leave the event unset rather than signaling completion first.
    """
    event = threading.Event()
    anchor = FaultRule(match=["gh", "pr", "merge"], raises=RuntimeError("blocked"))
    anchor.interrupt_after(event)
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[anchor])

    with pytest.raises(RuntimeError, match="blocked"):
        ops.run(["/usr/bin/gh", "pr", "merge"])

    assert not event.is_set()


def test_interrupt_after_is_not_a_phase_boundary_tool() -> None:
    """Setting the event has no effect on the harness's own dispatch — the
    regression test for the "interrupt_after is not a general kill switch"
    correction in §2c: a phase whose call sites never check the event runs
    to completion unaffected.
    """
    event = threading.Event()
    anchor = FaultRule(
        match=["git", "push"], times=1, response=CompletedProcessSpec(stdout="pushed")
    )
    anchor.interrupt_after(event)
    calls: list[list[str]] = []
    ops = FaultInjectingOps(real_run=_real_run_stub("real", calls), rules=[anchor])

    result = ops.run(["git", "push", "origin", "v1.0.0"])
    assert result.stdout == "pushed"
    assert event.is_set()

    for _ in range(3):
        follow_up = ops.run(["git", "status"])
        assert follow_up.stdout == "real"
    assert calls == [["git", "status"]] * 3


# ---------------------------------------------------------------------------
# from_fixture
# ---------------------------------------------------------------------------


def test_from_fixture_builds_the_matching_completed_process_spec(
    tmp_path: Path,
) -> None:
    fixtures_dir = tmp_path / "gh"
    fixtures_dir.mkdir()
    envelope = {
        "cmd": ["gh", "pr", "list", "--json", "number,state"],
        "returncode": 0,
        "stdout": '[{"number": 42, "state": "OPEN"}]',
        "stderr": "",
        "_meta": {"gh_version": "gh version 2.63.0", "recorded_at": "2026-01-01"},
    }
    (fixtures_dir / "gh_pr_list_open.json").write_text(json.dumps(envelope))

    spec = FaultRule.from_fixture("gh_pr_list_open.json", fixtures_dir=fixtures_dir)

    assert spec == CompletedProcessSpec(
        returncode=0, stdout='[{"number": 42, "state": "OPEN"}]', stderr=""
    )

    rule = FaultRule(match=["gh", "pr", "list"], response=spec)
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    result = ops.run(["/usr/bin/gh", "pr", "list", "--json", "number,state"])

    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"number": 42, "state": "OPEN"}]


# ---------------------------------------------------------------------------
# ReleaseOps conformance
# ---------------------------------------------------------------------------


def test_fault_injecting_ops_satisfies_the_release_ops_protocol() -> None:
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[])

    assert isinstance(ops, ReleaseOps)


def test_report_methods_do_not_raise_and_fail_raises_release_error() -> None:
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[])

    ops.ok("all good")
    ops.info("in progress")
    ops.dry("would run")
    ops.warn("careful")

    with pytest.raises(ReleaseError, match="boom"):
        ops.fail("boom")


# ---------------------------------------------------------------------------
# Thread safety — a real ThreadPoolExecutor, not a simulated one
# ---------------------------------------------------------------------------


def test_run_blocks_on_the_routing_table_lock_until_released() -> None:
    """Deterministic proof that ``run()`` actually acquires the router's
    lock.

    A ``ThreadPoolExecutor`` stress test alone cannot distinguish "the lock
    exists and works" from "the critical section is too short for the GIL
    to ever preempt inside it in practice" — round 1's evaluation measured
    zero failures across 1000 trials with the lock removed entirely. This
    test instead holds the lock from the test thread and asserts a
    concurrent ``run()`` call is genuinely blocked until it is released,
    which fails immediately if a future refactor narrows or removes the
    lock.
    """
    rule = FaultRule(
        match=["git", "fetch"], response=CompletedProcessSpec(stdout="scripted")
    )
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    ops._lock.acquire()  # pyright: ignore[reportPrivateUsage]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ops.run, ["git", "fetch"])

            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
            assert not future.done(), (
                "run() must block while the routing-table lock is held"
            )

            ops._lock.release()  # pyright: ignore[reportPrivateUsage]
            result = future.result(timeout=5)
    finally:
        if ops._lock.locked():  # pyright: ignore[reportPrivateUsage]
            ops._lock.release()  # pyright: ignore[reportPrivateUsage]

    assert result.stdout == "scripted"


def test_times_bounded_rule_is_consumed_exactly_once_under_concurrency() -> None:
    """Secondary sanity check alongside the deterministic lock test above —
    a real ``ThreadPoolExecutor`` stress run should also observe exactly one
    winner, even though (per round 1's evaluation) this alone doesn't prove
    the lock is what enforces it.
    """
    n_workers = 16
    barrier = threading.Barrier(n_workers)
    rule = FaultRule(
        match=["git", "fetch"],
        times=1,
        response=CompletedProcessSpec(stdout="scripted"),
    )
    ops = FaultInjectingOps(real_run=_real_run_stub("real"), rules=[rule])

    def call(_: int) -> subprocess.CompletedProcess[str]:
        barrier.wait(timeout=5)
        return ops.run(["git", "fetch"])

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        results = list(pool.map(call, range(n_workers)))

    scripted = [r for r in results if r.stdout == "scripted"]
    real = [r for r in results if r.stdout == "real"]
    assert len(scripted) == 1
    assert len(real) == n_workers - 1
