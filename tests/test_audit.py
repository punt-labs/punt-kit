"""Tests for audit command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from punt_kit.audit import run_audit
from punt_kit.detect import detect
from punt_kit.init import build_standard_deny_rules, build_standard_permissions

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
    (tmp_path / "Makefile").write_text(
        ".PHONY: help test lint type check format\n\n"
        "help: ## Show targets\n"
        "\t@echo help\n\n"
        "test: ## Run tests\n"
        "\tuv run pytest\n\n"
        "lint: ## Lint\n"
        "\tuv run ruff check .\n"
        "\tuv run ruff format --check .\n\n"
        "type: ## Type check\n"
        "\tuv run mypy src/ tests/\n"
        "\tuv run pyright src/ tests/\n\n"
        "check: lint type test ## All gates\n\n"
        "format: ## Format\n"
        "\tuv run ruff format .\n"
        "\tuv run ruff check --fix .\n"
    )
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
    # Standard permissions — use detect() to get the right set for this project
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    info = detect(tmp_path)
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": build_standard_permissions(info),
                    "deny": build_standard_deny_rules(),
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
    (tmp_path / "Makefile").write_text(
        ".PHONY: help test lint check format\n\n"
        "help: ## Show targets\n"
        "\t@echo help\n\n"
        "test: ## Run tests\n"
        "\tnpx jest\n\n"
        "lint: ## Lint\n"
        "\tnpx eslint .\n\n"
        "check: lint test ## All gates\n\n"
        "format: ## Format\n"
        "\tnpx prettier --write .\n"
    )
    (tmp_path / ".beads").mkdir()
    (tmp_path / ".markdownlint.jsonc").write_text("{}\n")
    (tmp_path / ".markdownlint-cli2.jsonc").write_text("{}\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "lint.yml").write_text("name: Lint\n")
    (workflows / "docs.yml").write_text("name: Docs\n")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    info = detect(tmp_path)
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": build_standard_permissions(info),
                    "deny": build_standard_deny_rules(),
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


# --- Plugin dev-command tests ---


def _make_compliant_plugin(tmp_path: Path) -> None:
    """Create a compliant plugin project scaffold with dev commands."""
    (tmp_path / "README.md").write_text("# Test Plugin\n")
    (tmp_path / "CLAUDE.md").write_text("# Agent Instructions\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    (tmp_path / ".beads").mkdir()
    (tmp_path / ".markdownlint.jsonc").write_text("{}\n")
    (tmp_path / ".markdownlint-cli2.jsonc").write_text("{}\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "docs.yml").write_text("name: Docs\n")
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-dev",
                "description": "Test plugin",
                "version": "1.0.0",
                "author": {"name": "Punt Labs", "email": "hello@punt-labs.com"},
            },
            indent=2,
        )
        + "\n"
    )
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    info = detect(tmp_path)
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": build_standard_permissions(info),
                    "deny": build_standard_deny_rules(),
                }
            },
            indent=2,
        )
        + "\n"
    )
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    (commands_dir / "audit.md").write_text("---\ndescription: Audit\n---\n")
    (commands_dir / "audit-dev.md").write_text("---\ndescription: Audit dev\n---\n")
    (commands_dir / "init.md").write_text("---\ndescription: Init\n---\n")
    (commands_dir / "init-dev.md").write_text("---\ndescription: Init dev\n---\n")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text("#!/usr/bin/env bash\n")
    (scripts_dir / "restore-dev-plugin.sh").write_text("#!/usr/bin/env bash\n")


def test_audit_plugin_dev_isolation_passes(tmp_path: Path) -> None:
    """Audit passes when plugin follows full dev/prod isolation standard."""
    _make_compliant_plugin(tmp_path)
    run_audit(str(tmp_path))


def test_audit_plugin_fails_missing_dev_command(tmp_path: Path) -> None:
    """Audit fails when a prod command is missing its -dev variant."""
    _make_compliant_plugin(tmp_path)
    (tmp_path / "commands" / "init-dev.md").unlink()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_plugin_fails_missing_dev_suffix(tmp_path: Path) -> None:
    """Audit fails when plugin name lacks -dev suffix."""
    _make_compliant_plugin(tmp_path)
    plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin_json.read_text())
    data["name"] = "test"  # no -dev suffix
    plugin_json.write_text(json.dumps(data, indent=2) + "\n")

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_plugin_fails_missing_release_scripts(tmp_path: Path) -> None:
    """Audit fails when release/restore scripts are missing."""
    _make_compliant_plugin(tmp_path)
    (tmp_path / "scripts" / "release-plugin.sh").unlink()
    (tmp_path / "scripts" / "restore-dev-plugin.sh").unlink()
    (tmp_path / "scripts").rmdir()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_plugin_non_plugin_skips_check(tmp_path: Path) -> None:
    """Audit skips dev isolation check for non-plugin projects."""
    _make_compliant_python(tmp_path)
    # No .claude-plugin/ — should not fail on missing dev commands
    run_audit(str(tmp_path))


# --- Hybrid install.sh tests ---


def _make_compliant_hybrid(tmp_path: Path) -> None:
    """Create a compliant hybrid project (CLI + plugin) scaffold."""
    _make_compliant_python(tmp_path)

    # Add CLI entry point and version to pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "1.0.0"\n\n'
        "[project.scripts]\ntest-cli = 'test_pkg:main'\n\n"
        "[tool.ruff]\nline-length = 88\n\n"
        "[tool.ruff.lint]\nselect = ['E']\n\n"
        "[tool.mypy]\nstrict = true\n\n"
        '[tool.pyright]\ntypeCheckingMode = "strict"\n\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )

    # Plugin structure (before detect so MCP servers are picked up)
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-dev",
                "description": "Test hybrid plugin",
                "version": "1.0.0",
                "author": {"name": "Punt Labs", "email": "hello@punt-labs.com"},
            },
            indent=2,
        )
        + "\n"
    )

    # Re-detect after pyproject.toml rewrite (now has CLI entry point + plugin)
    info = detect(tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": build_standard_permissions(info),
                    "deny": build_standard_deny_rules(),
                }
            },
            indent=2,
        )
        + "\n"
    )

    # Commands with dev variants
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(exist_ok=True)
    (commands_dir / "audit.md").write_text("---\ndescription: Audit\n---\n")
    (commands_dir / "audit-dev.md").write_text("---\ndescription: Audit dev\n---\n")

    # Release/restore scripts
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "release-plugin.sh").write_text("#!/usr/bin/env bash\n")
    (scripts_dir / "restore-dev-plugin.sh").write_text("#!/usr/bin/env bash\n")

    # Compliant install.sh
    (tmp_path / "install.sh").write_text(
        "#!/bin/sh\nset -eu\n"
        "# marketplace update\n"
        'claude plugin marketplace update "$MARKETPLACE_NAME" 2>/dev/null || true\n'
        "# SSH fallback\n"
        'git config --global url."https://github.com/".insteadOf "git@github.com:"\n'
        "# verify\n"
        '"$BINARY" doctor\n'
    )

    # README with SHA-pinned URLs
    readme_url = "https://raw.githubusercontent.com/punt-labs/test/abc1234/install.sh"
    (tmp_path / "README.md").write_text(
        f"# Test\n\n```bash\ncurl -fsSL {readme_url} | sh\n```\n"
    )


def test_audit_hybrid_install_sh_passes(tmp_path: Path) -> None:
    """Audit passes for compliant hybrid project with install.sh."""
    _make_compliant_hybrid(tmp_path)
    run_audit(str(tmp_path))


def test_audit_hybrid_install_sh_fails_missing(tmp_path: Path) -> None:
    """Audit fails when hybrid project is missing install.sh."""
    _make_compliant_hybrid(tmp_path)
    (tmp_path / "install.sh").unlink()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_hybrid_install_sh_fails_no_marketplace_refresh(tmp_path: Path) -> None:
    """Audit fails when install.sh is missing marketplace update step."""
    _make_compliant_hybrid(tmp_path)
    (tmp_path / "install.sh").write_text(
        "#!/bin/sh\nset -eu\n"
        "# SSH fallback\n"
        'git config --global url."https://github.com/".insteadOf "git@github.com:"\n'
        '"$BINARY" doctor\n'
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_hybrid_install_sh_fails_no_strict_mode(tmp_path: Path) -> None:
    """Audit fails when install.sh is missing set -eu."""
    _make_compliant_hybrid(tmp_path)
    (tmp_path / "install.sh").write_text(
        "#!/bin/sh\n"
        'claude plugin marketplace update "$MARKETPLACE_NAME" 2>/dev/null || true\n'
        'git config --global url."https://github.com/".insteadOf "git@github.com:"\n'
        '"$BINARY" doctor\n'
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_hybrid_install_sh_fails_no_ssh_fallback(tmp_path: Path) -> None:
    """Audit fails when install.sh is missing SSH/HTTPS fallback."""
    _make_compliant_hybrid(tmp_path)
    (tmp_path / "install.sh").write_text(
        "#!/bin/sh\nset -eu\n"
        'claude plugin marketplace update "$MARKETPLACE_NAME" 2>/dev/null || true\n'
        '"$BINARY" doctor\n'
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_hybrid_install_sh_fails_no_doctor(tmp_path: Path) -> None:
    """Audit fails when install.sh is missing doctor verification."""
    _make_compliant_hybrid(tmp_path)
    (tmp_path / "install.sh").write_text(
        "#!/bin/sh\nset -eu\n"
        'claude plugin marketplace update "$MARKETPLACE_NAME" 2>/dev/null || true\n'
        'git config --global url."https://github.com/".insteadOf "git@github.com:"\n'
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


# --- README SHA pin tests ---


def test_audit_readme_sha_pins_pass(tmp_path: Path) -> None:
    """Audit passes when README has SHA-pinned raw GitHub URLs."""
    _make_compliant_hybrid(tmp_path)
    run_audit(str(tmp_path))


def test_audit_readme_sha_pins_fail_branch(tmp_path: Path) -> None:
    """Audit fails when README has branch name instead of SHA in raw GitHub URL."""
    _make_compliant_hybrid(tmp_path)
    readme_url = "https://raw.githubusercontent.com/punt-labs/test/main/install.sh"
    (tmp_path / "README.md").write_text(
        f"# Test\n\n```bash\ncurl -fsSL {readme_url} | sh\n```\n"
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


# --- Plugin version sync tests ---


def test_audit_plugin_version_sync_passes(tmp_path: Path) -> None:
    """Audit passes when plugin.json and pyproject.toml versions match."""
    _make_compliant_hybrid(tmp_path)
    run_audit(str(tmp_path))


def test_audit_plugin_version_sync_fails(tmp_path: Path) -> None:
    """Audit fails when plugin.json and pyproject.toml versions differ."""
    _make_compliant_hybrid(tmp_path)
    # Mismatch: plugin.json=1.0.0, pyproject.toml=2.0.0
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "2.0.0"\n\n'
        "[project.scripts]\ntest-cli = 'test_pkg:main'\n\n"
        "[tool.ruff]\nline-length = 88\n\n"
        "[tool.ruff.lint]\nselect = ['E']\n\n"
        "[tool.mypy]\nstrict = true\n\n"
        '[tool.pyright]\ntypeCheckingMode = "strict"\n\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_fails_missing_makefile(tmp_path: Path) -> None:
    """Audit fails when Makefile is missing."""
    _make_compliant_python(tmp_path)
    (tmp_path / "Makefile").unlink()

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_fails_missing_makefile_target(tmp_path: Path) -> None:
    """Audit fails when a required Makefile target is missing."""
    _make_compliant_python(tmp_path)
    # Makefile without 'format' target
    (tmp_path / "Makefile").write_text(
        ".PHONY: help test lint type check\n\n"
        "help: ## Show targets\n"
        "\t@echo help\n\n"
        "test: ## Run tests\n"
        "\tuv run pytest\n\n"
        "lint: ## Lint\n"
        "\tuv run ruff check .\n\n"
        "type: ## Type check\n"
        "\tuv run mypy src/\n\n"
        "check: lint type test ## All gates\n"
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))


def test_audit_fails_missing_help_comment(tmp_path: Path) -> None:
    """Audit fails when a required target lacks a ## help comment."""
    _make_compliant_python(tmp_path)
    # 'format' target exists but has no ## comment
    (tmp_path / "Makefile").write_text(
        ".PHONY: help test lint type check format\n\n"
        "help: ## Show targets\n"
        "\t@echo help\n\n"
        "test: ## Run tests\n"
        "\tuv run pytest\n\n"
        "lint: ## Lint\n"
        "\tuv run ruff check .\n\n"
        "type: ## Type check\n"
        "\tuv run mypy src/\n\n"
        "check: lint type test ## All gates\n\n"
        "format:\n"
        "\tuv run ruff format .\n"
    )

    with pytest.raises(SystemExit, match="1"):
        run_audit(str(tmp_path))
