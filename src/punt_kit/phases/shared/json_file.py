"""Read and rewrite JSON while preserving file conventions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path


@final
class JsonFile:
    """Read and rewrite UTF-8 JSON while retaining BOM and newline conventions."""

    __slots__ = ("_eol", "_file", "_has_final_newline")

    _file: TextFile
    _eol: str
    _has_final_newline: bool

    def __new__(cls, path: Path) -> Self:
        """Prepare to read or write JSON at ``path``."""
        self = super().__new__(cls)
        self._file = TextFile(path)
        self._eol = "\n"
        self._has_final_newline = True
        return self

    @staticmethod
    def parse(text: str, *, source: str) -> object:
        """Parse JSON text and ignore a leading BOM.

        Args:
            source: File or revision label used in diagnostics.

        Raises:
            ReleaseError: The text is not valid JSON.
        """
        try:
            # Wire boundary: json.loads yields object until the caller narrows it.
            return json.loads(TextFile.without_bom(text))
        except json.JSONDecodeError as exc:
            msg = f"{source} is not valid JSON: {exc}"
            raise ReleaseError(msg) from exc

    @classmethod
    def parse_object(cls, text: str, *, source: str) -> dict[str, object]:
        """Parse JSON text that must hold an object.

        Args:
            source: File or revision label used in diagnostics.

        Raises:
            ReleaseError: The text is not valid JSON or is not an object.
        """
        data = cls.parse(text, source=source)
        if not isinstance(data, dict):
            msg = f"{source} must hold a JSON object, found {type(data).__name__}"
            raise ReleaseError(msg)
        return cast("dict[str, object]", data)

    def load(self) -> object:
        """Parse the file and remember its newline conventions.

        Raises:
            ReleaseError: The file is unreadable or not valid UTF-8 JSON.
        """
        text = self._file.read()
        self._eol = "\r\n" if "\r\n" in text else "\n"
        self._has_final_newline = text.endswith("\n")
        return self.parse(text, source=str(self._file.path))

    def load_object(self) -> dict[str, object]:
        """Parse a JSON object and remember the file's newline conventions.

        Raises:
            ReleaseError: The file is unreadable, not valid UTF-8 JSON,
                or does not contain an object.
        """
        text = self._file.read()
        self._eol = "\r\n" if "\r\n" in text else "\n"
        self._has_final_newline = text.endswith("\n")
        return self.parse_object(text, source=str(self._file.path))

    def save(self, data: object) -> None:
        """Write two-space-indented JSON with unescaped non-ASCII text.

        Preserve newline conventions from the most recent load.

        Raises:
            TypeError: The data cannot be serialized as JSON.
            ValueError: The data contains a circular reference.
            OSError: The file cannot be read for BOM detection or written.
            UnicodeEncodeError: A JSON string cannot be encoded as UTF-8.
        """
        body = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", self._eol)
        self._file.write(body + (self._eol if self._has_final_newline else ""))
