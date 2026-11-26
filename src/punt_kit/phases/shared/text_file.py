"""Read and rewrite text without changing its on-disk conventions."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    from pathlib import Path

_BOM = "\ufeff"


@final
class TextFile:
    """Read and write UTF-8 text without translating newlines.

    ``Path.read_text`` turns CRLF into LF and ``write_text`` writes LF, so a
    round trip through them rewrites every line ending of a file the release
    only meant to edit in one place. Here line endings survive untouched, and
    a leading BOM is kept on disk but hidden from the text, so an anchored
    pattern (``^version = ...``) still matches the first line.
    """

    __slots__ = ("_path",)

    _path: Path

    def __new__(cls, path: Path) -> Self:
        """Bind a path for BOM- and newline-preserving text access."""
        self = super().__new__(cls)
        self._path = path
        return self

    @property
    def path(self) -> Path:
        """Return the path this object reads and writes."""
        return self._path

    @staticmethod
    def from_bytes(raw: bytes, *, source: str) -> str:
        """Decode UTF-8 bytes and remove a leading BOM.

        Args:
            source: File or revision label used in diagnostics.

        Raises:
            ReleaseError: The bytes are not valid UTF-8.
        """
        try:
            return TextFile.without_bom(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            msg = f"{source} is not valid UTF-8: {exc}"
            raise ReleaseError(msg) from exc

    @staticmethod
    def line_ending(text: str) -> str:
        r"""Return ``\r\n`` if present anywhere in ``text``, else ``\n``."""
        return "\r\n" if "\r\n" in text else "\n"

    @staticmethod
    def without_bom(text: str) -> str:
        """Strip the leading BOM from text, if any."""
        return text.removeprefix(_BOM)

    @staticmethod
    def parse_toml(text: str, *, source: str) -> dict[str, object]:
        """Parse TOML text.

        Args:
            source: File or revision label used in diagnostics.

        Raises:
            ReleaseError: The text is not valid TOML.
        """
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            msg = f"{source} is not valid TOML: {exc}"
            raise ReleaseError(msg) from exc

    def read(self) -> str:
        """Read the file with its line endings intact but without a leading BOM.

        Raises:
            ReleaseError: The file is unreadable or not valid UTF-8.
        """
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            msg = f"{self._path} cannot be read: {exc.strerror or exc}"
            raise ReleaseError(msg) from exc
        return self.from_bytes(raw, source=str(self._path))

    def toml(self) -> dict[str, object]:
        """Read the file as TOML.

        Raises:
            ReleaseError: The file is unreadable or not valid UTF-8 TOML.
        """
        return self.parse_toml(self.read(), source=str(self._path))

    def write(self, text: str) -> None:
        """Replace the file's text, retaining an existing BOM.

        Raises:
            OSError: The file cannot be read for BOM detection or written.
            UnicodeEncodeError: The text cannot be encoded as UTF-8.
        """
        bom = _BOM if self._path.exists() and self._has_bom() else ""
        self._path.write_bytes((bom + text).encode("utf-8"))

    def _has_bom(self) -> bool:
        return self._path.read_bytes().startswith(_BOM.encode("utf-8"))
