"""Classify a concrete argv as one that may run git hooks, and size its timeout."""

from __future__ import annotations

from pathlib import PurePath
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Sequence

# git subcommands that provably run no hook. Per githooks, a hook can fire when
# git updates a ref (reference-transaction), writes or refreshes the index
# (post-index-change), consults fsmonitor (fsmonitor-watchman), or runs
# `gc --auto` (pre-auto-gc). So a quiet verb only reads the object database or
# the refs, and never touches the index or the working tree:
#   rev-parse, rev-list, merge-base, name-rev   read commits and refs
#   log, show, shortlog, cat-file, ls-tree      read objects; no index, no tree
#   show-ref, for-each-ref                      read refs
#   ls-remote                                   reads the remote's refs; updates none
#   config, var, version, help                  settings and static text
# Left out on purpose: fetch, remote, tag, branch, symbolic-ref (ref updates);
# add, status, diff, ls-files (index); describe (`--dirty` refreshes the index);
# grep and blame (read the working tree). Everything else, including a verb
# nobody listed, is assumed to fire, so it gets the long budget; over-
# approximating only lengthens a ceiling.
_GIT_QUIET_VERBS = frozenset(
    {
        "cat-file",
        "config",
        "for-each-ref",
        "help",
        "log",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
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
#   repo fork --clone/--remote  git clone of the fork / adds the remote and fetches
#   pr close -d              may check out the default branch before deleting
#   repo create --push/-c    git push of the source / git clone of the new repo
_GH_WITH_FLAG: dict[tuple[str, str], frozenset[str]] = {
    ("pr", "merge"): frozenset({"--delete-branch", "-d"}),
    ("issue", "develop"): frozenset({"--checkout", "-c"}),
    ("repo", "fork"): frozenset({"--clone", "--remote"}),
    ("pr", "close"): frozenset({"--delete-branch", "-d"}),
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
_GH_READ_AND_EDIT_ACTIONS = frozenset(
    {
        "checks",
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
# ``pr close`` is not here: with ``--delete-branch`` it may check out the
# default branch, so it is flag-gated above. ``issue close`` runs no git.
_GH_QUIET_ACTIONS: dict[str, frozenset[str]] = {
    "pr": _GH_READ_AND_EDIT_ACTIONS,
    "issue": _GH_READ_AND_EDIT_ACTIONS | {"close"},
    "repo": _GH_READ_AND_EDIT_ACTIONS,
}

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
    release. That covers git, gh, shells and wrappers of them. A program that is
    none of those (``make``, ``uv build``, ``go``) is quiet by design: it is not
    assumed to run git, and a script that does must be run through a shell.
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
            return self._splits_a_string(rest) or self._names_git(rest)
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
        return action not in _GH_QUIET_ACTIONS.get(group, frozenset())

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
    def _splits_a_string(words: Sequence[str]) -> bool:
        """True for ``env -S`` / ``--split-string`` in any form, attached or not.

        The string it carries is a command line, and any short-option cluster
        holding ``S`` (``-iSgit``) may carry one, so these are over-approximated.
        """
        return any(
            word.startswith("--split-string")
            or (word.startswith("-") and not word.startswith("--") and "S" in word)
            for word in words
        )

    @staticmethod
    def _names_git(words: Sequence[str]) -> bool:
        # Split on whitespace too: ``env -S "git push"`` is one word.
        return any(
            PurePath(token).name in _GIT_LIKE
            for word in words
            for token in word.split()
        )
