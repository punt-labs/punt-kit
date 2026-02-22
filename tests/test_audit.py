"""Tests for audit command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from punt_kit.audit import run_audit

if TYPE_CHECKING:
    from pathlib import Path


def _make_compliant_python(tmp_path: Path) -> None:
    """Create a fully compliant Python project scaffold."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n'
        "[tool.ruff]\nline-length = 88\n\n"
        "[tool.ruff.lint]\nselect = ['E']\n\n"
        "[tool.mypy]\nstrict = true\n\n"
        '[tool.pyright]\ntypeCheckingMode = "strict"\n\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    (tmp_path / "CLAUDE.md").write_text("# Agent Instructions\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    (tmp_path / ".beads").mkdir()
    (tmp_path / ".markdownlint.jsonc").write_text("{}\n")
    (tmp_path / ".markdownlint-cli2.jsonc").write_text("{}\n")
    src_pkg = tmp_path / "src" / "test_pkg"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("")
    (src_pkg / "py.typed").write_text("")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "lint.yml").write_text("name: Lint\n")
    (workflows / "test.yml").write_text("name: Test\n")
    (workflows / "docs.yml").write_text("name: Docs\n")
    # Standard permissions
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(git:*)",
                        "Bash(gh:*)",
                        "Bash(bd:*)",
                        "Bash(punt:*)",
                        "Bash(uv:*)",
                        "Bash(python3:*)",
                    ]
                }
            },
            indent=2,
        )
        + "\n"
    )


def test_audit_docs_project(tmp_path: Path) -> None:
    """Audit exits non-zero for docs project missing docs.yml."""
    (tmp_path / "README.md").write_text("# Test")

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_python_project_reports_failures(tmp_path: Path) -> None:
    """Audit exits non-zero for Python project missing configs."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_compliant_project_passes(tmp_path: Path) -> None:
    """Audit exits cleanly for a fully compliant project."""
    _make_compliant_python(tmp_path)

    # Should not raise SystemExit
    run_audit(str(tmp_path))


def test_audit_fix_creates_markdownlint(tmp_path: Path) -> None:
    """--fix creates missing markdownlint config files."""
    _make_compliant_python(tmp_path)
    # Remove markdownlint files to test fix
    (tmp_path / ".markdownlint.jsonc").unlink()
    (tmp_path / ".markdownlint-cli2.jsonc").unlink()

    run_audit(str(tmp_path), fix=True)

    assert (tmp_path / ".markdownlint.jsonc").exists()
    content = (tmp_path / ".markdownlint.jsonc").read_text()
    assert "MD013" in content

    assert (tmp_path / ".markdownlint-cli2.jsonc").exists()
    cli2_content = (tmp_path / ".markdownlint-cli2.jsonc").read_text()
    assert ".beads/" in cli2_content


def test_audit_fix_creates_py_typed(tmp_path: Path) -> None:
    """--fix creates missing py.typed marker."""
    _make_compliant_python(tmp_path)
    py_typed = tmp_path / "src" / "test_pkg" / "py.typed"
    py_typed.unlink()

    run_audit(str(tmp_path), fix=True)

    assert py_typed.exists()


def test_audit_fix_creates_changelog(tmp_path: Path) -> None:
    """--fix creates missing CHANGELOG.md with skeleton content."""
    _make_compliant_python(tmp_path)
    (tmp_path / "CHANGELOG.md").unlink()

    run_audit(str(tmp_path), fix=True)

    changelog = tmp_path / "CHANGELOG.md"
    assert changelog.exists()
    content = changelog.read_text()
    assert "Changelog" in content
    assert "Keep a Changelog" in content


def test_audit_without_fix_fails_on_missing_files(tmp_path: Path) -> None:
    """Audit without --fix reports failures for missing files."""
    _make_compliant_python(tmp_path)
    (tmp_path / ".markdownlint.jsonc").unlink()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_fix_idempotent(tmp_path: Path) -> None:
    """Running audit --fix twice produces the same result."""
    _make_compliant_python(tmp_path)
    (tmp_path / ".markdownlint.jsonc").unlink()
    (tmp_path / ".markdownlint-cli2.jsonc").unlink()

    run_audit(str(tmp_path), fix=True)
    first_ml = (tmp_path / ".markdownlint.jsonc").read_text()

    run_audit(str(tmp_path))  # Second run without fix — should pass
    second_ml = (tmp_path / ".markdownlint.jsonc").read_text()

    assert first_ml == second_ml


def test_audit_fix_does_not_overwrite_existing(tmp_path: Path) -> None:
    """--fix does not overwrite existing config files."""
    _make_compliant_python(tmp_path)
    custom = '{"MD013": true}\n'
    (tmp_path / ".markdownlint.jsonc").write_text(custom)

    run_audit(str(tmp_path), fix=True)

    assert (tmp_path / ".markdownlint.jsonc").read_text() == custom


def test_audit_non_python_skips_python_checks(tmp_path: Path) -> None:
    """Audit for non-Python project skips Python-specific checks."""
    (tmp_path / "package.json").write_text('{"name": "test"}')
    (tmp_path / "CLAUDE.md").write_text("# Agent\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    (tmp_path / ".beads").mkdir()
    (tmp_path / ".markdownlint.jsonc").write_text("{}\n")
    (tmp_path / ".markdownlint-cli2.jsonc").write_text("{}\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "lint.yml").write_text("name: Lint\n")
    (workflows / "docs.yml").write_text("name: Docs\n")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(git:*)",
                        "Bash(gh:*)",
                        "Bash(bd:*)",
                        "Bash(punt:*)",
                        "Bash(npx:*)",
                        "Bash(npm:*)",
                    ]
                }
            },
            indent=2,
        )
        + "\n"
    )

    # Should pass — no Python-specific checks apply
    run_audit(str(tmp_path))


# --- Permission check tests ---


def test_audit_fails_without_settings_json(tmp_path: Path) -> None:
    """Audit fails when .claude/settings.json is missing."""
    _make_compliant_python(tmp_path)
    (tmp_path / ".claude" / "settings.json").unlink()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_fails_with_missing_permissions(tmp_path: Path) -> None:
    """Audit fails when settings.json is missing standard permissions."""
    _make_compliant_python(tmp_path)
    # Overwrite with incomplete permissions
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git:*)"]}}, indent=2) + "\n"
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_passes_with_extra_permissions(tmp_path: Path) -> None:
    """Audit passes when settings.json has extra permissions beyond standard."""
    _make_compliant_python(tmp_path)
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    data["permissions"]["allow"].append("Bash(custom:*)")
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps(data, indent=2) + "\n"
    )

    # Should still pass — extra permissions are fine
    run_audit(str(tmp_path))
