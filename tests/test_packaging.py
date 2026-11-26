"""Tests for the contents of published distributions.

The build backend must ship the declared module rather than the entire
checkout, where local files could otherwise leak into a public artifact.
"""

from __future__ import annotations

import subprocess
import tomllib
import zipfile
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
    """Require a backend that ships only the declared module by default."""
    build_system = _table(_pyproject(), "build-system")
    assert build_system is not None
    assert build_system["build-backend"] == "uv_build"


def test_module_is_declared() -> None:
    """uv_build ships what module-name names, so it must be named."""
    backend = _table(_pyproject(), "tool", "uv", "build-backend")
    assert backend is not None
    assert backend["module-name"] == "punt_kit"


def test_no_stale_hatch_configuration() -> None:
    """Do not declare a Hatch sdist allowlist that the active backend ignores."""
    assert _table(_pyproject(), "tool", "hatch") is None


def test_license_is_declared_in_metadata() -> None:
    """Require the PEP 639 metadata that declares the license file."""
    project = _table(_pyproject(), "project")
    assert project is not None
    assert project["license"] == "MIT"
    license_files = project["license-files"]
    assert isinstance(license_files, list)
    assert "LICENSE" in [str(entry) for entry in cast("list[object]", license_files)]


def test_built_wheel_carries_license_and_templates(tmp_path: Path) -> None:
    """Read the built wheel rather than assuming metadata guarantees its contents."""
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as archive:
        members = archive.namelist()

    assert any(name.endswith("licenses/LICENSE") for name in members), (
        "LICENSE absent from the wheel — the regression this test exists for"
    )
    assert any("/templates/" in name for name in members), (
        "package data absent from the wheel"
    )
    assert any(name.endswith("py.typed") for name in members)


def test_never_ship_paths_are_not_package_data() -> None:
    """Nothing that must not ship may live inside the shipped module.

    uv_build ships src/punt_kit wholesale, so a sensitive path placed there
    would be published regardless of the backend's fail-closed default.
    """
    module = PROJECT_ROOT / "src" / "punt_kit"
    for name in NEVER_SHIP:
        assert not (module / name).exists(), f"{name} inside the shipped module"
