"""A git checkout on disk: the GitHub repository its origin remote names."""

from __future__ import annotations

import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Self, final
from urllib.parse import urlsplit

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

        Raises ``ValueError`` saying why there is none: git is not installed,
        ``root`` is not the top of a git checkout, the checkout has no origin
        (or git could not read it), or origin is not a GitHub ``owner/repo``,
        in which case the message names the URL with any credentials removed.
        """
        if shutil.which("git") is None:
            msg = "git is not installed"
            raise ValueError(msg)
        self._require_toplevel()
        url = self._origin_url()
        slug = None
        with suppress(ValueError):
            slug = RepoSlug.from_remote_url(url)
        if slug is None:
            shown = self._without_userinfo(url)
            msg = f"origin remote is not a GitHub owner/repo: {shown}"
            raise ValueError(msg)
        return str(slug)

    def _require_toplevel(self) -> None:
        result = self._git("rev-parse", "--show-toplevel")
        if (
            result is None
            or result.returncode != 0
            or Path(result.stdout.strip()).resolve() != self._root.resolve()
        ):
            msg = "no git repo at root"
            raise ValueError(msg)

    def _origin_url(self) -> str:
        result = self._git("remote", "get-url", "origin")
        if result is None:
            msg = "git remote get-url origin did not finish"
            raise ValueError(msg)
        if result.returncode == 0:
            return result.stdout.strip()
        complaint = result.stderr.strip()
        if "No such remote" in complaint:
            msg = "no remote detected"
        else:
            msg = f"git remote get-url origin failed: {complaint}"
        raise ValueError(msg)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        """``git <args>`` run in ``root``; ``None`` if it timed out or cannot start."""
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

    @staticmethod
    def _without_userinfo(url: str) -> str:
        """``url`` without a ``user:token@`` prefix on its host."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return "<unparseable url>"  # never echo what could not be parsed
        host = parts.netloc.rpartition("@")[2]
        return parts._replace(netloc=host).geturl()
