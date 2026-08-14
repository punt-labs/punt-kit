"""Tests for what the built artifacts are allowed to contain.

Hatchling's default sdist ships everything not VCS-ignored, which fails open:
any untracked file in the tree lands in a published tarball, permanently and
unlistably. These tests guard the explicit allowlist that closes that.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Top-level paths that must never reach a published artifact: local agent state,
# editor config, internal tracker content, and the environment file.
NEVER_SHIP = (
    ".beads",
    ".claude",
    ".CLAUDE.md.lock",
    ".envrc",
    ".idea",
    ".punt-labs",
    "resume.md",
)


def _sdist_include() -> list[str]:
    """The declared sdist allowlist, read from pyproject.toml."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as fh:
        node: object = tomllib.load(fh)
    for key in ("tool", "hatch", "build", "targets", "sdist", "include"):
        assert isinstance(node, dict), f"pyproject.toml: {key} has no parent table"
        table = cast("dict[str, object]", node)
        assert key in table, f"pyproject.toml is missing {key}"
        node = table[key]
    assert isinstance(node, list), "sdist include must be a list"
    return [str(entry) for entry in cast("list[object]", node)]


def test_sdist_declares_an_explicit_allowlist() -> None:
    """Without this block hatchling ships every untracked file in the tree."""
    assert _sdist_include(), "sdist include list must not be empty"


def test_sdist_allowlist_excludes_sensitive_paths() -> None:
    """The allowlist must not readmit the paths it exists to keep out."""
    include = _sdist_include()
    for entry in include:
        top = entry.lstrip("/").split("/")[0]
        assert top not in NEVER_SHIP, f"{entry} would publish {top}"


def test_sdist_allowlist_ships_what_the_package_needs() -> None:
    """A too-narrow allowlist breaks the build as surely as a missing one."""
    include = {entry.lstrip("/") for entry in _sdist_include()}
    for required in ("src", "tests", "README.md", "LICENSE"):
        assert required in include, f"sdist must ship {required}"


def test_allowlist_entries_exist_in_the_tree() -> None:
    """An entry naming a path that no longer exists is silently doing nothing."""
    for entry in _sdist_include():
        assert (PROJECT_ROOT / entry.lstrip("/")).exists(), f"{entry} not found"
