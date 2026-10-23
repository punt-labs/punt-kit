"""Finding and rewriting a ``name = "version"`` assignment in a source file."""

from __future__ import annotations

import re
from typing import Self, final

# What may precede a shell assignment: indentation, and the declaration
# builtins with their flags (``readonly -r``, ``declare -x``, ``local``).
_SHELL_LEAD = r"[ \t]*(?:(?:readonly|export|local|declare)[ \t]+(?:-\w+[ \t]+)*)*"
# A double-quoted shell value that expands something is not a plain string.
_EXPANDS = re.compile(r"[$`]")


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

    __slots__ = ("_assigned", "_is_shell", "_quoted")

    _assigned: re.Pattern[str]
    _quoted: re.Pattern[str]
    _is_shell: bool

    def __new__(cls, name: str, *, lead: str = "", is_shell: bool = False) -> Self:
        self = super().__new__(cls)
        head = rf"^{lead}{re.escape(name)}(?:\s*:[^=\n]+)?\s*="
        self._assigned = re.compile(head, re.MULTILINE)
        self._quoted = re.compile(rf"({head}\s*)([\"'])([^\"'\n]*)\2", re.MULTILINE)
        self._is_shell = is_shell
        return self

    @classmethod
    def in_shell(cls, name: str) -> Self:
        """The rule for a shell script, where the assignment may be indented.

        ``readonly``, ``export``, ``local`` and ``declare`` (with flags) may
        precede it: ``  readonly -r VERSION="1.0"``. The name is still
        anchored, so ``FOO_VERSION=`` is not ``VERSION=``. The *first*
        assignment decides, and a double-quoted value containing ``$`` or a
        backtick (``"${VERSION:-1.0}"``, ``"$(git describe)"``) is computed,
        so it is assigned but not readable.
        """
        return cls(name, lead=_SHELL_LEAD, is_shell=True)

    def is_assigned(self, text: str) -> bool:
        """True when ``text`` assigns the name at the start of some line."""
        return self._assigned.search(text) is not None

    def assigned_line(self, text: str) -> str:
        """The first line that assigns the name, stripped; empty when none."""
        match = self._assigned.search(text)
        if match is None:
            return ""
        return text[match.start() :].split("\n", 1)[0].strip()

    def read(self, text: str) -> str | None:
        """The first quoted value assigned, or ``None`` when there is none."""
        match = self._readable(text)
        return match.group(3) if match else None

    def rewritten(self, text: str, value: str) -> tuple[str, int]:
        """``text`` with the first quoted assignment set to ``value``, and the count.

        The count is 0 when no assignment has the readable shape; the caller
        decides whether that is a failure.
        """
        match = self._readable(text)
        if match is None:
            return text, 0
        quote = match.group(2)
        replacement = f"{match.group(1)}{quote}{value}{quote}"
        return text[: match.start()] + replacement + text[match.end() :], 1

    def _readable(self, text: str) -> re.Match[str] | None:
        """The match that supplies the value, or ``None`` when it is not plain."""
        if not self._is_shell:
            return self._quoted.search(text)
        first = self._assigned.search(text)
        if first is None:
            return None
        match = self._quoted.match(text, first.start())
        if match and match.group(2) == '"' and _EXPANDS.search(match.group(3)):
            return None
        return match
