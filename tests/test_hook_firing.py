"""Tests for the classifier that decides which commands get the hook budget."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.hook_firing import HookFiringCommand


def _fires(*argv: str) -> bool:
    return HookFiringCommand(list(argv)).fires_hooks()


@pytest.mark.parametrize(
    "verb",
    [
        "checkout",
        "switch",
        "commit",
        "merge",
        "rebase",
        "reset",
        "cherry-pick",
        "push",
        "pull",
        "am",
        "clone",
        "revert",
        "stash",
        "worktree",
        "restore",
        "submodule",
        "gc",
        "fetch",
        "add",
        "status",
        "diff",
        "ls-files",
        "symbolic-ref",
        "describe",
        "grep",
        "blame",
    ],
)
def test_git_verbs_that_run_hooks_fire_them(verb: str) -> None:
    assert _fires("git", verb)


@pytest.mark.parametrize(
    "verb",
    [
        "rev-parse",
        "log",
        "show",
        "cat-file",
        "ls-remote",
        "rev-list",
        "config",
        "var",
        "version",
        "help",
        "merge-base",
        "name-rev",
        "show-ref",
        "for-each-ref",
        "ls-tree",
        "shortlog",
    ],
)
def test_read_only_git_verbs_run_no_hook(verb: str) -> None:
    assert not _fires("git", verb)


def test_a_git_verb_nobody_listed_is_assumed_to_fire_hooks() -> None:
    assert _fires("git", "frobnicate")


def test_a_bare_git_is_assumed_to_fire_hooks() -> None:
    assert _fires("git")


def test_an_empty_argv_is_assumed_to_fire_hooks() -> None:
    assert HookFiringCommand([]).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["git", "-C", "/repo", "push"], id="dash-C"),
        pytest.param(["git", "-c", "k=v", "-C", "/r", "commit"], id="C-and-c"),
        pytest.param(["git", "--no-pager", "checkout"], id="no-pager"),
        pytest.param(["git", "--git-dir=x", "pull"], id="git-dir-equals"),
        pytest.param(["git", "--git-dir", "x", "merge"], id="git-dir-space"),
        pytest.param(["git", "--work-tree", "x", "-C", "d", "reset"], id="work-tree"),
        pytest.param(["git", "--namespace", "ns", "push"], id="namespace"),
        pytest.param(["git", "-p", "--bare", "push"], id="flags"),
        pytest.param(["/usr/bin/git", "push"], id="absolute-path"),
        pytest.param(["./bin/git", "-C", "d", "push"], id="relative-path"),
    ],
)
def test_git_global_options_do_not_hide_the_verb(argv: list[str]) -> None:
    assert HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["git", "-C", "push", "log"], id="dash-C-value-is-a-path"),
        pytest.param(["git", "-c", "alias.x=push", "log"], id="dash-c-value"),
        pytest.param(["git", "--git-dir", "commit", "show"], id="git-dir-value"),
    ],
)
def test_a_global_option_value_is_not_mistaken_for_the_verb(argv: list[str]) -> None:
    assert not HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["gh", "pr", "checkout", "7"], id="pr-checkout"),
        pytest.param(["gh", "pr", "co", "7"], id="pr-co"),
        pytest.param(["gh", "repo", "sync"], id="repo-sync"),
        pytest.param(["gh", "repo", "clone", "o/r"], id="repo-clone"),
        pytest.param(["gh", "repo", "fork", "--clone"], id="fork-clone"),
        pytest.param(["gh", "repo", "fork", "--clone=true"], id="fork-clone-equals"),
        pytest.param(["gh", "repo", "create", "r", "--push"], id="create-push"),
        pytest.param(["gh", "repo", "create", "r", "-c"], id="create-c"),
        pytest.param(["gh", "issue", "develop", "3", "-c"], id="develop-c"),
        pytest.param(["gh", "issue", "develop", "3", "--checkout"], id="develop-long"),
        pytest.param(["gh", "issue", "develop", "3", "-cb", "x"], id="develop-cb"),
        pytest.param(["gh", "pr", "merge", "1", "--delete-branch"], id="merge-long"),
        pytest.param(["gh", "pr", "merge", "1", "--delete-branch=true"], id="merge-eq"),
        pytest.param(["gh", "pr", "merge", "1", "-d"], id="merge-d"),
        pytest.param(["gh", "pr", "merge", "1", "-sd"], id="merge-sd"),
        pytest.param(["gh", "pr", "merge", "1", "-ds"], id="merge-ds"),
        pytest.param(["gh", "pr", "merge", "1", "-sdm"], id="merge-mid-cluster"),
        pytest.param(["gh", "pr", "create", "--title", "t"], id="create-no-head"),
        pytest.param(["gh", "-R", "o/r", "pr", "checkout", "1"], id="dash-R"),
        pytest.param(["gh", "--repo", "o/r", "pr", "merge", "1", "-sd"], id="repo-opt"),
        pytest.param(["/usr/local/bin/gh", "pr", "co", "1"], id="absolute-path"),
        pytest.param(["gh", "pr", "close", "1", "-d"], id="pr-close-d"),
        pytest.param(["gh", "pr", "close", "1", "--delete-branch"], id="close-long"),
        pytest.param(["gh", "repo", "fork", "--remote"], id="fork-remote"),
        pytest.param(["gh", "repo", "fork", "--remote=true"], id="fork-remote-eq"),
        pytest.param(["gh", "frobnicate", "now"], id="unknown-command"),
        pytest.param(["gh"], id="bare-gh"),
    ],
)
def test_gh_commands_that_run_local_git_fire_hooks(argv: list[str]) -> None:
    assert HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["gh", "api", "graphql", "-f", "query=x"], id="api"),
        pytest.param(["gh", "pr", "view", "7", "--json", "state"], id="pr-view"),
        pytest.param(["gh", "pr", "merge", "1", "--squash"], id="merge-no-delete"),
        pytest.param(["gh", "pr", "merge", "1", "-s"], id="merge-short-no-delete"),
        pytest.param(["gh", "pr", "create", "--head", "b"], id="create-head"),
        pytest.param(["gh", "pr", "create", "-H", "b"], id="create-H"),
        pytest.param(["gh", "issue", "develop", "3", "-l"], id="develop-list"),
        pytest.param(["gh", "pr", "close", "1"], id="pr-close-keeps-branch"),
        pytest.param(["gh", "issue", "close", "3"], id="issue-close"),
        pytest.param(["gh", "repo", "fork"], id="fork-plain"),
        pytest.param(["gh", "run", "watch", "9", "--exit-status"], id="run-watch"),
        pytest.param(["gh", "run", "view", "9"], id="run-view"),
        pytest.param(["gh", "release", "create", "v1"], id="release-create"),
        pytest.param(["gh", "-R", "o/r", "pr", "view", "7"], id="dash-R-view"),
    ],
)
def test_gh_commands_that_run_no_git_run_no_hook(argv: list[str]) -> None:
    assert not HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["env", "git", "push"], id="env-git"),
        pytest.param(["env", "FOO=1", "git", "push"], id="env-assignment"),
        pytest.param(["env", "-i", "/usr/bin/git", "push"], id="env-path"),
        pytest.param(["env", "-S", "git push"], id="env-S-string"),
        pytest.param(["env", "gh", "pr", "co", "1"], id="env-gh"),
        pytest.param(["env", "env", "git", "push"], id="nested-env"),
        pytest.param(["env", "-Sgit push"], id="env-S-attached"),
        pytest.param(["env", "--split-string=git push"], id="env-split-string-eq"),
        pytest.param(["env", "--split-string", "git push"], id="env-split-string"),
        pytest.param(["env", "-iSgit push"], id="env-S-in-cluster"),
        pytest.param(["timeout", "30", "git", "push"], id="timeout"),
        pytest.param(["nohup", "git", "commit"], id="nohup"),
        pytest.param(["xargs", "git", "checkout"], id="xargs"),
        pytest.param(["sh", "-c", "git push"], id="sh-c"),
        pytest.param(["bash", "-c", "git push"], id="bash-c"),
        pytest.param(["/bin/bash", "-lc", "git push"], id="bash-lc"),
        pytest.param(["bash", "scripts/release-plugin.sh"], id="bash-script"),
        pytest.param(["zsh", "-c", "git push"], id="zsh"),
        pytest.param(["scripts/restore-dev-plugin.sh"], id="script-run-directly"),
        pytest.param(["uv", "run", "git", "push"], id="uv-run-git"),
    ],
)
def test_wrappers_around_git_are_assumed_to_fire_hooks(argv: list[str]) -> None:
    assert HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["make", "check"], id="make"),
        pytest.param(["uv", "build"], id="uv-build"),
        pytest.param(["uvx", "twine", "check", "dist/x.whl"], id="uvx"),
        pytest.param(["go", "test", "./..."], id="go"),
        pytest.param(["env", "FOO=1", "make", "check"], id="env-make"),
        pytest.param(["/usr/bin/punt", "doctor"], id="punt"),
        pytest.param(["some-unlisted-tool", "git-like"], id="unknown-program"),
    ],
)
def test_other_programs_are_not_assumed_to_fire_hooks(argv: list[str]) -> None:
    assert not HookFiringCommand(argv).fires_hooks()


def test_a_hook_firing_command_gets_the_hook_budget_as_a_floor() -> None:
    command = HookFiringCommand(["git", "push"])
    assert command.timeout(timeouts.DEFAULT_RUN) == timeouts.GIT_HOOK


def test_a_longer_budget_than_the_floor_is_kept() -> None:
    command = HookFiringCommand(["git", "push"])
    assert command.timeout(timeouts.QUALITY_GATE) == timeouts.QUALITY_GATE


def test_the_hook_budget_itself_is_unchanged() -> None:
    command = HookFiringCommand(["git", "push"])
    assert command.timeout(timeouts.GIT_HOOK) == timeouts.GIT_HOOK


def test_a_command_that_fires_no_hook_keeps_its_budget() -> None:
    command = HookFiringCommand(["git", "rev-parse", "HEAD"])
    assert command.timeout(timeouts.DEFAULT_RUN) == timeouts.DEFAULT_RUN


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["git", "branch", "--show-current"], id="show-current"),
        pytest.param(["git", "branch"], id="bare-branch"),
        pytest.param(["git", "branch", "--list"], id="list"),
        pytest.param(["git", "branch", "-l"], id="short-list"),
        pytest.param(["git", "branch", "-a"], id="all"),
        pytest.param(["git", "branch", "-r"], id="remotes"),
        pytest.param(["git", "branch", "-vv"], id="verbose-cluster"),
        pytest.param(["git", "branch", "--format=%(refname)"], id="format-equals"),
        pytest.param(["git", "branch", "--contains", "abc1234"], id="contains"),
        pytest.param(["git", "branch", "--merged", "main"], id="merged"),
        pytest.param(["git", "-C", "/repo", "branch", "--show-current"], id="dash-C"),
        pytest.param(["git", "tag"], id="bare-tag"),
        pytest.param(["git", "tag", "-l"], id="tag-l"),
        pytest.param(["git", "tag", "--list"], id="tag-list"),
        pytest.param(["git", "tag", "--points-at", "HEAD"], id="points-at"),
        pytest.param(["git", "tag", "--contains", "abc1234"], id="tag-contains"),
        pytest.param(["git", "tag", "--format=%(tag)"], id="tag-format"),
        pytest.param(["git", "tag", "--sort=-creatordate"], id="tag-sort"),
        pytest.param(["git", "remote"], id="bare-remote"),
        pytest.param(["git", "remote", "-v"], id="remote-v"),
        pytest.param(["git", "remote", "get-url", "origin"], id="get-url"),
        pytest.param(
            ["git", "remote", "get-url", "--push", "origin"], id="get-url-push"
        ),
    ],
)
def test_read_only_forms_of_ref_commands_run_no_hook(argv: list[str]) -> None:
    assert not HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["git", "branch", "newbranch"], id="create"),
        pytest.param(["git", "branch", "-d", "old"], id="delete"),
        pytest.param(["git", "branch", "-D", "old"], id="force-delete"),
        pytest.param(["git", "branch", "-m", "a", "b"], id="rename"),
        pytest.param(["git", "branch", "--list", "pattern"], id="list-with-positional"),
        pytest.param(["git", "branch", "--set-upstream-to=origin/main"], id="upstream"),
        pytest.param(["git", "branch", "--contains", "abc", "extra"], id="extra-word"),
        pytest.param(["git", "tag", "v1"], id="tag-create"),
        pytest.param(["git", "tag", "-a", "v1", "-m", "x"], id="annotated"),
        pytest.param(["git", "tag", "-d", "v1"], id="tag-delete"),
        pytest.param(["git", "tag", "-f", "v1"], id="tag-force"),
        pytest.param(["git", "tag", "-l", "v*"], id="tag-list-with-pattern"),
        pytest.param(["git", "remote", "add", "x", "url"], id="remote-add"),
        pytest.param(["git", "remote", "remove", "x"], id="remote-remove"),
        pytest.param(["git", "remote", "set-url", "origin", "u"], id="set-url"),
        pytest.param(["git", "remote", "update"], id="remote-update"),
        pytest.param(["git", "remote", "prune", "origin"], id="remote-prune"),
        pytest.param(["git", "status"], id="status"),
        pytest.param(["git", "diff"], id="diff"),
        pytest.param(["git", "ls-files"], id="ls-files"),
    ],
)
def test_writing_forms_and_index_readers_still_fire_hooks(argv: list[str]) -> None:
    assert HookFiringCommand(argv).fires_hooks()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["env", "FOO=1", "scripts/release-plugin.sh"], id="env-script"),
        pytest.param(["timeout", "30", "./restore-dev-plugin.sh"], id="timeout-script"),
        pytest.param(["uv", "run", "scripts/x.sh"], id="uv-run-script"),
        pytest.param(["nohup", "/abs/path/x.sh", "arg"], id="nohup-script"),
    ],
)
def test_a_wrapper_running_a_shell_script_is_assumed_to_fire_hooks(
    argv: list[str],
) -> None:
    assert HookFiringCommand(argv).fires_hooks()
