"""CHANGELOG.md file access: reading, the preflight gate, and version facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.changelog_parser import ChangelogDocument

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
        return changelog.read_text(encoding="utf-8")

    def document(self) -> ChangelogDocument:
        """Parse CHANGELOG.md; callers that ask several questions parse once."""
        return ChangelogDocument(self.text())

    def require_unreleased_entries(self) -> None:
        """Fail unless the changelog has an [Unreleased] section with entries.

        Reads CHANGELOG.md once. Fails with ``No [Unreleased] section in
        CHANGELOG.md`` when no such heading starts a line outside a code
        fence, and with ``[Unreleased] section is empty — nothing to
        release`` when the section has no entry: headings and HTML comments
        alone do not count.
        """
        unreleased = self.document().section("Unreleased")
        if unreleased is None:
            self._ops.fail("No [Unreleased] section in CHANGELOG.md")
        if not unreleased.has_entries:
            self._ops.fail("[Unreleased] section is empty — nothing to release")

    def notes_for(self, version: str) -> str:
        """Release notes for ``version``, or ``Release v<version>`` when absent."""
        return self.document().notes_for(version)

    def suggest_next_version(self, current: str) -> str:
        """Suggest the next version from the [Unreleased] entries."""
        return self.document().suggest_next_version(current)

    def is_stamped(self, version: str) -> bool:
        """True if ``## [<version>] - YYYY-MM-DD`` appears in the changelog."""
        return self.document().is_stamped(version)
