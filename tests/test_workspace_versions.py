"""Tests for uv workspace manifest rewrites."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

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
