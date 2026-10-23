"""Finding and rewriting a ``name = "version"`` assignment in a source file."""

from __future__ import annotations

import re
from typing import Self, final


@final
class VersionAssignment:
    """A version assigned to ``name`` on one line, as a quoted string literal.

    The rule, shared by the Phase 2 bump and the Phase 11 check so they cannot
    disagree: the assignment starts its line, may carry a type annotation
    (``__version__: str = "1.0"``), and its value is a string in double or
    single quotes (TOML basic or literal string, Python either). The quote
    style is kept when the value is rewritten. Anything else, such as a
    computed value, an inline table or a tuple, is *assigned* but not
    *readable*: the bump must fail on it and the check must report it, never
    pass over it.
    """

    __slots__ = ("_assigned", "_quoted")

    _assigned: re.Pattern[str]
    _quoted: re.Pattern[str]

    def __new__(cls, name: str, *, lead: str = "") -> Self:
        self = super().__new__(cls)
        head = rf"^{lead}{re.escape(name)}(?:\s*:[^=\n]+)?\s*="
        self._assigned = re.compile(head, re.MULTILINE)
        self._quoted = re.compile(rf"({head}\s*)([\"'])([^\"'\n]*)\2", re.MULTILINE)
        return self

    @classmethod
    def in_shell(cls, name: str) -> Self:
        """The rule for a shell script, where the assignment may be indented.

        ``readonly`` and ``export`` may precede it: ``  readonly VERSION="1.0"``.
        The name is still anchored, so ``FOO_VERSION=`` is not ``VERSION=``.
        """
        return cls(name, lead=r"[ \t]*(?:(?:readonly|export)[ \t]+)*")

    def is_assigned(self, text: str) -> bool:
        """True when ``text`` assigns the name at the start of some line."""
        return self._assigned.search(text) is not None

    def read(self, text: str) -> str | None:
        """The first quoted value assigned, or ``None`` when there is none."""
        match = self._quoted.search(text)
        return match.group(3) if match else None

    def rewritten(self, text: str, value: str) -> tuple[str, int]:
        """``text`` with the first quoted assignment set to ``value``, and the count.

        The count is 0 when no assignment has the readable shape; the caller
        decides whether that is a failure.
        """
        return self._quoted.subn(
            lambda m: f"{m.group(1)}{m.group(2)}{value}{m.group(2)}", text, count=1
        )
