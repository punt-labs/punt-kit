"""Reading and rewriting a text file without changing its bytes beyond the edit."""

from __future__ import annotations

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
            return raw.decode("utf-8").removeprefix(_BOM)
        except UnicodeDecodeError as exc:
            msg = f"{source} is not valid UTF-8: {exc}"
            raise ReleaseError(msg) from exc

    def read(self) -> str:
        """The file's text with its line endings, without a leading BOM."""
        return self.from_bytes(self._path.read_bytes(), source=str(self._path))

    def write(self, text: str) -> None:
        """Replace the file's text, restoring the BOM the file already had."""
        bom = _BOM if self._path.exists() and self._has_bom() else ""
        self._path.write_bytes((bom + text).encode("utf-8"))

    def _has_bom(self) -> bool:
        return self._path.read_bytes().startswith(_BOM.encode("utf-8"))
