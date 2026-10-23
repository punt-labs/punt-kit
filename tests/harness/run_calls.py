"""Static reading of the release code's process-running ``.run(...)`` calls."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
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
    def is_runner(self) -> bool:
        """True when this call runs a process: a runner receiver or an argv list."""
        receiver = self.receiver
        return (
            (isinstance(receiver, ast.Name) and receiver.id in _RUNNER_NAMES)
            or (isinstance(receiver, ast.Attribute) and receiver.attr == "_ops")
            or isinstance(self._argv, ast.List | ast.Tuple)
        )

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
        return [
            elt.value
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            else None
            for elt in argv.elts
        ]

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
    def is_readable(self) -> bool:
        """True when the audits can tell what the call runs.

        A git argv is readable only if its verb is; any other list is a
        command the audits classify by its first word.
        """
        if self.words is None:
            return False
        return not self.is_git or self.git_verb is not None

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
