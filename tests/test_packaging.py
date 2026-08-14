"""Tests for what the built artifacts are allowed to contain.

punt-kit previously used hatchling, whose default sdist ships everything not
VCS-ignored. That fails open: any untracked file in the tree lands in a
published tarball, permanently and unlistably — and it did, in 0.12.0.

The fix was an explicit allowlist; the durable fix is a backend that ships a
declared module and nothing else. These tests guard the backend choice, since
under `uv_build` there is no allowlist left to guard. See DES-026.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Top-level paths that must never reach a published artifact: local agent
# state, editor config, internal tracker content, and the environment file.
NEVER_SHIP = (
    ".beads",
    ".claude",
    ".CLAUDE.md.lock",
    ".envrc",
    ".idea",
    ".punt-labs",
    "resume.md",
)


def _pyproject() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as fh:
        return cast("dict[str, object]", tomllib.load(fh))


def _table(data: dict[str, object], *keys: str) -> dict[str, object] | None:
    """Walk a nested TOML table, returning None if any level is absent."""
    node: dict[str, object] = data
    for key in keys:
        child = node.get(key)
        if not isinstance(child, dict):
            return None
        node = cast("dict[str, object]", child)
    return node


def test_build_backend_fails_closed() -> None:
    """uv_build ships the declared module; hatchling ships the whole tree.

    The distinction is the default, not the configuration: a backend that
    ships everything unless told otherwise puts every untracked file one
    release away from a public index.
    """
    build_system = _table(_pyproject(), "build-system")
    assert build_system is not None
    assert build_system["build-backend"] == "uv_build"


def test_module_is_declared() -> None:
    """uv_build ships what module-name names, so it must be named."""
    backend = _table(_pyproject(), "tool", "uv", "build-backend")
    assert backend is not None
    assert backend["module-name"] == "punt_kit"


def test_no_stale_hatch_configuration() -> None:
    """Leftover hatch tables would be inert config that reads as protection.

    A `[tool.hatch.build.targets.sdist]` allowlist under a uv_build project
    does nothing, but anyone auditing the file would conclude the sdist is
    scoped. Same failure mode as a permission rule that matches nothing.
    """
    assert _table(_pyproject(), "tool", "hatch") is None


def test_license_ships_in_the_artifact() -> None:
    """Named explicitly because the backend change silently dropped it.

    hatchling included LICENSE in dist-info without being asked; uv_build
    does not. The migration lost it until PEP 639 `license-files` was added,
    which is a licensing regression rather than a packaging detail.
    """
    project = _table(_pyproject(), "project")
    assert project is not None
    assert project["license"] == "MIT"
    license_files = project["license-files"]
    assert isinstance(license_files, list)
    assert "LICENSE" in [str(entry) for entry in cast("list[object]", license_files)]


def test_never_ship_paths_are_not_package_data() -> None:
    """Nothing that must not ship may live inside the shipped module.

    uv_build ships src/punt_kit wholesale, so a sensitive path placed there
    would be published regardless of the backend's fail-closed default.
    """
    module = PROJECT_ROOT / "src" / "punt_kit"
    for name in NEVER_SHIP:
        assert not (module / name).exists(), f"{name} inside the shipped module"
