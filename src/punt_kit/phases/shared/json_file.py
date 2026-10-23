"""Reading and rewriting a JSON file without disturbing how it was written."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path


@final
class JsonFile:
    """A JSON file rewritten as it was found: UTF-8 as-is, same final newline."""

    __slots__ = ("_has_final_newline", "_path")

    _path: Path
    _has_final_newline: bool

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._has_final_newline = True
        return self

    def load(self) -> object:
        """Parse the file, remembering whether it ended with a newline."""
        text = self._path.read_text(encoding="utf-8")
        self._has_final_newline = text.endswith("\n")
        # Wire boundary: json.loads yields object until the caller narrows it.
        return json.loads(text)

    def save(self, data: object) -> None:
        """Write ``data`` indented by two, keeping non-ASCII text as written."""
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self._path.write_text(
            text + ("\n" if self._has_final_newline else ""), encoding="utf-8"
        )
