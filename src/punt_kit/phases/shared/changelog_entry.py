"""Adding one bullet to a CHANGELOG's ``[Unreleased]`` section."""

from __future__ import annotations

import re
from typing import Self, final

_UNRELEASED = re.compile(r"^## \[Unreleased\][ \t]*\r?$", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)
_CATEGORY = re.compile(r"^### (?P<name>.+?)[ \t]*\r?$", re.MULTILINE)


@final
class UnreleasedEntry:
    """A bullet to file under a Keep a Changelog category of ``[Unreleased]``."""

    __slots__ = ("_category", "_line")

    _line: str
    _category: str

    def __new__(cls, line: str, *, category: str = "Changed") -> Self:
        self = super().__new__(cls)
        self._line = line
        self._category = category
        return self

    def added_to(self, text: str) -> str | None:
        """``text`` with the bullet filed, or ``None`` if it cannot be.

        ``None`` means there is no ``[Unreleased]`` section. A bullet already
        present in that section is left alone, so a resumed release does not
        file it twice.
        """
        heading = _UNRELEASED.search(text)
        if heading is None:
            return None
        nl = "\r\n" if "\r\n" in text else "\n"
        start = heading.end()
        following = _NEXT_SECTION.search(text, start)
        end = following.start() if following else len(text)
        body = text[start:end]
        bullet = f"- {self._line}"
        if any(line.rstrip("\r") == bullet for line in body.splitlines()):
            return text
        category = next(
            (m for m in _CATEGORY.finditer(body) if m.group("name") == self._category),
            None,
        )
        if category is None:
            new = f"{nl}{nl}### {self._category}{nl}{nl}{bullet}{nl}"
            tail = body.lstrip("\r\n")
            if tail:
                new += nl + tail
            return text[:start] + new + text[end:]
        after = _CATEGORY.search(body, category.end())
        stop = after.start() if after else len(body)
        block = body[category.end() : stop].rstrip()
        rest = body[category.end() + len(block) : stop]
        filed = body[: category.end()] + block + nl + bullet + rest + body[stop:]
        return text[:start] + filed + text[end:]
