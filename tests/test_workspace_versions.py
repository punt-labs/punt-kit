"""Tests for uv workspace manifest rewrites."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.workspace_versions import WorkspaceVersions

if TYPE_CHECKING:
    from pathlib import Path


def test_rewrites_exact_pins_in_dependency_tables_only(tmp_path: Path) -> None:
    root_file = tmp_path / "pyproject.toml"
    text = """[project]
name = "root"
version = '1.0.0' # release version
dependencies = [
    "Client_LIB[extra] == 1.0.0 ; python_version >= '3.13'", # current pin
    "client-lib==1.0.*",
    "client-lib==1.0.0,!=1.0.1",
    "client-lib>=1.0.0",
    "client-lib==0.9.0",
    "external==1.0.0",
    "separate==1.0.0",
    "already-target==1.0.0",
    "excluded==1.0.0",
    "unmanaged==1.0.0",
]

[project.optional-dependencies]
extras = ['client-lib==1.0']

[dependency-groups]
dev = ["client-lib==1.0.0", { include-group = "test" }]
test = []

[tool.uv]
dev-dependencies = ["client-lib==1.0.0", "separate==1.0.0"]

[tool.uv.workspace]
members = ["pkg/*"]
exclude = ["pkg/excluded"]

[tool.unrelated]
version = "1.0.0"
dependencies = ["client-lib==1.0.0"]
"""
    paths: dict[str, Path] = {}
    for name, version in (
        ("client-lib", "1.0.0"),
        ("separate", "9.0.0"),
        ("already-target", "2.0.0"),
        ("excluded", "1.0.0"),
        ("unmanaged", "1.0.0"),
    ):
        path = tmp_path / "pkg" / name / "pyproject.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n'
            'dependencies = ["root==1.0.0"]\n'
        )
        paths[name] = path
    unmanaged = paths["unmanaged"]
    unmanaged.write_text(unmanaged.read_text() + "\n[tool.uv]\nmanaged = false\n")
    workspace = WorkspaceVersions.from_manifest(
        tmp_path, tomllib.loads(text), read=lambda path: path.read_text()
    )
    assert workspace is not None

    original_versions = {
        paths["client-lib"]: "1.0.0",
        paths["already-target"]: "2.0.0",
    }
    root_text = text.replace("\n", "\r\n")
    rewrites = workspace.rewrites(root_text, "1.0.0", "2.0.0", original_versions.get)

    assert rewrites[root_file] == (
        text.replace("version = '1.0.0'", "version = '2.0.0'")
        .replace("Client_LIB[extra] == 1.0.0", "Client_LIB[extra] == 2.0.0")
        .replace("extras = ['client-lib==1.0']", "extras = ['client-lib==2.0.0']")
        .replace('dev = ["client-lib==1.0.0",', 'dev = ["client-lib==2.0.0",')
        .replace(
            'dev-dependencies = ["client-lib==1.0.0",',
            'dev-dependencies = ["client-lib==2.0.0",',
        )
        .replace("\n", "\r\n")
    )
    assert rewrites[paths["client-lib"]] == (
        '[project]\nname = "client-lib"\nversion = "2.0.0"\n'
        'dependencies = ["root==2.0.0"]\n'
    )
    assert rewrites[paths["separate"]] == (
        '[project]\nname = "separate"\nversion = "9.0.0"\n'
        'dependencies = ["root==2.0.0"]\n'
    )
    assert paths["excluded"] not in rewrites
    assert unmanaged not in rewrites

    client = paths["client-lib"]
    client.write_text(rewrites[client])
    assert (
        workspace.rewrites(root_text, "1.0.0", "2.0.0", original_versions.get)
        == rewrites
    )


@pytest.mark.parametrize("exclude", ["packages/*-skip", "packages/**/*-skip"])
def test_exclude_matches_nested_workspace_paths(tmp_path: Path, exclude: str) -> None:
    text = (
        '[project]\nname = "root"\nversion = "1.0.0"\n'
        '[tool.uv.workspace]\nmembers = ["packages/*-skip", "packages/nested/*"]\n'
        f'exclude = ["{exclude}"]\n'
    )
    expected = {tmp_path / "pyproject.toml"}
    for parent, name in (
        ("packages", "direct-skip"),
        ("packages/nested", "nested-skip"),
        ("packages/nested", "keep"),
    ):
        path = tmp_path / parent / name / "pyproject.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[project]\nname = "{name}"\nversion = "1.0.0"\n')
        if name == "keep":
            expected.add(path)

    workspace = WorkspaceVersions.from_manifest(
        tmp_path, tomllib.loads(text), read=lambda path: path.read_text()
    )
    assert workspace is not None
    assert workspace.rewrites(text, "1.0.0", "2.0.0", lambda _: None).keys() == expected


def test_equivalent_member_version_shares_the_root_release(tmp_path: Path) -> None:
    root = tmp_path / "pyproject.toml"
    text = (
        '[project]\nname = "root"\nversion = "1.0"\n'
        'dependencies = ["client==1.0.0"]\n'
        '[tool.uv.workspace]\nmembers = ["client"]\n'
    )
    client = tmp_path / "client" / "pyproject.toml"
    client.parent.mkdir()
    client.write_text('[project]\nname = "client"\nversion = "1.0.0"\n')
    workspace = WorkspaceVersions.from_manifest(
        tmp_path, tomllib.loads(text), read=lambda path: path.read_text()
    )
    assert workspace is not None
    previous = {client: "1.0.0"}.get

    rewrites = workspace.rewrites(text, "1.0", "2.0", previous)
    assert 'dependencies = ["client==2.0"]' in rewrites[root]
    assert 'version = "2.0"' in rewrites[client]
    client.write_text(rewrites[client])
    assert workspace.rewrites(text, "1.0", "2.0", previous) == rewrites


def test_rejects_symlinked_member_manifest(tmp_path: Path) -> None:
    text = (
        '[project]\nname = "root"\nversion = "1.0.0"\n'
        '[tool.uv.workspace]\nmembers = ["client"]\n'
    )
    actual = tmp_path / "client.toml"
    actual.write_text('[project]\nname = "client"\nversion = "1.0.0"\n')
    member = tmp_path / "client" / "pyproject.toml"
    member.parent.mkdir()
    member.symlink_to(actual)
    workspace = WorkspaceVersions.from_manifest(
        tmp_path, tomllib.loads(text), read=lambda path: path.read_text()
    )
    assert workspace is not None
    with pytest.raises(ReleaseError, match="member manifest uses a symlink"):
        workspace.rewrites(text, "1.0.0", "2.0.0", lambda _: None)
