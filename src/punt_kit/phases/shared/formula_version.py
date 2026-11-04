"""The version a Homebrew formula installs."""

from __future__ import annotations

import re
from typing import Self, final

_EXPLICIT = re.compile(r'^\s*version\s+"(?P<version>[^"]+)"')
_URL = re.compile(r'^\s*url\s+"(?P<url>[^"]+)"')
# Ruby constructs that open a block closed by ``end``. A modifier (``x if y``)
# never starts a line, so line-start keywords are enough for a Formula.
_OPENS = re.compile(r"^\s*(?:class|module|def|if|unless|case|while|until|begin)\b")
_DO_BLOCK = re.compile(r"\bdo(?:\s*\|[^|]*\|)?\s*$")
_END = re.compile(r"^\s*end\b")
# ``punt_quarry-3.5.5.tar.gz`` and ``.../v3.5.5.tar.gz`` both end this way.
_ARCHIVE_VERSION = re.compile(
    r"(?:^|[-_/]v?)(?P<version>\d+(?:\.\d+)+)\.(?:tar\.gz|tgz|zip|tar\.bz2)$"
)


@final
class FormulaVersion:
    """Reads a formula's version the way Homebrew does.

    An explicit ``version "X"`` wins; otherwise the version is the one in the
    first ``url`` line's archive name.
    """

    __slots__ = ("_text",)

    _text: str

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._text = text
        return self

    def value(self) -> str | None:
        """The formula's version, or ``None`` when it states none.

        Only the formula's own statements count: a ``resource`` block, a
        platform block or a method body carries other things' versions.
        """
        url: str | None = None
        for line in self._top_level():
            explicit = _EXPLICIT.match(line)
            if explicit:
                return explicit.group("version")
            found = _URL.match(line)
            if found and url is None:
                url = found.group("url")
        if url is None:
            return None
        archive = _ARCHIVE_VERSION.search(url)
        return archive.group("version") if archive else None

    def _top_level(self) -> list[str]:
        """The lines directly inside ``class ... < Formula``, nesting excluded."""
        depth = 0
        top: list[str] = []
        for line in self._text.splitlines():
            if _END.match(line):
                depth -= 1
                continue
            if depth == 1:
                top.append(line)
            if _OPENS.match(line) or _DO_BLOCK.search(line):
                depth += 1
        return top
