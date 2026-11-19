"""Resolve the GitHub origin remote for a git checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Self, final

from punt_kit.phases.shared.repo_slug import RepoSlug


@final
class GitCheckout:
    """Inspect the checkout whose working tree should be rooted at ``root``."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, root: Path) -> Self:
        """Describe the checkout expected at ``root``."""
        self = super().__new__(cls)
        self._root = root
        return self

    def github_slug(self) -> str:
        """Return the clean ``owner/repo`` of origin.

        Raises:
            ValueError: Git cannot run, the path is not a checkout root,
                or origin cannot be resolved to a GitHub repository.
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
            shown = RepoSlug.without_userinfo(url)
            msg = f"origin remote is not a GitHub owner/repo: {shown}"
            raise ValueError(msg)
        return str(slug)

    def _require_toplevel(self) -> None:
        if not self._root.is_dir():
            msg = "no git repo at root"
            raise ValueError(msg)
        result = self._git("rev-parse", "--show-toplevel")
        if result.returncode != 0:
            complaint = result.stderr.strip()
            # git's wording is fixed by LC_ALL=C; any other refusal (dubious
            # ownership, a broken config) is not "no repo" and says what it is.
            if "not a git repository" not in complaint:
                msg = f"git rev-parse --show-toplevel failed: {complaint}"
                raise ValueError(msg)
            msg = "no git repo at root"
            raise ValueError(msg)
        if Path(result.stdout.strip()).resolve() != self._root.resolve():
            msg = "no git repo at root"
            raise ValueError(msg)

    def _origin_url(self) -> str:
        result = self._git("remote", "get-url", "origin")
        if result.returncode == 0:
            return result.stdout.strip()
        complaint = result.stderr.strip()
        if "No such remote" in complaint:
            msg = "no remote detected"
        else:
            msg = f"git remote get-url origin failed: {complaint}"
        raise ValueError(msg)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run git in the C locale; raise ``ValueError`` if it cannot finish."""
        command = f"git {' '.join(args)}"
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"{command} did not finish"
            raise ValueError(msg) from exc
        except OSError as exc:
            msg = f"git is not installed or cannot run ({exc})"
            raise ValueError(msg) from exc
