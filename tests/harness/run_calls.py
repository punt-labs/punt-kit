"""Static reading of the release code's process-running ``.run(...)`` calls."""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# Verbs that run git hooks (the beads hooks reach a networked Dolt server), so
# a command using one needs the hook budget rather than the 60s default.
HOOK_FIRING_VERBS = frozenset(
    {
        "checkout",
        "cherry-pick",
        "commit",
        "merge",
        "pull",
        "push",
        "rebase",
        "reset",
        "switch",
    }
)

# Git options that sit before the verb and take their value as the next word
# (``-C dir``); every other leading ``-`` word is a flag or ``--opt=value``.
_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}
)

# gh options that sit before the subcommand and take the next word as a value.
_GH_VALUE_OPTIONS = frozenset({"-R", "--repo", "--hostname"})

# gh commands with no action word (``gh api <endpoint>``); every other gh
# command is ``gh <group> <action>``.
_GH_SINGLE_LEVEL = frozenset(
    {"api", "auth", "browse", "search", "status", "alias", "config", "help"}
)

# gh commands that run local git, and so fire the bd hooks. Each is stated here
# because gh, not this code, runs the git:
#   pr checkout / co     git fetch + git checkout of the PR branch
#   repo sync            git fetch + merge into the local branch
#   repo clone           git clone (post-checkout in the new tree)
#   pr merge -d          after the API merge: checkout base, delete branch, pull
#   issue develop -c     git fetch + git checkout of the new branch
#   pr create            git push of the head branch, unless --head names a
#                        branch that is already pushed (gh then skips the push)
_GH_ALWAYS: frozenset[tuple[str, ...]] = frozenset(
    {("pr", "checkout"), ("pr", "co"), ("repo", "sync"), ("repo", "clone")}
)
_GH_WITH_FLAG: dict[tuple[str, ...], frozenset[str]] = {
    ("pr", "merge"): frozenset({"--delete-branch", "-d"}),
    ("issue", "develop"): frozenset({"--checkout", "-c"}),
}
_GH_UNLESS_FLAG: dict[tuple[str, ...], frozenset[str]] = {
    ("pr", "create"): frozenset({"--head", "-H"})
}

# Variables the release code binds to the gh and git executables; any other
# non-constant argv[0] is an unknown binary.
_BINARY_VARIABLES = {"gh": "gh", "git": "git"}

# Constructors whose `.run(...)` is a release phase or propagator, not a
# process. The set is closed: any other constructed receiver is audited.
_PHASE_OBJECT = re.compile(r"Phase\d+\w*|\w+Propagator|MarketplacePinCheck")

# `.run(` receivers that are a process runner: a ReleaseOps (``ops``,
# ``self._ops``) or the subprocess module.
_RUNNER_NAMES = frozenset({"ops", "subprocess"})


