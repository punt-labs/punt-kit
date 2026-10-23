"""Parsing CHANGELOG.md text into versioned sections and their subsections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self, final

_STAMPED_HEADING = re.compile(r"## \[[^\]]*\] - \d{4}-\d{2}-\d{2}")

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
        """True for a dated ``## [X.Y.Z] - YYYY-MM-DD`` heading."""
        return _STAMPED_HEADING.fullmatch(self.heading) is not None

    def has_entries_under(self, name: str) -> bool:
        """True when a subsection titled ``name`` has at least one entry."""
        return any(sub.is_named(name) and sub.entries for sub in self.subsections)


@final
class ChangelogDocument:
    """The one parser for CHANGELOG.md: every reader goes through it.

    Splits text into ``## [version]`` sections and their ``###`` subsections
    while honoring fenced code blocks (a ``## [`` inside a fence is content),
    HTML comments, a leading UTF-8 BOM, and either line ending.
    """

    __slots__ = ("_lines", "_sections")

    _VERSION_HEADING = re.compile(r"## \[([^\]]*)\]")
    _SUBSECTION_HEADING = re.compile(r"###\s+(.*?)\s*$")
    _ANY_HEADING = re.compile(r"#{1,6}(?:\s|$)")
    _FENCE_OPEN = re.compile(r"\s*(`{3,}|~{3,})")
    # A Markdown link reference definition ("[Unreleased]: https://..."), the
    # footer Keep a Changelog files carry: bookkeeping, not an entry.
    _LINK_DEFINITION = re.compile(r"\[[^\]]+\]:\s")

    _lines: tuple[str, ...]
    _sections: tuple[Section, ...]

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._lines = tuple(text.removeprefix("\ufeff").splitlines(keepends=True))
        heads = cls._version_headings(self._lines)
        starts = [index for index, _ in heads]
        ends = [*starts[1:], len(self._lines)] if heads else []
        self._sections = tuple(
            cls._section(self._lines, version, start, end)
            for (start, version), end in zip(heads, ends, strict=True)
        )
        return self

    def section(self, version: str) -> Section | None:
        """The first section for ``version``; ``None`` is a legitimate absence."""
        return next((s for s in self._sections if s.version == version), None)

    def notes_for(self, version: str) -> str:
        """Release notes for ``version``, or a stub naming it when absent."""
        found = self.section(version)
        return found.notes if found is not None else f"Release v{version}"

    def is_stamped(self, version: str) -> bool:
        """True if a dated ``## [<version>] - YYYY-MM-DD`` heading exists."""
        return any(s.version == version and s.is_stamped for s in self._sections)

    def stamped(self, version: str, today: str) -> str:
        """Return the text with a new dated ``version`` heading under Unreleased.

        Inserts at the parsed [Unreleased] heading (never at a look-alike
        inside a code fence) and preserves the file's line endings. Text
        with no [Unreleased] section comes back unchanged.
        """
        unreleased = self.section("Unreleased")
        if unreleased is None:
            return "".join(self._lines)
        index = unreleased.line_index
        heading = self._lines[index]
        eol = "\r\n" if heading.endswith("\r\n") else "\n"
        return "".join(
            (
                *self._lines[:index],
                heading.rstrip("\r\n") + eol,
                eol,
                f"## [{version}] - {today}{eol}",
                *self._lines[index + 1 :],
            )
        )

    def suggest_next_version(self, current: str) -> str:
        """Suggest the next version from the [Unreleased] entries.

        No entries means nothing to release, so no bump. A ``Changed`` entry
        marked breaking is a major bump, entries under ``Added`` a minor
        one, anything else a patch.
        """
        unreleased = self.section("Unreleased")
        parts = current.split(".")
        if unreleased is None or not unreleased.has_entries or len(parts) != 3:
            return current
        major, minor, patch = (int(part) for part in parts)
        if unreleased.is_breaking:
            return f"{major + 1}.0.0"
        if unreleased.has_entries_under("added"):
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"

    @classmethod
    def _version_headings(cls, lines: tuple[str, ...]) -> list[tuple[int, str]]:
        """Every ``(line_index, version)`` heading that is outside a code fence."""
        found: list[tuple[int, str]] = []
        fence: str | None = None
        for index, line in enumerate(lines):
            fence, is_fence_line = cls._advance_fence(line, fence)
            if fence is None and not is_fence_line:
                match = cls._VERSION_HEADING.match(line)
                if match:
                    found.append((index, match.group(1)))
        return found

    @classmethod
    def _section(
        cls, lines: tuple[str, ...], version: str, start: int, end: int
    ) -> Section:
        body = lines[start + 1 : end]
        entries: list[str] = []
        titles: list[str] = []
        grouped: list[list[str]] = []
        for title, entry in cls._classify(body):
            if title is not None:
                titles.append(title)
                grouped.append([])
            else:
                entries.append(entry)
                if grouped:
                    grouped[-1].append(entry)
        return Section(
            version=version,
            heading=lines[start].rstrip("\r\n"),
            notes="".join(body).strip(),
            entries=tuple(entries),
            subsections=tuple(
                Subsection(title, tuple(group))
                for title, group in zip(titles, grouped, strict=True)
            ),
            line_index=start,
        )

    @classmethod
    def _classify(cls, body: tuple[str, ...]) -> list[tuple[str | None, str]]:
        """Label each body line: ``(title, "")`` for a ``###`` heading, or
        ``(None, text)`` for an entry; everything else is dropped.

        Dropped: blank lines, other headings, HTML comments (single- or
        multi-line), and link definitions. Everything inside a code fence is
        an entry.
        """
        labelled: list[tuple[str | None, str]] = []
        fence: str | None = None
        in_comment = False
        for raw in body:
            fence, is_fence_line = cls._advance_fence(raw, fence)
            if fence is not None or is_fence_line:
                labelled.append((None, raw.rstrip("\r\n")))
                continue
            text, in_comment = cls._without_comments(raw.rstrip("\r\n"), in_comment)
            if not text.strip():
                continue
            subsection = cls._SUBSECTION_HEADING.match(text)
            if subsection and not text.startswith("####"):
                labelled.append((subsection.group(1), ""))
            elif not (cls._ANY_HEADING.match(text) or cls._LINK_DEFINITION.match(text)):
                labelled.append((None, text))
        return labelled

    @classmethod
    def _advance_fence(cls, line: str, fence: str | None) -> tuple[str | None, bool]:
        """Advance the code-fence state over ``line``.

        Returns ``(fence, is_fence_line)``: the open fence marker (``None``
        when outside a fence) and whether ``line`` itself opens or closes
        one. A fence closes only on a line of the same character, at least
        as long as the opener.
        """
        if fence is None:
            opened = cls._FENCE_OPEN.match(line)
            return (opened.group(1), True) if opened else (None, False)
        stripped = line.strip()
        if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            return None, True
        return fence, False

    @staticmethod
    def _without_comments(line: str, in_comment: bool) -> tuple[str, bool]:
        """Strip HTML comment spans from ``line``, carrying multi-line state."""
        kept: list[str] = []
        rest = line
        while rest:
            if in_comment:
                end = rest.find("-->")
                if end < 0:
                    return "".join(kept), True
                rest, in_comment = rest[end + 3 :], False
            else:
                start = rest.find("<!--")
                if start < 0:
                    kept.append(rest)
                    break
                kept.append(rest[:start])
                rest, in_comment = rest[start + 4 :], True
        return "".join(kept), in_comment
