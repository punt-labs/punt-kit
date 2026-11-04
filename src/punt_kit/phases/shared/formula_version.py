"""The version a Homebrew formula installs."""

from __future__ import annotations

import re
from typing import Self, final

_EXPLICIT = re.compile(r'^\s*version\s+"(?P<version>[^"]+)"', re.MULTILINE)
_URL = re.compile(r'^\s*url\s+"(?P<url>[^"]+)"', re.MULTILINE)
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
        """The formula's version, or ``None`` when it states none."""
        explicit = _EXPLICIT.search(self._text)
        if explicit:
            return explicit.group("version")
        url = _URL.search(self._text)
        if url is None:
            return None
        archive = _ARCHIVE_VERSION.search(url.group("url"))
        return archive.group("version") if archive else None
