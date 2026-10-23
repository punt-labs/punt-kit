"""A git checkout on disk: the GitHub repository its origin remote names."""

from __future__ import annotations

import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Self, final

from punt_kit.phases.shared.repo_slug import RepoSlug


@final
class GitCheckout:
    """The checkout whose working tree should be rooted at ``root``."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def github_slug(self) -> str:
        """The clean ``owner/repo`` of origin.

        Raises ``ValueError`` saying why there is none: ``root`` is not the top
        of a git checkout, the checkout has no origin, or origin is not a
        GitHub ``owner/repo`` (another host, or a path of the wrong shape), in
        which case the message names the URL.
        """
        toplevel = self._git("rev-parse", "--show-toplevel")
        if toplevel is None or Path(toplevel).resolve() != self._root.resolve():
            msg = "no git repo at root"
            raise ValueError(msg)
        url = self._git("remote", "get-url", "origin")
        if url is None:
            msg = "no remote detected"
            raise ValueError(msg)
        slug = None
        with suppress(ValueError):
            slug = RepoSlug.from_remote_url(url)
        if slug is None:
            msg = f"origin remote is not a GitHub owner/repo: {url}"
            raise ValueError(msg)
        return str(slug)

    def _git(self, *args: str) -> str | None:
        """Stdout of ``git <args>`` run in ``root``; ``None`` if it fails."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None
