"""Reading and rewriting a JSON file without disturbing how it was written."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path


@final
class JsonFile:
    """A JSON file rewritten as found: UTF-8 as-is, BOM, line endings, final newline."""

    __slots__ = ("_eol", "_file", "_has_final_newline")

    _file: TextFile
    _eol: str
    _has_final_newline: bool

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._file = TextFile(path)
        self._eol = "\n"
        self._has_final_newline = True
        return self

    def load(self) -> object:
        """Parse the file, remembering its line ending and final newline."""
        text = self._file.read()
        self._eol = "\r\n" if "\r\n" in text else "\n"
        self._has_final_newline = text.endswith("\n")
        # Wire boundary: json.loads yields object until the caller narrows it.
        return json.loads(text)

    def save(self, data: object) -> None:
        """Write ``data`` indented by two, keeping non-ASCII text as written."""
        body = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", self._eol)
        self._file.write(body + (self._eol if self._has_final_newline else ""))
