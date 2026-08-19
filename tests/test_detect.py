"""Tests for project type detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect

if TYPE_CHECKING:
    from pathlib import Path


def _write_manifest(root: Path, *parts: str, body: str = '{"name": "test"}') -> Path:
    """Write a plugin manifest at ``root/parts`` and return its path."""
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_detect_python_package(tmp_path: Path) -> None:
    """Detect Python package from pyproject.toml with [project]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-pkg"\n')

    info = detect(tmp_path)

    assert info.language == "python"
    assert info.project_type == "package"
    assert "python" in info.standards_refs


def test_detect_node_package(tmp_path: Path) -> None:
    """Detect Node.js from package.json."""
    pkg = tmp_path / "package.json"
    pkg.write_text('{"name": "test-pkg"}')

    info = detect(tmp_path)

    assert info.language == "node"
    assert info.project_type == "package"
    assert "node" in info.standards_refs


def test_detect_go(tmp_path: Path) -> None:
    """Detect Go from go.mod."""
    (tmp_path / "go.mod").write_text("module example.com/test\n\ngo 1.25.0\n")

    info = detect(tmp_path)

    assert info.language == "go"
    assert info.project_type == "package"


def test_detect_swift(tmp_path: Path) -> None:
    """Detect Swift from .swift files."""
    (tmp_path / "App.swift").write_text("import SwiftUI")

    info = detect(tmp_path)

    assert info.language == "swift"
    assert info.project_type == "app"


def test_detect_plugin(tmp_path: Path) -> None:
    """Detect Claude Code plugin from plugin.json."""
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"name": "test"}')

    info = detect(tmp_path)

    assert info.is_plugin is True
    assert "plugins" in info.standards_refs


def test_detect_plugin_subdir_layout(tmp_path: Path) -> None:
    """The DES-025 layout is detected, and the plugin root is plugin/.

    plugin_root is what every ${CLAUDE_PLUGIN_ROOT}-relative path is anchored
    on. Returning the repo root here is the specific bug that makes the audit
    glob commands/ in a directory that no longer holds any.
    """
    manifest = _write_manifest(tmp_path, "plugin", ".claude-plugin", "plugin.json")

    info = detect(tmp_path)

    assert info.is_plugin is True
    assert info.plugin_manifest == manifest
    assert info.plugin_root == tmp_path / "plugin"


def test_detect_plugin_subdir_wins_over_repo_root(tmp_path: Path) -> None:
    """A half-finished move leaves two manifests; plugin/ is authoritative."""
    subdir = _write_manifest(
        tmp_path, "plugin", ".claude-plugin", "plugin.json", body='{"name": "new"}'
    )
    _write_manifest(tmp_path, ".claude-plugin", "plugin.json", body='{"name": "old"}')

    info = detect(tmp_path)

    assert info.plugin_manifest == subdir
    assert len(info.plugin_manifests) == 2, "the stale manifest must stay visible"


def test_detect_plugin_root_for_bare_manifest(tmp_path: Path) -> None:
    """With plugin.json loose at the repo root, that root is the plugin root."""
    _write_manifest(tmp_path, "plugin.json")

    info = detect(tmp_path)

    assert info.is_plugin is True
    assert info.plugin_root == tmp_path


def test_plugin_manifest_raises_for_non_plugin(tmp_path: Path) -> None:
    """Reaching for a manifest that cannot exist is a caller bug, so it raises.

    Returning None would push the failure into a path join and surface it as a
    nonsense filename far from the code that asked the wrong question.
    """
    (tmp_path / "README.md").write_text("# Docs")

    info = detect(tmp_path)

    assert info.is_plugin is False
    with pytest.raises(ValueError, match="no plugin manifest"):
        _ = info.plugin_manifest


def test_detect_ci_workflows(tmp_path: Path) -> None:
    """Detect existing CI workflows."""
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "lint.yml").write_text("name: Lint")

    info = detect(tmp_path)

    assert info.has_ci is True
    assert "lint.yml" in info.workflow_files


def test_detect_beads(tmp_path: Path) -> None:
    """Detect beads directory."""
    (tmp_path / ".beads").mkdir()

    info = detect(tmp_path)

    assert info.has_beads is True


def test_detect_claude_md(tmp_path: Path) -> None:
    """Detect CLAUDE.md."""
    (tmp_path / "CLAUDE.md").write_text("# Agent Instructions")

    info = detect(tmp_path)

    assert info.has_claude_md is True


def test_detect_docs_project(tmp_path: Path) -> None:
    """Detect docs-only project from markdown files."""
    (tmp_path / "README.md").write_text("# Docs")

    info = detect(tmp_path)

    assert info.language is None
    assert info.project_type == "docs"


def test_detect_mcp_server_python(tmp_path: Path) -> None:
    """Detect MCP server from FastMCP import."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-mcp"\n')
    src = tmp_path / "src"
    src.mkdir()
    server = src / "server.py"
    server.write_text("from fastmcp import FastMCP\napp = FastMCP('test')\n")

    info = detect(tmp_path)

    assert info.is_mcp_server is True
    assert info.language == "python"


def test_detect_go_hybrid(tmp_path: Path) -> None:
    """Detect Go project with cmd/ directory as hybrid when plugin exists."""
    (tmp_path / "go.mod").write_text("module example.com/test\n\ngo 1.25.0\n")
    cmd_dir = tmp_path / "cmd" / "myapp"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "main.go").write_text("package main\nfunc main() {}\n")
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"name": "myapp-dev"}')

    info = detect(tmp_path)

    assert info.language == "go"
    assert info.is_plugin is True
    assert info.is_hybrid is True
    assert info.cli_commands == ["myapp"]


def test_detect_go_no_cmd_dir(tmp_path: Path) -> None:
    """Go project without cmd/ directory has no CLI commands."""
    (tmp_path / "go.mod").write_text("module example.com/lib\n\ngo 1.25.0\n")

    info = detect(tmp_path)

    assert info.language == "go"
    assert info.cli_commands == []
    assert info.is_hybrid is False


def test_detect_all_standards_refs(tmp_path: Path) -> None:
    """All projects get github and workflow refs."""
    (tmp_path / "README.md").write_text("# Test")

    info = detect(tmp_path)

    assert "github" in info.standards_refs
    assert "workflow" in info.standards_refs
