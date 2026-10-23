"""Deciding which marketplace or website entry belongs to a project, by full slug."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

from punt_kit.phases.shared.repo_slug import RepoSlug

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class EntryMatcher:
    """Matches entries named for this project, or sourced from its own owner/repo.

    A source URL claims the project only when it parses to ``owner/repo`` for
    this project's own owner and repository: a same-named repository under
    someone else is not this project, and neither is another repository of
    the owner. ``names`` are the entry names the project goes by (its repository
    name and its marketplace short name); they match an entry's ``name`` or
    ``id`` field and never a repository.
    """

    owner: str
    repo: str
    names: frozenset[str]

    @classmethod
    def for_marketplace(
        cls,
        slug: RepoSlug,
        # Absent is a real answer: a project with no plugin manifest has no
        # marketplace short name, only its repository name.
        marketplace_name: str | None,
    ) -> Self:
        """The matcher for a project's marketplace entry.

        Built from the repository (the origin slug) and the plugin's
        marketplace short name, not the PyPI distribution name: entries key
        on ``punt``, not ``punt-kit``. Phases 10 and 11 both build theirs
        here, so the entry one writes is the entry the other verifies.
        """
        names = frozenset(n for n in (marketplace_name, slug.name) if n)
        return cls(slug.owner, slug.name, names)

    @classmethod
    def for_website(cls, slug: RepoSlug) -> Self:
        """The matcher for a project's website entry: its id is the repo name."""
        return cls(slug.owner, slug.name, frozenset({slug.name}))

    def claims_url(self, url: str) -> bool:
        """True when ``url`` is a github.com remote for ``owner/repo``."""
        try:
            slug = RepoSlug.from_remote_url(url)
        except ValueError:
            return False
        return (
            slug is not None
            and slug.owner.lower() == self.owner.lower()
            and slug.name.lower() == self.repo.lower()
        )

    def claims_plugin(self, plugin: Mapping[str, object]) -> bool:
        """True for a marketplace entry named for the project or sourced from it."""
        source = plugin.get("source")
        url = (
            cast("dict[str, object]", source).get("url")
            if isinstance(source, dict)
            else None
        )
        return self._is_named(plugin.get("name")) or self.claims_url(str(url or ""))

    def claims_website(self, entry: Mapping[str, object]) -> bool:
        """True for a website entry whose id or GitHub URL is the project's."""
        return self._is_named(entry.get("id")) or self.claims_url(
            str(entry.get("githubUrl") or "")
        )

    def _is_named(self, value: object) -> bool:
        """True when ``value`` (a JSON name field) is one of ``names``."""
        return isinstance(value, str) and value in self.names