@dataclass(frozen=True, slots=True)
class RunCall:
    """One ``<receiver>.run(...)`` call, with where it sits in its file."""

    file: str
    function: str
    ordinal: int
    node: ast.Call

    @classmethod
    def collect(cls, files: Iterable[Path]) -> list[Self]:
        """Every ``.run(`` call in ``files``, in source order."""
        calls: list[Self] = []
        for path in files:
            calls.extend(cls.collect_source(path.name, path.read_text("utf-8")))
        return calls

    @classmethod
    def collect_source(cls, file: str, source: str) -> list[Self]:
        """Every ``.run(`` call in one module's ``source``.

        ``ordinal`` counts calls with the same argv text inside one function,
        so two calls that look alike get distinct identities.
        """
        seen: Counter[tuple[str, str]] = Counter()
        calls: list[Self] = []
        for function, node in _walk(ast.parse(source), ""):
            argv = ast.unparse(node.args[0]) if node.args else ""
            calls.append(cls(file, function, seen[function, argv], node))
            seen[function, argv] += 1
        return calls

    @property
    def line(self) -> int:
        return self.node.lineno

    @property
    def receiver(self) -> ast.expr:
        return cast("ast.Attribute", self.node.func).value

    @property
    def argv_text(self) -> str:
        """The first positional argument as source, ``""`` when there is none."""
        return ast.unparse(self.node.args[0]) if self.node.args else ""

    @property
    def identity(self) -> tuple[str, str, str, int]:
        """File, enclosing function, argv expression, and ordinal."""
        return (self.file, self.function, self.argv_text, self.ordinal)

    @property
    def is_phase_object(self) -> bool:
        """True for ``Phase3Build(...).run(...)`` and the other phase objects."""
        receiver = self.receiver
        return (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and _PHASE_OBJECT.fullmatch(receiver.func.id) is not None
        )

    @property
    def is_runner(self) -> bool:
        """True when this call runs a process.

        A runner receiver, an argv list, or a constructed receiver that is not
        a phase object and is given an argument (``Adapter().run(cmd)``).
        """
        receiver = self.receiver
        if isinstance(self._argv, ast.List | ast.Tuple):
            return True
        if isinstance(receiver, ast.Name):
            return receiver.id in _RUNNER_NAMES
        if isinstance(receiver, ast.Attribute):
            return receiver.attr == "_ops"
        return bool(self.node.args) and not self.is_phase_object

    @property
    def words(self) -> list[str | None] | None:
        """The argv as words (``None`` for a non-constant element).

        ``None`` overall means the argv is not a list the audits can read: a
        variable, a call, or any list with a ``*`` element anywhere (it could
        splice in a hook-firing verb).
        """
        argv = self._argv
        if not isinstance(argv, ast.List | ast.Tuple):
            return None
        if any(isinstance(elt, ast.Starred) for elt in argv.elts):
            return None
        words = [
            elt.value
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            else None
            for elt in argv.elts
        ]
        if words:
            # The binary: a path names it by basename; a variable the release
            # code binds to gh or git stands for it.
            first = argv.elts[0]
            if words[0] is not None:
                words[0] = PurePath(words[0]).name
            elif isinstance(first, ast.Name):
                words[0] = _BINARY_VARIABLES.get(first.id)
        return words

    @property
    def is_git(self) -> bool:
        words = self.words
        return words is not None and words[:1] == ["git"]

    @property
    def git_verb(self) -> str | None:
        """The git subcommand, skipping global options; ``None`` if not git.

        Also ``None`` when the verb is not a string constant, which callers
        treat as unreadable.
        """
        words = self.words
        if words is None or words[:1] != ["git"]:
            return None
        index = 1
        while index < len(words):
            word = words[index]
            if word is None:
                return None
            if word in _VALUE_OPTIONS:
                index += 2
            elif word.startswith("-"):
                index += 1
            else:
                return word
        return None

    @property
    def is_gh(self) -> bool:
        words = self.words
        return words is not None and words[:1] == ["gh"]

    @property
    def gh_command(self) -> tuple[tuple[str, ...], frozenset[str]] | None:
        """The gh command words and the flags given; ``None`` if not gh or unclear.

        Skips gh's leading ``-R repo`` style options. A command is ``(group,)``
        for ``gh api`` and the like, else ``(group, action)``.
        """
        words = self.words
        if words is None or words[:1] != ["gh"]:
            return None
        positional: list[str | None] = []
        flags: set[str] = set()
        index = 1
        while index < len(words):
            word = words[index]
            if word in _GH_VALUE_OPTIONS:
                index += 2
                continue
            if word is not None and word.startswith("-"):
                flags.add(word.split("=", 1)[0])
            else:
                positional.append(word)
            index += 1
        group = positional[0] if positional else None
        if group is None:
            return None
        if group in _GH_SINGLE_LEVEL:
            return (group,), frozenset(flags)
        action = positional[1] if len(positional) > 1 else None
        return ((group, action), frozenset(flags)) if action else None

    @property
    def is_readable(self) -> bool:
        """True when the audits can tell what the call runs.

        The argv must be a list whose binary is a constant or a variable the
        release code binds to gh or git. A git argv also needs a constant verb,
        and a gh argv a constant command.
        """
        words = self.words
        if words is None or not words or words[0] is None:
            return False
        if self.is_git:
            return self.git_verb is not None
        return not self.is_gh or self.gh_command is not None

    @property
    def fires_hooks(self) -> bool:
        """True when the command runs hook-firing git, directly or through gh."""
        if self.is_git:
            return self.git_verb in HOOK_FIRING_VERBS
        parsed = self.gh_command
        if parsed is None:
            return False
        command, flags = parsed
        if command in _GH_ALWAYS:
            return True
        if command in _GH_WITH_FLAG:
            return bool(flags & _GH_WITH_FLAG[command])
        if command in _GH_UNLESS_FLAG:
            return not flags & _GH_UNLESS_FLAG[command]
        return False

    @property
    def timeout_budget(self) -> str | None:
        """The identifier passed as ``timeout=`` (``timeouts.GIT_HOOK`` -> GIT_HOOK)."""
        for kw in self.node.keywords:
            if kw.arg != "timeout":
                continue
            if isinstance(kw.value, ast.Name):
                return kw.value.id
            if isinstance(kw.value, ast.Attribute):
                return kw.value.attr
            return "<non-name expression>"
        return None

    @property
    def _argv(self) -> ast.expr | None:
        return self.node.args[0] if self.node.args else None


def _walk(tree: ast.AST, scope: str) -> Iterable[tuple[str, ast.Call]]:
    """Yield ``(enclosing function qualname, call)`` for every ``.run(`` call."""
    for child in ast.iter_child_nodes(tree):
        inner = scope
        if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            inner = f"{scope}.{child.name}" if scope else child.name
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "run"
        ):
            yield scope or "<module>", child
        yield from _walk(child, inner)
