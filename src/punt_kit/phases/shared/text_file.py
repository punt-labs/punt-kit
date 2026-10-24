"""Reading and rewriting a text file without changing its bytes beyond the edit."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    from pathlib import Path

_BOM = "\ufeff"


@final
class TextFile:
    """A UTF-8 file read and written without newline translation.

    ``Path.read_text`` turns CRLF into LF and ``write_text`` writes LF, so a
    round trip through them rewrites every line ending of a file the release
    only meant to edit in one place. Here line endings survive untouched, and
    a leading BOM is kept on disk but hidden from the text, so an anchored
    pattern (``^version = ...``) still matches the first line.
    """

    __slots__ = ("_path",)

    _path: Path

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    @property
    def path(self) -> Path:
        """The file this object reads and writes."""
        return self._path

    @staticmethod
    def from_bytes(raw: bytes, *, source: str) -> str:
        """Decode bytes that did not come from a file, such as ``git show`` output.

        Applies the same rules as :meth:`read`: UTF-8, a leading BOM dropped,
        and an undecodable byte reported as a :class:`ReleaseError` naming
        ``source``.
        """
        try:
            return TextFile.without_bom(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            msg = f"{source} is not valid UTF-8: {exc}"
            raise ReleaseError(msg) from exc

    @staticmethod
    def line_ending(text: str) -> str:
        """``\\r\\n`` when ``text`` uses it anywhere, else ``\\n``."""
        return "\r\n" if "\r\n" in text else "\n"

    @staticmethod
    def without_bom(text: str) -> str:
        """``text`` without a leading BOM, for text a command printed."""
        return text.removeprefix(_BOM)

    @staticmethod
    def parse_toml(text: str, *, source: str) -> dict[str, object]:
        """Parse TOML text, or raise a :class:`ReleaseError` naming ``source``."""
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            msg = f"{source} is not valid TOML: {exc}"
            raise ReleaseError(msg) from exc

    def read(self) -> str:
        """The file's text with its line endings, without a leading BOM.

        Raises :class:`ReleaseError` naming the file when it cannot be read
        (permission denied, a directory, not UTF-8).
        """
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            msg = f"{self._path} cannot be read: {exc.strerror or exc}"
            raise ReleaseError(msg) from exc
        return self.from_bytes(raw, source=str(self._path))

    def toml(self) -> dict[str, object]:
        """The file parsed as TOML, or a :class:`ReleaseError` naming it and why."""
        return self.parse_toml(self.read(), source=str(self._path))

    def write(self, text: str) -> None:
        """Replace the file's text, restoring the BOM the file already had."""
        bom = _BOM if self._path.exists() and self._has_bom() else ""
        self._path.write_bytes((bom + text).encode("utf-8"))

    def _has_bom(self) -> bool:
        return self._path.read_bytes().startswith(_BOM.encode("utf-8"))
