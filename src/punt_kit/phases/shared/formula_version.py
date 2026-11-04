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
# ``punt_quarry-3.5.5.tar.gz`` and ``.../v3.5.5.tar.gz`` both end this way. The
# version is a PEP 440 release plus any pre, post and dev segments:
# ``1.2.3rc1``, ``1.2.3.post1``, ``1.2.3a1``, ``1.2.3.dev1``.
_ARCHIVE_VERSION = re.compile(
    r"(?:^|[-_/]v?)(?P<version>\d+(?:\.\d+)+"
    r"(?:[._-]?(?:a|b|c|rc|alpha|beta|pre|preview)[._-]?\d+)?"
    r"(?:[._-]?(?:post|rev|r)[._-]?\d+)?"
    r"(?:[._-]?dev[._-]?\d*)?)"
    r"\.(?:tar\.gz|tgz|zip|tar\.bz2)$"
)


@final
class FormulaVersion:
    """Reads the versions a formula states: an explicit ``version "X"`` and the
    one in the first ``url`` line's archive name.
    """

    __slots__ = ("_text",)

    _text: str

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._text = text
        return self

    def stated(self) -> tuple[str, ...]:
        """Every version the formula states: its top-level ``version`` and its
        main url's archive version, whichever are present.

        Only the formula's own statements count: a ``resource`` block, a
        platform block or a method body carries other things' versions.
        """
        explicit: str | None = None
        url: str | None = None
        for line in self._top_level():
            if explicit is None and (found := _EXPLICIT.match(line)):
                explicit = found.group("version")
            if url is None and (found := _URL.match(line)):
                url = found.group("url")
        archive = _ARCHIVE_VERSION.search(url) if url else None
        return tuple(
            v for v in (explicit, archive.group("version") if archive else None) if v
        )

    def is_release(self, version: str) -> bool:
        """True when the formula states a version and every one is ``version``.

        A bumped ``version`` over an archive url that still names the old
        release installs the old release, so both must agree.
        """
        stated = self.stated()
        return bool(stated) and all(v == version for v in stated)

    def describe(self) -> str:
        """The stated versions as text, for a verdict line."""
        stated = self.stated()
        return ", ".join(dict.fromkeys(stated)) if stated else "not found"

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
