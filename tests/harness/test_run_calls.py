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


# --- argv[0]: a variable or a path to the binary must not hide the command ---


@pytest.mark.parametrize(
    "call",
    [
        pytest.param('ops.run([git, "push", "origin"])', id="git-variable"),
        pytest.param('ops.run(["/usr/bin/git", "push"])', id="absolute-git-path"),
        pytest.param('ops.run(["./bin/git", "-C", d, "push"])', id="relative-git-path"),
    ],
)
def test_git_behind_a_variable_or_a_path_is_still_a_git_push(call: str) -> None:
    found = _only(call)
    assert (found.is_readable, found.git_verb, found.fires_hooks) == (
        True,
        "push",
        True,
    )


def test_an_unknown_variable_binary_is_unreadable() -> None:
    assert not _only('ops.run([binary, "push"])').is_readable


def test_a_non_constant_binary_expression_is_unreadable() -> None:
    assert not _only('ops.run([self.git_path(), "push"])').is_readable


# --- gh subcommands that run local git ---


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param('[gh, "pr", "merge", "1", "--delete-branch"]', id="merge-delete"),
        pytest.param('[gh, "pr", "merge", "1", "-d", "--squash"]', id="merge-short-d"),
        pytest.param('[gh, "-R", repo, "pr", "merge", "1", "--delete-branch"]', id="R"),
        pytest.param('[gh, "pr", "checkout", "1"]', id="pr-checkout"),
        pytest.param('["gh", "pr", "create", "--title", t]', id="create-pushes"),
        pytest.param('[gh, "repo", "sync"]', id="repo-sync"),
        pytest.param('[gh, "repo", "clone", r]', id="repo-clone"),
        pytest.param('[gh, "issue", "develop", "1", "--checkout"]', id="develop"),
    ],
)
def test_gh_commands_that_run_local_git_fire_hooks(argv: str) -> None:
    assert _only(f"ops.run({argv})").fires_hooks


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param('[gh, "pr", "merge", "1", "--squash"]', id="merge-via-api"),
        pytest.param('[gh, "pr", "create", "--head", b, "--title", t]', id="head"),
        pytest.param('[gh, "pr", "view", "1"]', id="view"),
        pytest.param('[gh, "run", "list"]', id="run-list"),
        pytest.param('[gh, "api", "graphql"]', id="api"),
    ],
)
def test_gh_commands_that_stay_off_local_git_do_not_fire_hooks(argv: str) -> None:
    assert not _only(f"ops.run({argv})").fires_hooks


def test_a_git_verb_outside_the_hook_set_does_not_fire_hooks() -> None:
    assert not _only('ops.run(["git", "status"])').fires_hooks


# --- receivers: a constructed runner is audited unless it is a phase object ---


def test_a_constructed_receiver_given_a_variable_argv_is_a_process_run() -> None:
    found = _only("Something().run(cmd_var)")
    assert (found.is_runner, found.is_readable) == (True, False)


def test_a_constructed_phase_object_is_not_a_process_run() -> None:
    found = _only("InstallAllPropagator(info, ops=ops).run(version)")
    assert (found.is_runner, found.is_phase_object) == (False, True)


def test_an_unknown_constructed_receiver_with_no_args_is_unclassified() -> None:
    found = _only("Something().run()")
    assert (found.is_runner, found.is_phase_object) == (False, False)
