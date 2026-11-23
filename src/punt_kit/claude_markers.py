"""Remove obsolete managed sections from user-owned CLAUDE.md files."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from rich.console import Console
from rich.markup import escape

from punt_kit.claude_md import ClaudeMdImport
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path

console = Console()


@final
class ClaudeMarkers:
    """Migrate legacy CLAUDE.md sections and maintain standards references."""

    __slots__ = ("_file",)

    _file: TextFile

    def __new__(cls, path: Path) -> Self:
        """Bind the user-owned CLAUDE.md file to update."""
        self = super().__new__(cls)
        self._file = TextFile(path)
        return self

    def update(self, references: str) -> list[str]:
        """Remove legacy sections and add references unless already present.

        Malformed markers skip stripping with a warning, but still add references.

        Raises:
            ReleaseError: The existing file cannot be read as UTF-8.
            OSError: The updated file cannot be written.
        """
        if not self._file.path.exists():
            self._file.write(references + "\n")
            console.print("  [green]+[/green] Created CLAUDE.md")
            return ["CLAUDE.md"]

        existing = self._file.read()
        try:
            migrated = self.strip(existing)
        except ValueError as exc:
            console.print(
                "  [yellow]Warning:[/yellow] Skipping CLAUDE.md marker migration: "
                f"{escape(str(exc))}"
            )
            migrated = existing
        if "## Standards References" not in migrated:
            migrated = self._append_references(existing, migrated, references)
        if migrated == existing:
            return []
        self._file.write(migrated)
        console.print(
            "  [yellow]↻[/yellow] Updated CLAUDE.md references and legacy sections"
        )
        return ["CLAUDE.md"]

    @staticmethod
    def _append_references(original: str, migrated: str, references: str) -> str:
        eol = TextFile.line_ending(original)
        tail = eol if original.endswith("\n") else ""
        block = references.replace("\n", eol)
        return migrated.rstrip() + eol + eol + block + tail

    @staticmethod
    def strip(content: str) -> str:
        """Return text outside complete, non-nested marker sections.

        Raises:
            ValueError: Markers are unmatched or nested.
        """
        kept: list[str] = []
        section: str | None = None
        lines = content.splitlines(keepends=True)
        flags = ClaudeMdImport.top_level_flags(lines)
        for line, top in zip(lines, flags, strict=True):
            marker = (
                re.fullmatch(r"<!-- punt:(begin|end) (\S+) -->", line.rstrip("\r\n"))
                if top
                else None
            )
            if marker is None:
                if section is None:
                    kept.append(line)
            elif marker[1] == "begin" and section is None:
                section = marker[2]
            elif marker[1] == "end" and section == marker[2]:
                section = None
            else:
                raise ValueError("nested or unmatched marker")
        if section is not None:
            raise ValueError("unterminated marker")
        return "".join(kept)
