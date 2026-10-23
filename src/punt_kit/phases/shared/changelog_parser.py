"""Parsing CHANGELOG.md text into versioned sections and their subsections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self, final

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


@final
class ChangelogDocument:
    """The one parser for CHANGELOG.md: every reader goes through it.

    Splits text into ``## [version]`` sections and their ``###`` subsections
    while honoring fenced code blocks (a ``## [`` inside a fence is content),
    HTML comments, a leading UTF-8 BOM, and either line ending.
    """

    __slots__ = ("_bom", "_lines", "_sections")

    _VERSION_HEADING = re.compile(r"## \[([^\]]*)\]")
    _SUBSECTION_HEADING = re.compile(r"###\s+(.*?)\s*$")
    _ANY_HEADING = re.compile(r"#{1,6}(?:\s|$)")
    _FENCE_OPEN = re.compile(r"\s*(`{3,}|~{3,})")
    # A Markdown link reference definition ("[Unreleased]: https://..."), the
    # footer Keep a Changelog files carry: bookkeeping, not an entry.
    _LINK_DEFINITION = re.compile(r"\[[^\]]+\]:\s")

    _bom: str
    _lines: tuple[str, ...]
    _sections: tuple[Section, ...]

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._bom = "\ufeff" if text.startswith("\ufeff") else ""
        self._lines = tuple(text.removeprefix("\ufeff").splitlines(keepends=True))
        # One scan decides, for every line, whether it is code and what text
        # is visible once comments are removed. Headings and entries are both
        # read from it, so they cannot disagree about fences or comments.
        scanned = cls._scan(self._lines)
        heads = [
            (index, match.group(1))
            for index, (is_code, text) in enumerate(scanned)
            if not is_code and (match := cls._VERSION_HEADING.match(text))
        ]
        starts = [index for index, _ in heads]
        ends = [*starts[1:], len(self._lines)] if heads else []
        self._sections = tuple(
            cls._section(self._lines, scanned, version, start, end)
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
        inside a code fence) and preserves the file's BOM and line endings.
        Text with no [Unreleased] section comes back unchanged.
        """
        unreleased = self.section("Unreleased")
        if unreleased is None:
            return self._bom + "".join(self._lines)
        index = unreleased.line_index
        heading = self._lines[index]
        eol = "\r\n" if heading.endswith("\r\n") else "\n"
        return self._bom + "".join(
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
    def _scan(cls, lines: tuple[str, ...]) -> tuple[tuple[bool, str], ...]:
        """Label every line ``(is_code, visible_text)`` in one pass.

        Code is a fenced block (delimiters included) and keeps its text
        verbatim. Outside code, HTML comments — single- or multi-line — are
        removed from the text. A fence or comment that is never closed is
        plain text, not a state that runs to the end of the file: swallowing
        every later release over one stray backtick fence would hide
        published versions, so an opener only counts when a closer follows.
        """
        closes_later = [False] * len(lines)
        seen_close = False
        for index in range(len(lines) - 1, -1, -1):
            closes_later[index] = seen_close
            seen_close = seen_close or "-->" in lines[index]
        scanned: list[tuple[bool, str]] = []
        fence: str | None = None
        in_comment = False
        for index, raw in enumerate(lines):
            line = raw.rstrip("\r\n")
            if fence is not None:
                if cls._closes_fence(line, fence):
                    fence = None
                scanned.append((True, line))
                continue
            opened = None if in_comment else cls._FENCE_OPEN.match(line)
            if opened and cls._fence_is_closed(lines, index, opened.group(1)):
                fence = opened.group(1)
                scanned.append((True, line))
                continue
            text, in_comment = cls._without_comments(
                line, in_comment, closable=closes_later[index]
            )
            scanned.append((False, text))
        return tuple(scanned)

    @classmethod
    def _section(
        cls,
        lines: tuple[str, ...],
        scanned: tuple[tuple[bool, str], ...],
        version: str,
        start: int,
        end: int,
    ) -> Section:
        body = lines[start + 1 : end]
        entries: list[str] = []
        titles: list[str] = []
        grouped: list[list[str]] = []
        for title, entry in cls._classify(scanned[start + 1 : end]):
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
    def _classify(
        cls, body: tuple[tuple[bool, str], ...]
    ) -> list[tuple[str | None, str]]:
        """Label each scanned line: ``(title, "")`` for a ``###`` heading, or
        ``(None, text)`` for an entry; everything else is dropped.

        Dropped: blank lines, other headings, comments (already removed by
        the scan), and link definitions. Everything inside a code fence is an
        entry.
        """
        labelled: list[tuple[str | None, str]] = []
        for is_code, text in body:
            if is_code:
                labelled.append((None, text))
                continue
            if not text.strip():
                continue
            subsection = cls._SUBSECTION_HEADING.match(text)
            if subsection and not text.startswith("####"):
                labelled.append((subsection.group(1), ""))
            elif not (cls._ANY_HEADING.match(text) or cls._LINK_DEFINITION.match(text)):
                labelled.append((None, text))
        return labelled

    @staticmethod
    def _closes_fence(line: str, fence: str) -> bool:
        """True when ``line`` closes ``fence``: same character, at least as long."""
        stripped = line.strip()
        return (
            bool(stripped)
            and set(stripped) == {fence[0]}
            and len(stripped) >= len(fence)
        )

    @classmethod
    def _fence_is_closed(cls, lines: tuple[str, ...], opener: int, fence: str) -> bool:
        """True when some line after ``opener`` closes ``fence``."""
        return any(cls._closes_fence(line, fence) for line in lines[opener + 1 :])

    @staticmethod
    def _without_comments(
        line: str, in_comment: bool, *, closable: bool
    ) -> tuple[str, bool]:
        """Strip HTML comment spans from ``line``, carrying multi-line state.

        ``closable`` says whether a later line contains ``-->``; an opener
        that nothing closes is left in the text.
        """
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
                if "-->" not in rest[start + 4 :] and not closable:
                    kept.append(rest)
                    break
                kept.append(rest[:start])
                rest, in_comment = rest[start + 4 :], True
        return "".join(kept), in_comment
