"""Tests for init command."""

from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from punt_kit.init import STANDARD_SKILL_PERMISSIONS, run_init

_EXPECTED_SKILLS: list[str] = sorted(STANDARD_SKILL_PERMISSIONS)


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


def test_init_creates_release_workflow_with_metadata(tmp_path: Path) -> None:
    """Init creates release.yml with package name and CLI command substituted."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "punt-quarry"\n\n'
        '[project.scripts]\nquarry = "quarry.cli:app"\n'
    )

    run_init(str(tmp_path))

    release_yml = tmp_path / ".github" / "workflows" / "release.yml"
    assert release_yml.exists()
    content = release_yml.read_text()
    assert "punt-quarry" in content
    assert "quarry --help" in content
    # Jinja2 placeholders must not appear in rendered output
    assert "{{ package_name }}" not in content
    assert "{{ cli_command }}" not in content


def test_init_skips_release_without_cli_entry_point(tmp_path: Path) -> None:
    """Init skips release.yml when pyproject.toml has no scripts entry."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))

    release_yml = tmp_path / ".github" / "workflows" / "release.yml"
    assert not release_yml.exists()


def test_init_release_workflow_idempotent(tmp_path: Path) -> None:
    """Running init twice with release metadata produces the same result."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "punt-biff"\n\n'
        '[project.scripts]\nbiff = "biff.__main__:app"\n'
    )

    run_init(str(tmp_path))
    first = (tmp_path / ".github" / "workflows" / "release.yml").read_text()

    run_init(str(tmp_path))
    second = (tmp_path / ".github" / "workflows" / "release.yml").read_text()

    assert first == second


def test_init_skips_existing_workflow_files(tmp_path: Path) -> None:
    """Init skips workflow files that already exist with different content."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test-pkg"\n')

    # First run creates the workflows
    run_init(str(tmp_path))

    lint_yml = tmp_path / ".github" / "workflows" / "lint.yml"
    assert lint_yml.exists()

    # Simulate a project-specific customization
    customized = lint_yml.read_text() + "\n# custom cache config\n"
    lint_yml.write_text(customized)

    # Second run should skip the customized file, not overwrite it
    run_init(str(tmp_path))

    assert lint_yml.read_text() == customized


# --- Permission scaffolding tests ---


def test_init_creates_permissions_python(tmp_path: Path) -> None:
    """Init creates .claude/settings.json with Python-specific permissions."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))

    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    # Base permissions
    assert "Bash(git:*)" in allow
    assert "Bash(gh:*)" in allow
    assert "Bash(bd:*)" in allow
    assert "Bash(punt:*)" in allow

    # Python-specific
    assert "Bash(uv:*)" in allow
    assert "Bash(python3:*)" in allow

    # make is universal; should NOT have Swift or Node specific
    assert "Bash(make:*)" in allow
    assert "Bash(npx:*)" not in allow


def test_init_creates_permissions_swift(tmp_path: Path) -> None:
    """Init creates .claude/settings.json with Swift-specific permissions."""
    (tmp_path / "project.yml").write_text("name: TestApp\n")

    run_init(str(tmp_path))

    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    assert "Bash(make:*)" in allow
    assert "Bash(swiftformat:*)" in allow
    assert "Bash(swiftlint:*)" in allow
    assert "Bash(xcodebuild:*)" in allow
    assert "Bash(xcodegen:*)" in allow

    # Should NOT have Python-specific
    assert "Bash(uv:*)" not in allow


def test_init_creates_permissions_node(tmp_path: Path) -> None:
    """Init creates .claude/settings.json with Node-specific permissions."""
    (tmp_path / "package.json").write_text('{"name": "test"}')

    run_init(str(tmp_path))

    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    assert "Bash(npx:*)" in allow
    assert "Bash(npm:*)" in allow


def test_init_permissions_include_plugin_mcp_servers(tmp_path: Path) -> None:
    """Init adds MCP permission patterns for plugin servers."""
    (tmp_path / "README.md").write_text("# Test")
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "myplug",
                "description": "Test plugin",
                "mcpServers": {"grimoire": {"command": "node", "args": ["server.js"]}},
            }
        )
    )

    run_init(str(tmp_path))

    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    assert "mcp__plugin_myplug_grimoire__*" in allow


def test_init_permissions_include_cli_commands(tmp_path: Path) -> None:
    """Init adds Bash permissions for CLI entry points from pyproject scripts."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "punt-quarry"\n\n'
        '[project.scripts]\nquarry = "quarry.cli:app"\n'
    )

    run_init(str(tmp_path))

    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]

    assert "Bash(quarry:*)" in allow


def test_init_permissions_merge_existing(tmp_path: Path) -> None:
    """Init merges permissions into existing settings.json without removing entries."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')

    # Pre-existing settings with custom permission and other config
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(custom:*)", "Bash(git:*)"]},
                "env": {"MY_VAR": "value"},
            }
        )
    )

    run_init(str(tmp_path))

    data = json.loads((settings_dir / "settings.json").read_text())
    allow = data["permissions"]["allow"]

    # Existing entries preserved
    assert "Bash(custom:*)" in allow
    assert "Bash(git:*)" in allow
    # New entries added
    assert "Bash(uv:*)" in allow
    # Non-permission fields preserved
    assert data["env"]["MY_VAR"] == "value"


def test_init_permissions_no_duplicates(tmp_path: Path) -> None:
    """Init does not duplicate permissions that already exist."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))
    first = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    run_init(str(tmp_path))
    second = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    assert first == second


