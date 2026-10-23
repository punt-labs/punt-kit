"""A GitHub ``owner/repo`` slug, parsed once so no caller splits text itself."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

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
        path ``owner/repo/``; stripping here is what makes every consumer see
        the same slug. Raises ``ValueError`` unless exactly one owner and one
        repo name remain.
        """
        parts = raw.strip().strip("/").split("/")
        if len(parts) != 2 or not all(
            _NAME.fullmatch(part) and part not in _PATH_COMPONENTS for part in parts
        ):
            msg = f"not an owner/repo slug: {raw!r}"
            raise ValueError(msg)
        return cls(parts[0], parts[1])

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}"
