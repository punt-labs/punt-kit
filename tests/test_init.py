"""Tests for init command."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from punt_kit.init import run_init


def test_init_creates_docs_workflow(tmp_path: Path) -> None:
    """Init creates docs.yml for any project with markdown files."""
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    docs_yml = tmp_path / ".github" / "workflows" / "docs.yml"
    assert docs_yml.exists()
    content = docs_yml.read_text()
    assert "markdownlint" in content


def test_init_creates_python_workflows(tmp_path: Path) -> None:
    """Init creates lint.yml and test.yml for Python projects."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))

    lint_yml = tmp_path / ".github" / "workflows" / "lint.yml"
    test_yml = tmp_path / ".github" / "workflows" / "test.yml"
    assert lint_yml.exists()
    assert test_yml.exists()
    assert "ruff" in lint_yml.read_text()
    assert "pytest" in test_yml.read_text()


def test_init_creates_node_workflow(tmp_path: Path) -> None:
    """Init creates lint.yml for Node.js projects."""
    (tmp_path / "package.json").write_text('{"name": "test"}')

    run_init(str(tmp_path))

    lint_yml = tmp_path / ".github" / "workflows" / "lint.yml"
    assert lint_yml.exists()
    assert "npm" in lint_yml.read_text()


def test_init_merges_python_tool_config(tmp_path: Path) -> None:
    """Init adds tool config to existing pyproject.toml without overwriting."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-pkg"\nversion = "1.0.0"\n')

    run_init(str(tmp_path))

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    assert data["project"]["name"] == "test-pkg"
    assert data["project"]["version"] == "1.0.0"
    assert "ruff" in data["tool"]
    assert "mypy" in data["tool"]
    assert "pyright" in data["tool"]
    assert "pytest" in data["tool"]


def test_init_preserves_existing_tool_config(tmp_path: Path) -> None:
    """Init does not overwrite existing tool configs."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test-pkg"\n\n[tool.ruff]\ntarget-version = "py312"\n'
    )

    run_init(str(tmp_path))

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    # Existing ruff config should be preserved
    assert data["tool"]["ruff"]["target-version"] == "py312"
    # But missing configs should be added
    assert "mypy" in data["tool"]


def test_init_creates_claude_md(tmp_path: Path) -> None:
    """Init creates CLAUDE.md with standards references."""
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "Standards References" in content
    assert "punt-labs/punt-kit" in content


def test_init_appends_to_existing_claude_md(tmp_path: Path) -> None:
    """Init appends references to existing CLAUDE.md without overwriting."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# My Project\n\nCustom instructions here.\n")
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    content = claude_md.read_text()
    assert "My Project" in content
    assert "Custom instructions here" in content
    assert "Standards References" in content


def test_init_skips_existing_references(tmp_path: Path) -> None:
    """Init does not duplicate standards references."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "# Agent Instructions\n\n## Standards References\n- Already here\n"
    )
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    content = claude_md.read_text()
    assert content.count("Standards References") == 1


def test_init_idempotent(tmp_path: Path) -> None:
    """Running init twice produces the same result."""
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))
    first_docs = (tmp_path / ".github" / "workflows" / "docs.yml").read_text()
    first_claude = (tmp_path / "CLAUDE.md").read_text()

    run_init(str(tmp_path))
    second_docs = (tmp_path / ".github" / "workflows" / "docs.yml").read_text()
    second_claude = (tmp_path / "CLAUDE.md").read_text()

    assert first_docs == second_docs
    assert first_claude == second_claude
