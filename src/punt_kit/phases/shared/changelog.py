"""Read and update a project's CHANGELOG.md."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.changelog_entry import UnreleasedEntry
from punt_kit.phases.shared.changelog_parser import ChangelogDocument
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class Changelog:
    """Inspect and update a project's changelog.

    Every answer comes from ``ChangelogDocument``, the one parser; this
    class only owns locating and reading the file.
    """

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        """Bind the project's changelog and release operations."""
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def text(self) -> str:
        """Read CHANGELOG.md.

        Raises:
            ReleaseError: The file is missing, unreadable, or not UTF-8.
        """
        changelog = self._root / "CHANGELOG.md"
        if not changelog.exists():
            self._ops.fail("CHANGELOG.md not found")
        return TextFile(changelog).read()

    def document(self) -> ChangelogDocument:
        """Parse CHANGELOG.md for queries on a single snapshot.

        Raises:
            ReleaseError: The file is missing, unreadable, or not UTF-8.
        """
        return ChangelogDocument(self.text())

    def require_unreleased_entries(self) -> None:
        """Require entries under Unreleased before releasing.

        Headings and HTML comments alone do not count as entries.

        Raises:
            ReleaseError: The file is missing or unreadable, a block never
                closes, or the Unreleased section is missing or empty.
        """
        document = self.document()
        for line in document.unclosed_block_lines():
            self._ops.fail(
                f"CHANGELOG.md line {line} opens a code fence or HTML block "
                "that never closes"
            )
        unreleased = document.section("Unreleased")
        if unreleased is None:
            self._ops.fail("No [Unreleased] section in CHANGELOG.md")
        if not unreleased.has_entries:
            self._ops.fail("[Unreleased] section is empty — nothing to release")

    def notes_for(self, version: str) -> str:
        """Return the publishable notes for a released version.

        Raises:
            ReleaseError: The changelog is missing or unreadable, or the
                version section is absent or empty.
        """
        section = self.document().section(version)
        if section is None:
            self._ops.fail(f"CHANGELOG.md has no [{version}] section to publish")
        if not section.has_entries:
            self._ops.fail(f"CHANGELOG.md [{version}] section has no entries")
        return section.notes

    def stamp(self, version: str, today: str, *, dry_run: bool) -> None:
        """Stamp Unreleased as a dated version, preserving BOM and line endings.

        Leave an already dated version alone. A dry run only reports the stamp.

        Args:
            today: Release date in YYYY-MM-DD form.

        Raises:
            ReleaseError: The changelog is missing or unreadable, the version
                already has an undated heading, or Unreleased is absent.
            OSError: The updated changelog could not be written.
        """
        document = self.document()
        if document.is_stamped(version):
            self._ops.ok(f"CHANGELOG.md already stamped [{version}]")
            return
        if document.section(version) is not None:
            self._ops.fail(
                f"CHANGELOG.md [{version}] section has no date — date it "
                f"(`## [{version}] - YYYY-MM-DD`) or remove it before releasing"
            )
        if document.section("Unreleased") is None:
            self._ops.fail("No [Unreleased] section in CHANGELOG.md to stamp")
        if dry_run:
            self._ops.dry(f"CHANGELOG.md: [Unreleased] → [{version}] - {today}")
            return
        stamped = document.stamped(version, today)
        TextFile(self._root / "CHANGELOG.md").write(stamped)
        self._ops.ok(f"CHANGELOG.md: [{version}] - {today}")

    def add_unreleased_entry(self, line: str, *, category: str = "Changed") -> bool:
        """File a bullet under Unreleased without adding duplicates.

        Args:
            line: Bullet text without its list marker.
            category: Keep a Changelog subsection title.

        Returns:
            Whether the Unreleased section exists.

        Raises:
            ReleaseError: The file is missing, unreadable, or not UTF-8.
            OSError: The updated changelog could not be written.
        """
        filed = UnreleasedEntry(line, category=category).added_to(self.text())
        if filed is None:
            return False
        TextFile(self._root / "CHANGELOG.md").write(filed)
        return True

    def suggest_next_version(self, current: str) -> str:
        """Suggest the next version from the Unreleased entries.

        Raises:
            ReleaseError: The file is missing or unreadable, or a bump is
                needed but the current version is not MAJOR.MINOR.PATCH.
        """
        return self.document().suggest_next_version(current)

    def is_stamped(self, version: str) -> bool:
        """Check for a dated ``## [<version>] - YYYY-MM-DD`` heading.

        Raises:
            ReleaseError: The file is missing, unreadable, or not UTF-8.
        """
        return self.document().is_stamped(version)
