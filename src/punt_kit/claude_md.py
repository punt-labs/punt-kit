"""Maintain a tool's bare ``@``-import line in the host ``CLAUDE.md``.

Leave the rest of the host file untouched; Claude Code resolves imports at
read time (tool-enable-disable.md §2.4).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ["UNCLOSED_FENCE", "ClaudeMdImport", "write_atomically"]

_NEW_FILE_MODE = 0o644
UNCLOSED_FENCE = "CLAUDE.md ends inside an unclosed code fence; close it first"
_LOCK_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC


@final
class ClaudeMdImport:
    """Edit one bare import under a shared lock and replace the file atomically."""

    __slots__ = ("_host", "_import_line")

    _host: Path
    _import_line: str

    def __new__(cls, host_path: Path, import_line: str) -> Self:
        """Own ``import_line`` inside the host file at ``host_path``.

        Raises:
            ValueError: ``import_line`` is not a single bare ``@`` line.
        """
        cls._validate(import_line)
        self = super().__new__(cls)
        self._host = host_path
        self._import_line = import_line
        return self

    def is_registered(self) -> bool:
        """Return ``True`` when the import line is present at top level.

        A pure read — no lock needed, since every write lands atomically and a
        read therefore never observes a torn file.
        """
        return self._present(self._read())

    def append_would_be_fenced(self) -> bool:
        """Return ``True`` when :meth:`register` would append into an open fence.

        :meth:`register` appends at the end of the file, so an import added
        after a fence that never closes would be inert while ``enable``
        reported success. An import already present at top level is left
        alone, so it never is. Callers check this before changing anything.
        """
        if not self._host.is_file():
            return False
        text = self._read()
        open_at = self._scan_fences(self._physical_lines(text))[1]
        return not self._present(text) and open_at is not None

    def register(self) -> bool:
        """Append the import line if absent. Return ``True`` if the file changed.

        An existing top-level import is a no-op.

        Raises:
            ValueError: The file ends inside a fence that never closes, so the
                appended line would be inert.
            OSError: The host file or its lock file cannot be read or written.
        """
        with self.locked(self._host):
            text = self._read()
            if self._present(text):
                return False
            if self._scan_fences(self._physical_lines(text))[1] is not None:
                raise ValueError(UNCLOSED_FENCE)
            self._write(self._appended(text))
            return True

    def prune(self) -> bool:
        """Remove every top-level occurrence. Return ``True`` if the file changed.

        Collapses an accidental duplicate to zero and leaves any inert copy
        inside a code block untouched. An absent host has nothing to prune, so
        no lock file is created for it.

        Raises:
            OSError: The host file or its lock file cannot be read or written.
        """
        if not self._host.is_file():
            return False
        with self.locked(self._host):
            text = self._read()
            new_text = self._removed(text)
            if new_text == text:
                return False
            self._write(new_text)
            return True

    def _present(self, text: str) -> bool:
        """Return ``True`` when a top-level line matches the import line."""
        lines = self._physical_lines(text)
        flags = self.top_level_flags(lines)
        return any(
            top and self._line_matches(line)
            for line, top in zip(lines, flags, strict=True)
        )

    def _appended(self, text: str) -> str:
        """Return *text* with the import line appended as one bare top-level line.

        Ensures a separating newline first (so the import is never glued to the
        user's last line) and uses the host file's existing EOL convention for
        both the separator and the appended line.
        """
        eol = self._detect_eol(text)
        result = text
        if result and not result.endswith(("\n", "\r")):
            result += eol
        return f"{result}{self._import_line}{eol}"

    def _removed(self, text: str) -> str:
        """Return *text* with every top-level occurrence of the line removed."""
        lines = self._physical_lines(text)
        flags = self.top_level_flags(lines)
        kept = [
            line
            for line, top in zip(lines, flags, strict=True)
            if not (top and self._line_matches(line))
        ]
        return "".join(kept)

    def _line_matches(self, line: str) -> bool:
        """Match a physical line against the import line, net of its terminator."""
        return line.rstrip("\r\n") == self._import_line

    @staticmethod
    def _physical_lines(text: str) -> list[str]:
        """Split into physical lines, keeping each line's terminator."""
        return text.splitlines(keepends=True)

    @staticmethod
    def _parse_fence(line: str) -> tuple[str, int] | None:
        """Return ``(marker_char, run_length)`` if *line* is a fence delimiter.

        A fence delimiter is a run of three or more of a single marker char
        (a backtick or a tilde) after up to three leading spaces. An **indented**
        line (a tab, or four or more leading spaces) is an inert indented-code
        line, never a fence delimiter (§2.4). Returns ``None`` otherwise.
        """
        bare = line.rstrip("\r\n")
        if bare.startswith("\t"):
            return None
        stripped = bare.lstrip(" ")
        if len(bare) - len(stripped) >= 4:
            return None
        if not stripped or stripped[0] not in "`~":
            return None
        marker = stripped[0]
        run = len(stripped) - len(stripped.lstrip(marker))
        return (marker, run) if run >= 3 else None

    @classmethod
    def _fenced_ranges(cls, lines: list[str]) -> list[tuple[int, int]]:
        """Return ``(open_idx, close_idx)`` index pairs of fenced blocks.

        A fence that never closes runs to the last line, as in CommonMark.
        """
        ranges, open_at = cls._scan_fences(lines)
        if open_at is not None:
            ranges.append((open_at, len(lines) - 1))
        return ranges

    @classmethod
    def _scan_fences(cls, lines: list[str]) -> tuple[list[tuple[int, int]], int | None]:
        """Return the matched fenced blocks and the index of an opener left open.

        A block opened by a run of *N* of a marker closes only on a later
        **same-marker** delimiter of length ``>= N`` (CommonMark); a mismatched
        marker, a shorter run, or a run followed by an info string (valid on an
        opener only) is content, not a close, so an inner ``~~~`` or
        ```` ```python ```` in a ```` ``` ```` block never toggles the state.
        An opener that never closes is returned separately: Claude Code's
        Markdown lexer treats it as running to the end of the file, so a line
        after it is fenced.
        Blocks do not nest — once open, every line up to the matching
        close is content.
        """
        ranges: list[tuple[int, int]] = []
        open_at: int | None = None
        open_marker = ""
        open_len = 0
        for i, line in enumerate(lines):
            fence = cls._parse_fence(line)
            if open_at is None:
                if fence is not None:
                    open_at, (open_marker, open_len) = i, fence
            elif (
                fence is not None
                and fence[0] == open_marker
                and fence[1] >= open_len
                and not line.rstrip("\r\n").lstrip(" ")[fence[1] :].strip(" ")
            ):
                ranges.append((open_at, i))
                open_at = None
        return ranges, open_at

    @classmethod
    def top_level_flags(cls, lines: list[str]) -> list[bool]:
        """Flag each line ``True`` when it is top-level (not in a code block).

        A line is non-top-level when it lies inside a fenced block
        (:meth:`_fenced_ranges`, including one that never closes) or is itself
        an indented code-block line — a tab or four or more leading spaces
        (§2.4). The tool's own import line is
        written at column 0 with no info string, so it is top-level by
        construction unless it sits inside a fenced block.
        """
        inside: set[int] = set()
        for open_idx, close_idx in cls._fenced_ranges(lines):
            # Content and the closing delimiter are inside; the opener is not.
            inside.update(range(open_idx + 1, close_idx + 1))
        flags: list[bool] = []
        for i, line in enumerate(lines):
            leading_spaces = len(line) - len(line.lstrip(" "))
            indented = line.startswith("\t") or leading_spaces >= 4
            flags.append(i not in inside and not indented)
        return flags

    @staticmethod
    def _detect_eol(text: str) -> str:
        r"""Return the host file's EOL convention, defaulting to ``\\n``."""
        crlf = text.find("\r\n")
        lf = text.find("\n")
        cr = text.find("\r")
        if crlf != -1 and crlf == lf - 1:
            return "\r\n"
        if lf != -1 and (cr == -1 or lf < cr):
            return "\n"
        if cr != -1:
            return "\r"
        return "\n"

    @staticmethod
    @contextmanager
    def locked(host: Path) -> Generator[None]:
        """Serialize CLAUDE.md writers using the shared sibling lock.

        Raises:
            OSError: The lock cannot be created or acquired.
        """
        lock_path = host.parent / f".{host.name}.punt-import.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, _LOCK_FLAGS, _NEW_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> str:
        """Return the host file verbatim, or ``""`` when it does not exist.

        ``newline=""`` disables universal-newline translation so a read/write
        round-trip keeps LF, CRLF, and lone-CR endings byte-identical.
        ``errors="surrogateescape"`` makes the read byte-faithful for a host
        that is *not* valid UTF-8 (a hand-authored ``CLAUDE.md`` may hold
        latin-1 or mixed bytes): invalid bytes decode to lone surrogates and
        :meth:`_write` restores them, so a non-UTF-8 host neither crashes the
        read (``UnicodeDecodeError`` is a ``ValueError``, not ``OSError``) nor
        is corrupted on write-back.
        """
        if not self._host.is_file():
            return ""
        return self._host.read_text(
            encoding="utf-8", newline="", errors="surrogateescape"
        )

    def _write(self, text: str) -> None:
        """Replace the host file's contents with *text* atomically.

        A symlinked path is resolved so the rename updates the real file and
        preserves the link.
        """
        write_atomically(
            self._host.resolve() if self._host.is_symlink() else self._host, text
        )

    @staticmethod
    def _validate(import_line: str) -> None:
        """Raise ``ValueError`` unless *import_line* is a lone top-level ``@`` line.

        Validated at the construction boundary (PY-EH-1): the line is spliced
        into the host file verbatim, so a padded, multi-line, or non-``@`` value
        would inject a duplicate, a blank line, or inert markdown.
        """
        if not import_line or import_line.isspace():
            raise ValueError("import line must be non-empty")
        if "\n" in import_line or "\r" in import_line:
            raise ValueError(f"import line must be a single line: {import_line!r}")
        if import_line != import_line.strip():
            raise ValueError(
                f"import line must have no leading/trailing whitespace: {import_line!r}"
            )
        if not import_line.startswith("@"):
            raise ValueError(f"import line must begin with '@': {import_line!r}")


def write_atomically(target: Path, text: str) -> None:
    """Replace ``target``'s contents with ``text``, keeping its mode.

    Writes a temp file in the target's own directory, ``fsync``s it, then
    ``os.replace``s it over the target, so an interrupted write leaves the
    original untouched.

    Raises:
        OSError: The temp file cannot be written or moved over ``target``.
    """
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(target.stat().st_mode) if target.is_file() else _NEW_FILE_MODE
    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        # surrogateescape mirrors _read: a lone surrogate produced by
        # decoding an invalid host byte is written back as that exact byte.
        handle = os.fdopen(
            fd, "w", encoding="utf-8", newline="", errors="surrogateescape"
        )
    except BaseException:
        os.close(fd)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # os.replace preserves the temp's 0600 mkstemp mode, so stamp the
        # intended mode before the rename or an existing 0644 file drops.
        tmp.chmod(mode)
        tmp.replace(target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
