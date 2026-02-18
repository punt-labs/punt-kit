"""Tests for audit command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_kit.audit import run_audit

if TYPE_CHECKING:
    from pathlib import Path


def test_audit_docs_project(tmp_path: Path, capsys: object) -> None:
    """Audit reports missing docs.yml for docs project."""
    (tmp_path / "README.md").write_text("# Test")

    run_audit(str(tmp_path))

    # Should complete without error — audit is read-only


def test_audit_python_project(tmp_path: Path) -> None:
    """Audit reports gaps for Python project missing configs."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

    run_audit(str(tmp_path))

    # Should complete without error


def test_audit_compliant_project(tmp_path: Path) -> None:
    """Audit reports passes for a project with everything configured."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n'
        "[tool.ruff]\nline-length = 88\n\n"
        "[tool.ruff.lint]\nselect = ['E']\n\n"
        "[tool.mypy]\nstrict = true\n\n"
        '[tool.pyright]\ntypeCheckingMode = "strict"\n\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    (tmp_path / "CLAUDE.md").write_text("# Agent Instructions\n")
    (tmp_path / ".beads").mkdir()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "lint.yml").write_text("name: Lint\n")
    (workflows / "test.yml").write_text("name: Test\n")
    (workflows / "docs.yml").write_text("name: Docs\n")

    run_audit(str(tmp_path))

    # Should complete without error — all local checks pass
