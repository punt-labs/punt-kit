"""Finding and rewriting a ``name = "version"`` assignment in a source file."""

from __future__ import annotations

import re
from typing import Self, final

# What may precede a shell assignment: indentation, and the declaration
# builtins with their flags (``readonly -r``, ``declare -x``, ``typeset -r``).
_SHELL_LEAD = (
    r"[ \t]*(?:(?:readonly|export|local|declare|typeset)[ \t]+(?:-\w+[ \t]+)*)*"
)
# A double-quoted shell value that expands something is not a plain string.
_EXPANDS = re.compile(r"[$`]")
# What may follow the closing quote of a plain shell value: the end of the
# line, whitespace or a command separator. A ``#`` starts a comment only at the
# beginning of a word, so one glued to the quote (``"1.0"#x``) continues the
# word, like ``"1.0"$SUFFIX`` and ``'1'"$x"``: the value is computed.
_VALUE_END = re.compile(r"[ \t;\r\n]|\Z")
# An unquoted shell word is a literal when it holds nothing the shell would
# expand, split or glue onto: ``VERSION=0.0.9`` is as fixed as ``"0.0.9"``.
_BARE_WORD = r"[^\s\"'`$;&|<>(){}\\#]+"


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

    __slots__ = ("_assigned", "_bare", "_is_shell", "_quoted")

    _assigned: re.Pattern[str]
    _bare: re.Pattern[str]
    _quoted: re.Pattern[str]
    _is_shell: bool

    def __new__(cls, name: str, *, lead: str = "", is_shell: bool = False) -> Self:
        self = super().__new__(cls)
        head = rf"^{lead}{re.escape(name)}(?:[ \t]*:[^=\n]+)?[ \t]*="
        self._assigned = re.compile(head, re.MULTILINE)
        self._quoted = re.compile(rf"({head}[ \t]*)([\"'])([^\"'\n]*)\2", re.MULTILINE)
        # Group 2 is empty so a bare word and a quoted one share one shape.
        self._bare = re.compile(rf"({head}[ \t]*)()({_BARE_WORD})", re.MULTILINE)
        self._is_shell = is_shell
        return self

    @classmethod
    def in_shell(cls, name: str) -> Self:
        """The rule for a shell script, where the assignment may be indented.

        ``readonly``, ``export``, ``local`` and ``declare`` (with flags) may
        precede it: ``  readonly -r VERSION="1.0"``. The name is still
        anchored, so ``FOO_VERSION=`` is not ``VERSION=``. ``typeset`` is
        recognised like ``declare``.

        The *first* assignment decides whether the script can be bumped: it
        is the value a script has until something reassigns it. Every later
        assignment that is a plain string is rewritten with it, so a re-pin in
        a branch cannot stay stale; one that is computed is left alone. An
        unquoted literal (``VERSION=0.0.9``) is a plain value like a quoted one
        and is rewritten without quotes. A value is
        computed, so assigned but not readable, when it is double-quoted and
        contains ``$`` or a backtick (``"${VERSION:-1.0}"``,
        ``"$(git describe)"``), or when the closing quote is followed by more
        word (``"1.0"$SUFFIX``, ``'1'"$x"``, ``"1.0"#x``; a ``#`` only starts
        a comment after whitespace). A later assignment can still
        replace an earlier one at run time, and a line inside a heredoc or an
        untaken branch is not an assignment at all; ``assigned_lines`` lists
        them all so the caller can warn that it cannot tell which take effect.
        """
        return cls(name, lead=_SHELL_LEAD, is_shell=True)

    def is_assigned(self, text: str) -> bool:
        """True when ``text`` assigns the name at the start of some line."""
        return self._assigned.search(text) is not None

    def assigned_lines(self, text: str) -> tuple[str, ...]:
        """Every line that assigns the name, stripped, in order.

        Best effort: it sees assignments that start a line. A compound form
        such as ``if ...; then VERSION=...; fi`` or an appending
        ``VERSION+=...`` is not seen.
        """
        return tuple(
            text[match.start() :].split("\n", 1)[0].strip()
            for match in self._assigned.finditer(text)
        )

    def read(self, text: str) -> str | None:
        """The first plain value assigned, or ``None`` when there is none."""
        match = self._readable(text)
        return match.group(3) if match else None

    def is_pinned_to(self, text: str, value: str) -> bool:
        """True when the first assignment is plain and every plain one is ``value``."""
        if self.read(text) is None:
            return False
        return all(found in (None, value) for found in self.values(text))

    def rewritten(self, text: str, value: str) -> tuple[str, int]:
        """``text`` with every plain quoted assignment set to ``value``, and the count.

        The count is 0 when the first assignment lacks the readable shape; the
        caller decides whether that is a failure.
        """
        matches = self._rewritable(text)
        parts: list[str] = []
        end = 0
        for match in matches:
            quote = match.group(2)
            parts.append(text[end : match.start()])
            parts.append(f"{match.group(1)}{quote}{value}{quote}")
            end = match.end()
        parts.append(text[end:])
        return "".join(parts), len(matches)

    def values(self, text: str) -> tuple[str | None, ...]:
        """The value of each assignment in order; ``None`` for a computed one."""
        found = (self._value_at(text, m.start()) for m in self._assigned.finditer(text))
        return tuple(m.group(3) if m else None for m in found)

    def _rewritable(self, text: str) -> list[re.Match[str]]:
        """The matches to rewrite: all plain ones, when the first is plain."""
        first = self._readable(text)
        if first is None:
            return []
        if not self._is_shell:
            return [first]
        starts = (m.start() for m in self._assigned.finditer(text))
        found = (self._value_at(text, start) for start in starts)
        return [m for m in found if m is not None]

    def _readable(self, text: str) -> re.Match[str] | None:
        """The match that supplies the value, or ``None`` when it is not plain."""
        if not self._is_shell:
            return self._quoted.search(text)
        first = self._assigned.search(text)
        if first is None:
            return None
        return self._value_at(text, first.start())

    def _value_at(self, text: str, start: int) -> re.Match[str] | None:
        """The value of the assignment at ``start``, if it is a plain literal."""
        match = self._quoted.match(text, start)
        if not self._is_shell:
            return match
        match = match or self._bare.match(text, start)
        if match is None:
            return None
        if match.group(2) == '"' and _EXPANDS.search(match.group(3)):
            return None
        if _VALUE_END.match(text, match.end()) is None:
            return None
        return match
