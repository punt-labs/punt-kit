"""A GitHub ``owner/repo`` slug, parsed once so no caller splits text itself."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self
from urllib.parse import urlparse

# GitHub owners and repositories are made of word characters, dots, and
# hyphens; "." and ".." are path components, never names.
_NAME = re.compile(r"[\w.-]+")
_PATH_COMPONENTS = frozenset({".", ".."})


@dataclass(frozen=True, slots=True)
class RepoSlug:
    """The owner and repository halves of ``owner/repo``."""

    owner: str
    name: str

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Parse ``raw`` after stripping surrounding whitespace and slashes.

        A remote URL such as ``https://github.com/owner/repo/`` yields the
        path ``owner/repo/``, and an scp-style one ``owner/repo.git/``;
        stripping here is what makes every consumer see the same slug.
        Raises ``ValueError`` unless exactly one owner and one repo name
        remain.
        """
        parts = raw.strip().strip("/").removesuffix(".git").split("/")
        if len(parts) != 2 or not all(
            _NAME.fullmatch(part) and part not in _PATH_COMPONENTS for part in parts
        ):
            msg = f"not an owner/repo slug: {raw!r}"
            raise ValueError(msg)
        return cls(parts[0], parts[1])

    @classmethod
    def from_remote_url(cls, url: str) -> Self | None:
        """The slug of a github.com remote URL (https, ssh or scp-style).

        ``None`` when the URL is not on github.com or names no path. Raises
        ``ValueError`` when it is on github.com but the path is not
        ``owner/repo``.
        """
        url = url.strip()
        if url.startswith("git@github.com:"):
            return cls.parse(url.removeprefix("git@github.com:"))
        parsed = urlparse(url)
        if parsed.hostname != "github.com" or not parsed.path.strip("/"):
            return None
        return cls.parse(parsed.path.lstrip("/"))

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}"
