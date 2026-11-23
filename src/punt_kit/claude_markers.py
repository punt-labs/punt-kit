"""Remove obsolete managed sections from user-owned CLAUDE.md files."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from rich.console import Console
from rich.markup import escape

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

        Malformed markers leave the entire file unchanged with a warning.

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
                f"  [yellow]Warning:[/yellow] Skipping CLAUDE.md: {escape(str(exc))}"
            )
            return []
        if "## Standards References" not in migrated:
            eol = TextFile.line_ending(existing)
            tail = eol if existing.endswith("\n") else ""
            block = references.replace("\n", eol)
            migrated = migrated.rstrip() + eol + eol + block + tail
        if migrated == existing:
            return []
        self._file.write(migrated)
        console.print(
            "  [yellow]↻[/yellow] Updated CLAUDE.md references and legacy sections"
        )
        return ["CLAUDE.md"]

    @staticmethod
    def strip(content: str) -> str:
        """Return text outside complete, non-nested marker sections.

        Raises:
            ValueError: Markers are unmatched, nested, or malformed.
        """
        kept: list[str] = []
        section: str | None = None
        for line in content.splitlines(keepends=True):
            marker = re.fullmatch(
                r"<!-- punt:(begin|end) (\S+) -->", line.rstrip("\r\n")
            )
            if marker is None:
                if "punt:begin" in line or "punt:end" in line:
                    raise ValueError("malformed marker")
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
