"""Tests for a git checkout's GitHub origin."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit.git_checkout import GitCheckout

if TYPE_CHECKING:
    from pathlib import Path


def _checkout(tmp_path: Path, remote: str | None) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    if remote is not None:
        subprocess.run(
            ["git", "remote", "add", "origin", remote], cwd=tmp_path, check=True
        )
    return tmp_path


@pytest.mark.parametrize(
    ("remote", "slug"),
    [
        pytest.param("https://github.com/o/r/", "o/r", id="trailing-slash"),
        pytest.param("git@github.com:o/r.git/", "o/r", id="scp-dot-git-slash"),
        pytest.param("https://github.com/o/r.git", "o/r", id="dot-git"),
    ],
)
def test_github_slug_is_clean(tmp_path: Path, remote: str, slug: str) -> None:
    """The audit builds ``repos/{slug}/...`` URLs, so the slug must be clean."""
    assert GitCheckout(_checkout(tmp_path, remote)).github_slug() == slug


def test_github_slug_says_when_there_is_no_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^no remote detected$"):
        GitCheckout(_checkout(tmp_path, None)).github_slug()


def test_github_slug_says_when_root_is_a_subdirectory_of_a_checkout(
    tmp_path: Path,
) -> None:
    sub = _checkout(tmp_path, "https://github.com/o/r") / "pkg"
    sub.mkdir()
    with pytest.raises(ValueError, match="^no git repo at root$"):
        GitCheckout(sub).github_slug()


def test_github_slug_says_when_root_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^no git repo at root$"):
        GitCheckout(tmp_path / "absent").github_slug()


@pytest.mark.parametrize(
    "remote",
    [
        pytest.param("https://github.com/proj", id="no-owner"),
        pytest.param("https://github.com/o/r/extra", id="three-parts"),
        pytest.param("https://gitlab.com/o/r", id="other-host"),
    ],
)
def test_github_slug_names_an_origin_that_is_not_a_github_owner_repo(
    tmp_path: Path, remote: str
) -> None:
    with pytest.raises(ValueError, match=f"^origin remote is not .*: {remote}$"):
        GitCheckout(_checkout(tmp_path, remote)).github_slug()
