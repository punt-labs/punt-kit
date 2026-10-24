"""Where the bodies of the here-documents in a shell script are."""

from __future__ import annotations

import re
from typing import Self, final

# ``<<EOF``, ``<<-EOF``, ``<< 'EOF'``, ``<<"EOF"``, with an optional descriptor
# (``0<<EOF``, ``3<<-END``) that must start a word. Not ``<<<`` (a here-string)
# and not a shift glued to a digit or word (``1<<k``, ``a1<<k``).
_OPENER = re.compile(
    r"(?:(?<!\S)\d+|(?<![<\d]))<<(?!<)(-?)[ \t]*"
    r"(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([A-Za-z_]\w*))"
)


@final
class HeredocBodies:
    """The text a shell reads as data, not commands, because a ``<<`` opened it.

    A body starts on the line after its opener and ends at a line that is just
    the delimiter (with leading tabs allowed for ``<<-``). One that never
    closes runs to the end of the file, as it does in the shell. Best effort,
    like the rest of the line-based scan: a ``<<`` inside a quoted string is
    not told from a real one, but a comment line and ``((`` arithmetic are.
    """

    __slots__ = ("_spans",)

    _spans: tuple[tuple[int, int], ...]

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        spans: list[tuple[int, int]] = []
        pending: list[tuple[str, bool]] = []
        body_start = 0
        offset = 0
        for line in text.splitlines(keepends=True):
            end = offset + len(line)
            if pending:
                content = line.rstrip("\r\n")
                delimiter, strips_tabs = pending[0]
                if (content.lstrip("\t") if strips_tabs else content) == delimiter:
                    pending.pop(0)
                    if not pending:
                        spans.append((body_start, end))
            else:
                pending = cls._openers(line)
                body_start = end
            offset = end
        if pending:
            spans.append((body_start, len(text)))
        self._spans = tuple(spans)
        return self

    def contains(self, position: int) -> bool:
        """True when ``position`` is inside a here-document body."""
        return any(start <= position < end for start, end in self._spans)

    @classmethod
    def _openers(cls, line: str) -> list[tuple[str, bool]]:
        """The ``(delimiter, strips tabs)`` of each here-document ``line`` opens."""
        opaque = cls._opaque_spans(line)
        return [
            (m.group(2) or m.group(3) or m.group(4), m.group(1) == "-")
            for m in _OPENER.finditer(line)
            if "((" not in line[: m.start()]
            and not any(start <= m.start() < end for start, end in opaque)
        ]

    @staticmethod
    def _opaque_spans(line: str) -> list[tuple[int, int]]:
        """The ``(start, end)`` of each quoted string and of a trailing comment.

        A ``#`` starts a comment only at the beginning of a word; a backslash
        escapes the next character; a quote left open runs to the line's end.
        """
        spans: list[tuple[int, int]] = []
        i = 0
        while i < len(line):
            char = line[i]
            if char == "\\":
                i += 2
            elif char in "'\"":
                end = i + 1
                while end < len(line) and line[end] != char:
                    end += 2 if char == '"' and line[end] == "\\" else 1
                spans.append((i, end + 1))
                i = end + 1
            elif char == "#" and (i == 0 or line[i - 1] in " \t;&|("):
                spans.append((i, len(line)))
                break
            else:
                i += 1
        return spans
