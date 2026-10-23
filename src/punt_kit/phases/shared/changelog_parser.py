"""Parsing CHANGELOG.md text into versioned sections and their subsections."""

from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING, Self, final

from markdown_it import MarkdownIt

from punt_kit.phases.shared.changelog_sections import Section, Subsection

if TYPE_CHECKING:
    from markdown_it.token import Token

_MARKDOWN = MarkdownIt("commonmark")
_VERSION = re.compile(r"\[([^\]]*)\]")

# Block tokens that open a list (descended into) and that are code (an entry).
_LIST_OPENERS = frozenset({"bullet_list_open", "ordered_list_open"})
_DESCENDED = _LIST_OPENERS | {"list_item_open"}
_CODE_BLOCKS = frozenset({"fence", "code_block", "hr"})


@final
class ChangelogDocument:
    """The one parser for CHANGELOG.md: every reader goes through it.

    Structure comes from a CommonMark parse (markdown-it-py), not from
    scanning lines: a ``## [version]`` heading, a ``###`` subsection, and an
    entry are block tokens, so what counts as a fence or an HTML comment is
    decided by the CommonMark spec. A fence or comment that is never closed
    runs to the end of the document, hiding every later release; callers see
    those releases as missing rather than as a phantom section. The text is
    kept by line, so a leading UTF-8 BOM and either line ending survive the
    Phase 2 stamp.
    """

    __slots__ = ("_bom", "_lines", "_sections", "_tokens")

    _bom: str
    _lines: tuple[str, ...]
    _sections: tuple[Section, ...]
    _tokens: tuple[Token, ...]

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._bom = "\ufeff" if text.startswith("\ufeff") else ""
        body = text.removeprefix("\ufeff")
        # markdown-it numbers lines by \n, \r\n and \r, which is exactly what
        # newline="" iteration yields; str.splitlines() would also split on
        # form feeds and U+2028 and drift from the token line maps.
        self._lines = tuple(io.StringIO(body, newline=""))
        self._tokens = tuple(_MARKDOWN.parse(body))
        heads = [
            (index, version)
            for index in range(len(self._tokens))
            if (version := self._version_of(index)) is not None
        ]
        bounds = [index for index, _ in heads] + [len(self._tokens)]
        self._sections = tuple(
            self._section(start, stop, version)
            for (start, version), stop in zip(heads, bounds[1:], strict=True)
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
        eol = heading[len(heading.rstrip("\r\n")) :] or "\n"
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

    def _version_of(self, index: int) -> str | None:
        """The version in a top-level ``## [version]`` heading, else ``None``.

        Only an ATX heading counts: a setext underline would make the stamp's
        one-line insertion split the heading.
        """
        token = self._tokens[index]
        if (
            token.type != "heading_open"
            or token.tag != "h2"
            or token.level != 0
            or not token.markup.startswith("#")
        ):
            return None
        match = _VERSION.match(self._tokens[index + 1].content)
        return match.group(1) if match else None

    def _section(self, first: int, stop: int, version: str) -> Section:
        """Build the section whose tokens are ``tokens[first:stop]``.

        Its notes end where the token at ``stop`` (the next version heading)
        begins, or at the end of the text.
        """
        start, end = self._span(self._tokens[first])
        last = (
            self._span(self._tokens[stop])[0]
            if stop < len(self._tokens)
            else len(self._lines)
        )
        entries: list[str] = []
        titles: list[str] = []
        grouped: list[list[str]] = []
        for title, entry in self._classify(first + 3, stop):
            if title is not None:
                titles.append(title)
                grouped.append([])
            else:
                entries.append(entry)
                if grouped:
                    grouped[-1].append(entry)
        return Section(
            version=version,
            heading=self._lines[start].rstrip("\r\n"),
            notes="".join(self._lines[end:last]).strip(),
            entries=tuple(entries),
            subsections=tuple(
                Subsection(title, tuple(group))
                for title, group in zip(titles, grouped, strict=True)
            ),
            line_index=start,
        )

    def _classify(self, first: int, stop: int) -> list[tuple[str | None, str]]:
        """Label the tokens ``[first, stop)``: ``(title, "")`` for a ``###``
        heading, or ``(None, text)`` for an entry; everything else is dropped.

        An entry is a list item (nested items count on their own), or any
        other top-level block with visible content: a paragraph, a fence, a
        quote. Other headings, comment-only blocks, and link definitions
        (which CommonMark consumes without a token) are not entries.
        """
        labelled: list[tuple[str | None, str]] = []
        index = first
        while index < stop:
            token = self._tokens[index]
            close = self._close_of(index)
            if token.type == "heading_open" and token.level == 0:
                title = self._subsection_title(index)
                if title is not None:
                    labelled.append((title, ""))
            elif self._is_entry_block(token) and self._has_content(index, close + 1):
                labelled.append((None, self._text(token)))
            # Lists are walked into: nested items are entries too.
            index = index + 1 if token.type in _DESCENDED else close + 1
        return labelled

    @staticmethod
    def _is_entry_block(token: Token) -> bool:
        """True for a list item at any depth, or a top-level non-list block."""
        if token.type == "list_item_open":
            return True
        return token.level == 0 and token.type not in _LIST_OPENERS

    @staticmethod
    def _span(token: Token) -> tuple[int, int]:
        """The ``[first, end)`` source lines of a block token."""
        if token.map is None:
            msg = f"block token {token.type!r} has no line map"
            raise ValueError(msg)
        first, end = token.map
        return first, end

    def _text(self, token: Token) -> str:
        """The source text of a block token, without its trailing line ending."""
        first, end = self._span(token)
        return "".join(self._lines[first:end]).rstrip("\r\n")

    def _close_of(self, index: int) -> int:
        """Index of the token closing ``tokens[index]``; itself for a leaf."""
        token = self._tokens[index]
        if token.nesting != 1:
            return index
        closer = token.type.removesuffix("_open") + "_close"
        return next(
            i
            for i in range(index + 1, len(self._tokens))
            if self._tokens[i].type == closer and self._tokens[i].level == token.level
        )

    def _subsection_title(self, index: int) -> str | None:
        """The title of a ``###`` ATX heading at ``index`` (comments left out)."""
        token = self._tokens[index]
        if token.tag != "h3" or not token.markup.startswith("#"):
            return None
        return "".join(
            child.content
            for child in self._tokens[index + 1].children or []
            if child.type != "html_inline"
        ).strip()

    def _has_content(self, first: int, end: int) -> bool:
        """True when tokens ``[first, end)`` carry something a reader sees.

        Comment-only blocks, empty list items, and blank text do not count.
        """
        return any(self._shows(token) for token in self._tokens[first:end])

    @classmethod
    def _shows(cls, token: Token) -> bool:
        """True when this one token renders something a reader sees."""
        if token.type == "inline":
            return any(cls._is_visible(child) for child in token.children or [])
        if token.type == "html_block":
            return not cls._is_comment(token)
        return token.type in _CODE_BLOCKS

    @staticmethod
    def _is_comment(token: Token) -> bool:
        return token.content.lstrip().startswith("<!--")

    @classmethod
    def _is_visible(cls, child: Token) -> bool:
        """True for an inline token that renders: not a comment or whitespace."""
        if child.type == "html_inline":
            return not cls._is_comment(child)
        if child.type in ("softbreak", "hardbreak"):
            return False
        return bool(child.content.strip()) if child.type == "text" else True
