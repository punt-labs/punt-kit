"""Tests for the static reader behind the hook-timeout audits."""

from __future__ import annotations

import pytest

from tests.harness.run_calls import HOOK_FIRING_VERBS, RunCall


def _only(source: str) -> RunCall:
    (call,) = RunCall.collect_source("mod.py", source)
    return call


@pytest.mark.parametrize(
    ("argv", "verb"),
    [
        pytest.param('["git", "push"]', "push", id="plain"),
        pytest.param('["git", "-C", d, "push"]', "push", id="dash-C"),
        pytest.param('["git", "-c", "k=v", "-C", d, "commit"]', "commit", id="C-and-c"),
        pytest.param('["git", "--no-pager", "checkout"]', "checkout", id="no-pager"),
        pytest.param('["git", "--git-dir=x", "pull"]', "pull", id="git-dir-equals"),
        pytest.param('["git", "--git-dir", x, "merge"]', "merge", id="git-dir-space"),
        pytest.param('["git", "--work-tree", x, "-C", d, "reset"]', "reset", id="tree"),
        pytest.param('["git", "-p", "--bare", "status"]', "status", id="flags"),
    ],
)
def test_git_verb_skips_global_options(argv: str, verb: str) -> None:
    assert _only(f"ops.run({argv})").git_verb == verb


def test_a_non_git_argv_has_no_git_verb() -> None:
    assert _only('ops.run(["gh", "pr", "merge"])').git_verb is None


def test_a_git_argv_with_a_non_constant_verb_is_unreadable() -> None:
    assert not _only('ops.run(["git", verb])').is_readable


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param('["git", "push", *extra]', id="trailing-star"),
        pytest.param('["git", *opts, "push"]', id="middle-star"),
        pytest.param('[*cmd, "push"]', id="leading-star"),
        pytest.param("cmd", id="variable"),
        pytest.param("build_argv()", id="call"),
    ],
)
def test_a_starred_or_computed_argv_is_unreadable(argv: str) -> None:
    assert not _only(f"ops.run({argv})").is_readable


def test_a_constant_argv_is_readable() -> None:
    assert _only('ops.run(["make", "check"])').is_readable


@pytest.mark.parametrize(
    "call",
    [
        pytest.param('subprocess.run(["git", "push"])', id="subprocess"),
        pytest.param('self._ops.run(["git", "push"])', id="self-ops"),
        pytest.param('Adapter().run(["git", "push"])', id="constructed-runner"),
    ],
)
def test_any_receiver_with_an_argv_list_is_a_process_run(call: str) -> None:
    found = _only(call)
    assert (found.is_runner, found.git_verb) == (True, "push")


def test_a_phase_object_run_is_not_a_process_run() -> None:
    assert not _only("Phase1Preflight(info).run()").is_runner


@pytest.mark.parametrize("verb", ["switch", "rebase", "reset", "cherry-pick"])
def test_hook_firing_verbs_include_the_history_rewriting_ones(verb: str) -> None:
    assert verb in HOOK_FIRING_VERBS


def test_two_identical_calls_in_one_function_have_distinct_identities() -> None:
    source = (
        "class C:\n"
        "    def go(self):\n"
        "        self._ops.run(gate)\n"
        "        self._ops.run(gate)\n"
    )
    first, second = RunCall.collect_source("mod.py", source)
    assert first.identity == ("mod.py", "C.go", "gate", 0)
    assert second.identity == ("mod.py", "C.go", "gate", 1)


def test_identity_names_the_enclosing_function() -> None:
    source = "def a():\n    ops.run(gate)\n\ndef b():\n    ops.run(gate)\n"
    first, second = RunCall.collect_source("mod.py", source)
    assert (first.identity[1], second.identity[1]) == ("a", "b")


def test_timeout_budget_reads_the_identifier() -> None:
    call = _only('ops.run(["git", "push"], timeout=timeouts.GIT_HOOK)')
    assert call.timeout_budget == "GIT_HOOK"


def test_timeout_budget_is_none_without_a_timeout() -> None:
    assert _only('ops.run(["git", "push"])').timeout_budget is None
