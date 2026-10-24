"""CHANGELOG.md file access: reading, the preflight gate, and version facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.changelog_parser import ChangelogDocument
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class Changelog:
    """Reads a project's CHANGELOG.md and answers questions about it.

    Every answer comes from ``ChangelogDocument``, the one parser; this
    class only owns locating and reading the file.
    """

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def text(self) -> str:
        """Read CHANGELOG.md content."""
        changelog = self._root / "CHANGELOG.md"
        if not changelog.exists():
            self._ops.fail("CHANGELOG.md not found")
        return TextFile(changelog).read()

    def document(self) -> ChangelogDocument:
        """Parse CHANGELOG.md; callers that ask several questions parse once."""
        return ChangelogDocument(self.text())

    def require_unreleased_entries(self) -> None:
        """Fail unless the changelog has an [Unreleased] section with entries.

        Reads CHANGELOG.md once. Fails when a code fence or HTML block opens
        and never closes (it would swallow every older release), with ``No
        [Unreleased] section in CHANGELOG.md`` when no such heading starts a
        line outside a code fence, and with ``[Unreleased] section is empty
        — nothing to release`` when the section has no entry: headings and
        HTML comments alone do not count.
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
        """Release notes for ``version``; fail when there is nothing to publish."""
        section = self.document().section(version)
        if section is None:
            self._ops.fail(f"CHANGELOG.md has no [{version}] section to publish")
        if not section.has_entries:
            self._ops.fail(f"CHANGELOG.md [{version}] section has no entries")
        return section.notes

    def stamp(self, version: str, today: str, *, dry_run: bool) -> None:
        """Stamp ``[Unreleased]`` as ``version``, unless it already is.

        A resumed Phase 2 finds the version section already there and leaves
        the file alone; a changelog with no ``[Unreleased]`` section cannot be
        stamped and fails. The file's BOM and line endings are kept.
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

    def suggest_next_version(self, current: str) -> str:
        """Suggest the next version from the [Unreleased] entries."""
        return self.document().suggest_next_version(current)

    def is_stamped(self, version: str) -> bool:
        """True for a dated ``## [<version>] - YYYY-MM-DD`` heading; text may follow."""
        return self.document().is_stamped(version)