# --- Gitignore tests ---


def test_init_creates_gitignore_claude_pattern(tmp_path: Path) -> None:
    """Init adds .claude/ gitignore pattern with exceptions."""
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".claude/" in content
    assert "!.claude/settings.json" in content
    assert "!.claude/hooks/" in content


def test_init_appends_gitignore_to_existing(tmp_path: Path) -> None:
    """Init appends .claude/ pattern to existing .gitignore."""
    (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__/\n")
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    content = (tmp_path / ".gitignore").read_text()
    assert "*.pyc" in content
    assert ".claude/" in content
    assert "!.claude/settings.json" in content


def test_init_gitignore_idempotent(tmp_path: Path) -> None:
    """Init does not duplicate .claude/ gitignore pattern."""
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))
    first = (tmp_path / ".gitignore").read_text()

    run_init(str(tmp_path))
    second = (tmp_path / ".gitignore").read_text()

    assert first == second
    # Count only the bare ".claude/" line, not substrings in exception lines
    assert second.split("\n").count(".claude/") == 1


def test_init_gitignore_adds_missing_exceptions(tmp_path: Path) -> None:
    """Init adds missing exception lines when .claude/ already in gitignore."""
    (tmp_path / ".gitignore").write_text(".claude/\n")
    (tmp_path / "README.md").write_text("# Test")

    run_init(str(tmp_path))

    content = (tmp_path / ".gitignore").read_text()
    assert "!.claude/settings.json" in content
    assert "!.claude/hooks/" in content
    # Should still have only one .claude/ line
    assert content.count(".claude/\n") == 1


def test_init_language_override_on_empty_repo(tmp_path: Path) -> None:
    """Init with --language scaffolds language-specific files for empty repos."""
    # Empty repo — no pyproject.toml, no package.json, nothing
    (tmp_path / ".git").mkdir()  # make it look like a git repo

    run_init(str(tmp_path), language="python")

    # Should create Python-specific workflows
    lint_yml = tmp_path / ".github" / "workflows" / "lint.yml"
    test_yml = tmp_path / ".github" / "workflows" / "test.yml"
    assert lint_yml.exists()
    assert test_yml.exists()
    assert "ruff" in lint_yml.read_text()

    # Should create CLAUDE.md with Python standards reference
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    assert "Python" in claude_md.read_text()

    # Should create permissions with Python tools
    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]
    assert "Bash(uv:*)" in allow
    assert "Bash(python3:*)" in allow


def test_init_language_override_invalid(tmp_path: Path) -> None:
    """Init rejects unsupported language values."""
    import pytest

    (tmp_path / "README.md").write_text("# Test")

    with pytest.raises(SystemExit, match="1"):
        run_init(str(tmp_path), language="rust")


# --- Skill() permission tests ---


def test_build_standard_permissions_includes_skill_entries(tmp_path: Path) -> None:
    """build_standard_permissions returns Skill() entries for all plugins."""
    from punt_kit.detect import detect
    from punt_kit.init import build_standard_permissions

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    info = detect(tmp_path)
    perms = build_standard_permissions(info)

    skill_perms = [p for p in perms if p.startswith("Skill(")]
    expected_skills = _EXPECTED_SKILLS
    assert sorted(skill_perms) == expected_skills, (
        f"Skill perm mismatch:\n"
        f"  missing={sorted(set(expected_skills) - set(skill_perms))}\n"
        f"  extra={sorted(set(skill_perms) - set(expected_skills))}"
    )

    # One representative per plugin group
    assert "Skill(beadle:mail)" in skill_perms
    assert "Skill(biff:who)" in skill_perms
    assert "Skill(commit-commands:commit)" in skill_perms
    assert "Skill(dungeon:d)" in skill_perms
    assert "Skill(ethos:identity)" in skill_perms
    assert "Skill(lux:lux)" in skill_perms
    assert "Skill(prfaq:vote)" in skill_perms
    assert "Skill(punt:audit)" in skill_perms
    assert "Skill(quarry:find)" in skill_perms
    assert "Skill(vox:vox)" in skill_perms
    assert "Skill(z-spec:check)" in skill_perms


def test_init_settings_json_includes_skill_entries(tmp_path: Path) -> None:
    """Init writes Skill() entries into .claude/settings.json."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    allow = data["permissions"]["allow"]
    skill_entries = [p for p in allow if p.startswith("Skill(")]
    expected_skills = _EXPECTED_SKILLS
    assert sorted(skill_entries) == expected_skills, (
        f"Skill perm mismatch:\n"
        f"  missing={sorted(set(expected_skills) - set(skill_entries))}\n"
        f"  extra={sorted(set(skill_entries) - set(expected_skills))}"
    )
