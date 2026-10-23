"""Classify a concrete argv as one that may run git hooks, and size its timeout."""

from __future__ import annotations

from pathlib import PurePath
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Sequence

# git subcommands that provably run no hook: they read, or touch only the index,
# tags, branches and remotes. Everything else is assumed to fire one, so a verb
# nobody listed (a new git subcommand, a user alias) gets the long budget rather
# than the short one. Over-approximating only lengthens a ceiling.
_GIT_QUIET_VERBS = frozenset(
    {
        "add",
        "blame",
        "branch",
        "cat-file",
        "check-ignore",
        "config",
        "describe",
        "diff",
        "diff-index",
        "diff-tree",
        "fetch",
        "for-each-ref",
        "grep",
        "help",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "remote",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "symbolic-ref",
        "tag",
        "var",
        "version",
    }
)

# git options that sit before the verb and take it from the next word
# (``-C dir``); every other leading ``-`` word is a flag or ``--opt=value``.
_GIT_VALUE_OPTIONS = frozenset(
    {
        "-C",
        "-c",
        "--attr-source",
        "--config-env",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
)

# gh options that sit before the command and take the next word as a value.
_GH_VALUE_OPTIONS = frozenset({"-R", "--repo", "--hostname"})

# gh runs local git for these, whatever else is on the line:
#   pr checkout / co   git fetch + git checkout of the PR branch
#   repo sync          git fetch + merge into the local branch
#   repo clone         git clone, with post-checkout in the new tree
_GH_ALWAYS = frozenset(
    {("pr", "checkout"), ("pr", "co"), ("repo", "sync"), ("repo", "clone")}
)

# gh runs local git for these only when one of the flags is given. A long flag
# matches with or without ``=value``; a short one matches inside a cluster such
# as ``-sd``.
#   pr merge -d              after the API merge: checkout base, delete branch, pull
#   issue develop -c         git fetch + git checkout of the new branch
#   repo fork --clone        git clone of the fork
#   repo create --push/-c    git push of the source / git clone of the new repo
_GH_WITH_FLAG: dict[tuple[str, str], frozenset[str]] = {
    ("pr", "merge"): frozenset({"--delete-branch", "-d"}),
    ("issue", "develop"): frozenset({"--checkout", "-c"}),
    ("repo", "fork"): frozenset({"--clone"}),
    ("repo", "create"): frozenset({"--push", "--clone", "-c"}),
}

# ``gh pr create`` pushes the head branch unless ``--head`` names one that is
# already pushed, in which case gh runs only read-only git.
_GH_UNLESS_FLAG: dict[tuple[str, str], frozenset[str]] = {
    ("pr", "create"): frozenset({"--head", "-H"})
}

# gh commands that never run local git: API calls and remote-only objects.
_GH_QUIET_COMMANDS = frozenset(
    {
        "api",
        "auth",
        "browse",
        "cache",
        "config",
        "help",
        "label",
        "release",
        "ruleset",
        "run",
        "search",
        "secret",
        "status",
        "variable",
        "workflow",
    }
)
_GH_QUIET_ACTIONS = frozenset(
    {
        "checks",
        "close",
        "comment",
        "diff",
        "edit",
        "list",
        "lock",
        "ready",
        "reopen",
        "review",
        "status",
        "unlock",
        "view",
    }
)
_GH_QUIET_GROUPS = frozenset({"pr", "issue", "repo"})

# Programs that run another program given on their own command line. One is
# hook-firing when any word of its line names git, gh or a shell.
_WRAPPERS = frozenset(
    {
        "command",
        "doas",
        "env",
        "exec",
        "ionice",
        "nice",
        "nohup",
        "setsid",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
        "uv",
        "uvx",
        "xargs",
    }
)
_SHELLS = frozenset({"ash", "bash", "dash", "fish", "ksh", "sh", "zsh"})
_GIT_LIKE = frozenset({"git", "gh"}) | _SHELLS


@final
class HookFiringCommand:
    """One concrete argv, classified by whether it may run a git hook.

    Every punt-labs repo installs beads hooks that call a networked Dolt
    server, so a command that fires one needs ``GIT_HOOK``, not the 60s
    metadata default. The argv is read as the runtime sees it, never guessed
    from source. When it cannot be read with confidence the answer is
    ``True``: a wrong ``True`` lengthens a ceiling, a wrong ``False`` aborts a
    release.
    """

    __slots__ = ("_argv",)

    _argv: tuple[str, ...]

    def __new__(cls, argv: Sequence[str]) -> Self:
        self = super().__new__(cls)
        self._argv = tuple(argv)
        return self

    def fires_hooks(self) -> bool:
        """True unless the argv is provably a command that runs no hook."""
        if not self._argv:
            return True
        binary = PurePath(self._argv[0]).name
        rest = self._argv[1:]
        if binary == "git":
            return self._git_fires(rest)
        if binary == "gh":
            return self._gh_fires(rest)
        if binary in _SHELLS or binary.endswith(".sh"):
            return True
        if binary in _WRAPPERS:
            return self._names_git(rest)
        return False

    def timeout(self, requested: int) -> int:
        """``requested``, raised to the hook budget when this command may fire one."""
        return max(requested, GIT_HOOK) if self.fires_hooks() else requested

    @staticmethod
    def _git_fires(words: Sequence[str]) -> bool:
        index = 0
        while index < len(words):
            word = words[index]
            if word in _GIT_VALUE_OPTIONS:
                index += 2
            elif word.startswith("-"):
                index += 1
            else:
                return word not in _GIT_QUIET_VERBS
        return True

    @classmethod
    def _gh_fires(cls, words: Sequence[str]) -> bool:
        positional, given = cls._gh_split(words)
        if not positional:
            return True
        group = positional[0]
        action = positional[1] if len(positional) > 1 else ""
        command = (group, action)
        if group in _GH_QUIET_COMMANDS:
            return False
        if command in _GH_ALWAYS:
            return True
        if command in _GH_WITH_FLAG:
            return bool(given & _GH_WITH_FLAG[command])
        if command in _GH_UNLESS_FLAG:
            return not given & _GH_UNLESS_FLAG[command]
        return not (group in _GH_QUIET_GROUPS and action in _GH_QUIET_ACTIONS)

    @staticmethod
    def _gh_split(words: Sequence[str]) -> tuple[list[str], set[str]]:
        """The command words and the flags given, a cluster split into its letters."""
        positional: list[str] = []
        given: set[str] = set()
        index = 0
        while index < len(words):
            word = words[index]
            index += 1
            if word in _GH_VALUE_OPTIONS:
                index += 1
            elif word.startswith("--"):
                given.add(word.split("=", 1)[0])
            elif word.startswith("-"):
                given.update(f"-{letter}" for letter in word[1:])
            else:
                positional.append(word)
        return positional, given

    @staticmethod
    def _names_git(words: Sequence[str]) -> bool:
        # Split on whitespace too: ``env -S "git push"`` is one word.
        return any(
            PurePath(token).name in _GIT_LIKE
            for word in words
            for token in word.split()
        )
