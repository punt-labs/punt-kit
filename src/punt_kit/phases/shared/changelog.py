"""CHANGELOG.md reading, notes extraction, and version-bump suggestion."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


def extract_version_notes(changelog: str, version: str) -> str:
    """Extract release notes for a specific version from changelog text.

    Pure string transform — legitimate PY-OO-7 exception: it shares no
    vocabulary with ``Changelog``'s fields, only the text a caller already
    has in hand (``Changelog.notes_for`` reads the file, then delegates
    here; tests exercise this directly against fabricated text with no
    file at all).
    """
    pattern = rf"## \[{re.escape(version)}\][^\n]*\n"
    match = re.search(pattern, changelog)
    if not match:
        return f"Release v{version}"

    start = match.end()
    next_heading = re.search(r"\n## \[", changelog[start:])
    end = start + next_heading.start() if next_heading else len(changelog)
    return changelog[start:end].strip()


def suggest_next_version(changelog: str, current: str) -> str:
    """Suggest a version bump based on changelog content. Pure string transform."""
    unreleased = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased:
        return current

    content = unreleased.group(1)
    parts = current.split(".")
    if len(parts) != 3:
        return current

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    # Check for breaking changes only within the ### Changed subsection
    changed_match = re.search(r"### Changed\n(.*?)(?=\n### |\Z)", content, re.DOTALL)
    has_breaking = (
        changed_match is not None and "breaking" in changed_match.group(1).lower()
    )
    if has_breaking:
        return f"{major + 1}.0.0"
    if "### Added" in content:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


@final
class Changelog:
    """Reads and interprets a project's CHANGELOG.md."""

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

    def has_unreleased_entries(self) -> bool:
        content = self.text()
        if "## [Unreleased]" not in content:
            return False
        match = re.search(
            r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", content, re.DOTALL
        )
        return bool(match and match.group(1).strip())

    def notes_for(self, version: str) -> str:
        return extract_version_notes(self.text(), version)

    def suggest_next_version(self, current: str) -> str:
        return suggest_next_version(self.text(), current)

    def is_stamped(self, version: str) -> bool:
        """True if ``## [<version>] - YYYY-MM-DD`` appears in the changelog."""
        return bool(
            re.search(
                rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}",
                self.text(),
                re.MULTILINE,
            )
        )
