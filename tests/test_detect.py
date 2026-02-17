"""Tests for project type detection."""

from __future__ import annotations

from pathlib import Path

from punt_kit.detect import detect


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


def test_detect_all_standards_refs(tmp_path: Path) -> None:
    """All projects get github and workflow refs."""
    (tmp_path / "README.md").write_text("# Test")

    info = detect(tmp_path)

    assert "github" in info.standards_refs
    assert "workflow" in info.standards_refs
