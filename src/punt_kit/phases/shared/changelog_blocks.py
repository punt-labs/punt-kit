"""Finding fenced and HTML blocks that run unclosed to the end of a changelog."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from markdown_it.token import Token

# CommonMark HTML block kinds 1-5 end only at a closing marker, so one that
# never closes swallows every later line. Kinds 6 and 7 end at a blank line
# and cannot run away. Each entry: (start of the block, its closing marker).
_HTML_OPENERS = (
    (re.compile(r" {0,3}<!--"), re.compile(r"--!?>")),
    (re.compile(r" {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r" {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r" {0,3}<![A-Za-z]"), re.compile(r">")),
    (
        re.compile(r" {0,3}<(?:script|pre|style|textarea)(?:[\s>]|$)", re.IGNORECASE),
        re.compile(r"</(?:script|pre|style|textarea)>", re.IGNORECASE),
    ),
)


@final
class UnclosedBlockScan:
    """The fences and HTML blocks that are opened and never closed.

    A block counts only when it reaches the end of the document: inside a
    list item or quote, the container ending closes it, and no later line is
    swallowed.
    """

    __slots__ = ("_end", "_lines", "_tokens")

    _tokens: tuple[Token, ...]
    _lines: tuple[str, ...]
    _end: int

    def __new__(cls, tokens: tuple[Token, ...], lines: tuple[str, ...]) -> Self:
        self = super().__new__(cls)
        self._tokens = tokens
        self._lines = lines
        # Trailing blank lines belong to no block.
        self._end = len(lines)
        while self._end and not lines[self._end - 1].strip():
            self._end -= 1
        return self

    def opening_lines(self) -> tuple[int, ...]:
        """The 1-based line of every unclosed opener, in document order."""
        return tuple(
            token.map[0] + 1
            for token in self._tokens
            if token.map is not None
            and token.map[1] >= self._end
            and self._is_unclosed(token)
        )

    def _is_unclosed(self, token: Token) -> bool:
        if token.type == "fence":
            return self._fence_is_unclosed(token)
        if token.type == "html_block":
            return self._html_is_unclosed(token)
        return False

    @staticmethod
    def _fence_is_unclosed(token: Token) -> bool:
        """True unless the parser consumed a closing line after the content.

        The token's ``map`` covers the opener, the content and a closer when
        there is one, and ``content`` holds only the content lines: so the
        block is closed exactly when the map has a line the content lacks
        beyond the opener. The parser has already applied CommonMark's rules
        for the closer (0-3 spaces, same container, long enough), so none of
        them is re-scanned here.
        """
        first, end = token.map or (0, 0)
        content = token.content
        # A final line without a newline still counts as a line.
        content_lines = content.count("\n") + (
            1 if content and not content.endswith("\n") else 0
        )
        return end - first - 1 - content_lines < 1

    @staticmethod
    def _html_is_unclosed(token: Token) -> bool:
        """True when the block starts a kind that only a closing marker ends."""
        return any(
            opener.match(token.content) and not closer.search(token.content)
            for opener, closer in _HTML_OPENERS
        )
