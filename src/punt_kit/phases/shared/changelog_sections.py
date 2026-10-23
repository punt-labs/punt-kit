"""The parsed shape of a changelog: versioned sections and their subsections."""

from __future__ import annotations

import re
from dataclasses import dataclass

# A date after the version stamps the heading; whatever follows it ("  ",
# " (yanked)") does not matter, so the check is a prefix match.
_STAMPED_HEADING = re.compile(r"## \[[^\]]*\] - \d{4}-\d{2}-\d{2}(?!\d)")

# How the fleet marks a breaking change (surveyed across the sibling repos'
# CHANGELOG.md files): a bold ``**Breaking:**`` / ``**BREAKING —`` lead-in,
# a bullet that opens with the word, or a ``### Changed (BREAKING)``
# heading. The bare word elsewhere in prose ("Non-breaking tweak", "fixed a
# breaking regression") is not a marker.
_BREAKING_ENTRY = re.compile(r"(?:\*\*|^\s*[-*+]\s+)breaking\b", re.IGNORECASE)
_BREAKING_HEADING = re.compile(r"\(breaking\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Subsection:
    """One ``### Title`` block and the entry lines under it."""

    title: str
    entries: tuple[str, ...]

    def is_named(self, name: str) -> bool:
        """True when the title starts with ``name`` (``Changed (BREAKING)``)."""
        return self.title.lower().startswith(name.lower())

    @property
    def is_breaking(self) -> bool:
        """True for a ``Changed`` block that marks a breaking change."""
        return self.is_named("changed") and (
            _BREAKING_HEADING.search(self.title) is not None
            or any(_BREAKING_ENTRY.search(entry) for entry in self.entries)
        )


@dataclass(frozen=True, slots=True)
class Section:
    """One ``## [version]`` block of a changelog."""

    version: str
    heading: str
    notes: str
    entries: tuple[str, ...]
    subsections: tuple[Subsection, ...]
    line_index: int

    @property
    def has_entries(self) -> bool:
        """True when at least one line is a real entry.

        Blank lines, headings, HTML comments, and link definitions are not
        entries: a section of bare ``### Added`` headings has nothing to
        release.
        """
        return bool(self.entries)

    @property
    def is_breaking(self) -> bool:
        return any(sub.is_breaking for sub in self.subsections)

    @property
    def is_stamped(self) -> bool:
        """True for a ``## [X.Y.Z] - YYYY-MM-DD`` heading, trailing text allowed."""
        return _STAMPED_HEADING.match(self.heading) is not None

    def has_entries_under(self, name: str) -> bool:
        """True when a subsection titled ``name`` has at least one entry."""
        return any(sub.is_named(name) and sub.entries for sub in self.subsections)
