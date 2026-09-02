"""Tests for init command."""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from pathlib import Path

import pytest

from punt_kit.init import STANDARD_SKILL_PERMISSIONS, run_init

_EXPECTED_SKILLS: list[str] = sorted(STANDARD_SKILL_PERMISSIONS)


_real_which = shutil.which


def _no_bd(
    cmd: str, mode: int = os.F_OK | os.X_OK, path: str | None = None
) -> str | None:
    """A ``shutil.which`` stand-in reporting only ``bd`` as not installed.

    Tests asserting exact post-``run_init`` file content must not depend on
    whatever gitignore patterns the locally installed ``bd`` binary's own
    ``init`` appends — that behavior belongs to bd, and drifts independently
    of this repo's release. Every other lookup delegates to the real
    ``shutil.which`` (signature mirrored exactly, not ``*args``/``**kwargs``,
    so a call passing ``mode``/``path`` type-checks and behaves identically
    to the unpatched function) — a blanket ``None`` for every command would
    silently disable other ``which()`` lookups a future call site adds.
    """
    if cmd == "bd":
        return None
    return _real_which(cmd, mode, path)


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

    # Every Punt Labs plugin that ships skills is represented. Naming
    # individual skills here is what let the list drift: the old assertion
    # required Skill(commit-commands:commit), which is not a Punt Labs plugin
    # and was never installed, so the test passed while the list was wrong.
    plugins = {p.split("(")[1].split(":")[0] for p in skill_perms}
    assert plugins >= {
        "beadle",
        "biff",
        "dungeon",
        "ethos",
        "lux",
        "prfaq",
        "punt",
        "quarry",
        "vox",
        "z-spec",
    }


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


# --- Unmatched path rule tests ---


def test_deny_rules_have_no_dead_path_forms() -> None:
    """The seeder never emits a rule Claude Code cannot match."""
    from punt_kit.init import build_standard_deny_rules
    from punt_kit.permission_rules import RuleSet

    assert RuleSet.from_strings(build_standard_deny_rules()).dead == ()


def test_standard_permissions_have_no_dead_path_forms(tmp_path: Path) -> None:
    """The allow list is free of unmatched path rules for every language."""
    from punt_kit.detect import detect
    from punt_kit.init import build_standard_permissions
    from punt_kit.permission_rules import RuleSet

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    info = detect(tmp_path)

    assert RuleSet.from_strings(build_standard_permissions(info)).dead == ()


def test_deny_rules_guard_env_via_edit() -> None:
    """Edit(.env) is the guard; Write(.env) is dead and must not appear."""
    from punt_kit.init import build_standard_deny_rules

    deny = build_standard_deny_rules()
    assert "Edit(.env)" in deny
    assert "Edit(.envrc)" in deny
    assert "Write(.env)" not in deny
    assert "Write(.envrc)" not in deny


def test_init_prunes_dead_rules_from_existing_settings(tmp_path: Path) -> None:
    """Init removes seeded Write(...) entries that duplicate a live Edit(...)."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": ["Bash(git:*)"],
                    "deny": ["Edit(.env)", "Write(.env)", "Edit(.envrc)"],
                }
            }
        )
    )

    run_init(str(tmp_path))

    data = json.loads((settings_dir / "settings.json").read_text())
    deny = data["permissions"]["deny"]
    assert "Write(.env)" not in deny
    assert "Edit(.env)" in deny
    assert "Edit(.envrc)" in deny


def test_init_drops_orphan_dead_allow_rule(tmp_path: Path) -> None:
    """An allow-tier orphan is dropped — cleanup must not activate a grant."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Write(docs/**)", "Bash(git:*)"]}})
    )

    run_init(str(tmp_path))

    allow = json.loads((settings_dir / "settings.json").read_text())["permissions"][
        "allow"
    ]
    assert "Write(docs/**)" not in allow
    assert "Edit(docs/**)" not in allow
    assert "Bash(git:*)" in allow


def test_init_drops_orphan_dead_deny_rule_without_activating_it(
    tmp_path: Path,
) -> None:
    """A deny orphan is removed, not switched on.

    Rewriting it to Edit(secrets/**) would activate a block that has never
    been in effect, and a deny cannot be overridden by approval — that can
    hard-break a workflow that has been writing the path for months.
    """
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"permissions": {"allow": [], "deny": ["Write(secrets/**)"]}})
    )

    run_init(str(tmp_path))

    deny = json.loads((settings_dir / "settings.json").read_text())["permissions"][
        "deny"
    ]
    assert "Write(secrets/**)" not in deny
    assert "Edit(secrets/**)" not in deny


def test_init_reports_why_each_rule_was_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A covered rule and an orphan are different situations for the operator."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [],
                    "deny": ["Edit(.env)", "Write(.env)", "Write(secrets/**)"],
                }
            }
        )
    )

    run_init(str(tmp_path))

    out = capsys.readouterr().out
    assert "already covers it" in out
    assert "never took effect" in out
    assert "Edit(secrets/**)" in out


def test_init_output_has_no_dead_rules(tmp_path: Path) -> None:
    """A freshly seeded settings.json triggers zero startup warnings."""
    import json

    from punt_kit.permission_rules import RuleSet

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')

    run_init(str(tmp_path))

    perms = json.loads((tmp_path / ".claude" / "settings.json").read_text())[
        "permissions"
    ]
    for tier in ("allow", "deny"):
        assert RuleSet.from_strings(perms[tier]).dead == (), f"dead rule in {tier}"


def test_init_leaves_malformed_permission_tier_untouched(tmp_path: Path) -> None:
    """A non-string entry is preserved verbatim rather than coerced to its repr."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": ["Write(docs/**)", {"unexpected": "object"}],
                    "deny": ["Edit(.env)", "Write(.env)"],
                }
            }
        )
    )

    run_init(str(tmp_path))

    data = json.loads((settings_dir / "settings.json").read_text())
    allow = data["permissions"]["allow"]
    # The malformed tier is left alone entirely — including its dead rule.
    assert {"unexpected": "object"} in allow
    assert "Write(docs/**)" in allow
    # A well-formed tier in the same file is still pruned.
    assert "Write(.env)" not in data["permissions"]["deny"]


def test_init_prunes_settings_local(tmp_path: Path) -> None:
    """The gitignored local file warns too, so init cleans it as well."""
    import json

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Read(/abs/**)",
                        "Edit(/abs/**)",
                        "Write(/abs/**)",
                        "Bash(say:*)",
                    ]
                }
            }
        )
    )

    run_init(str(tmp_path))

    allow = json.loads((settings_dir / "settings.local.json").read_text())[
        "permissions"
    ]["allow"]
    assert "Write(/abs/**)" not in allow
    assert "Edit(/abs/**)" in allow
    assert "Read(/abs/**)" in allow
    assert "Bash(say:*)" in allow


def test_init_leaves_clean_settings_local_untouched(tmp_path: Path) -> None:
    """A local file with nothing dead in it is not rewritten at all."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    local = settings_dir / "settings.local.json"
    original = '{"permissions": {"allow": ["Bash(say:*)"]}}'
    local.write_text(original)

    run_init(str(tmp_path))

    # Byte-identical: no reformatting of the developer's personal file.
    assert local.read_text() == original


def test_init_tolerates_malformed_settings_local(tmp_path: Path) -> None:
    """Unparseable local settings are left alone rather than crashing init."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    local = settings_dir / "settings.local.json"
    local.write_text("{not json")

    run_init(str(tmp_path))

    assert local.read_text() == "{not json"


# --- gitignore .claude stanza tests ---


def test_init_leaves_a_foreign_claude_stanza_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stanza punt did not write is never appended to.

    Under a `.claude/*` parent git descends into the directory, so the
    exception lines become live rules that re-include paths the repo has
    never tracked. Seeding must not change what a repo currently ignores.

    ``bd`` is disabled: this test asserts the ``.gitignore`` is byte-for-byte
    unchanged, which is a claim about punt's own ``.claude`` stanza handling,
    not about whatever gitignore patterns the locally installed ``bd``
    binary's own ``init`` happens to append — that behavior is bd's to test,
    and drifts independently of this repo's release.
    """
    monkeypatch.setattr(shutil, "which", _no_bd)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    gitignore = tmp_path / ".gitignore"
    original = "# deliberate stanza\n.claude/*\n!.claude/settings.json\n"
    gitignore.write_text(original)

    run_init(str(tmp_path))

    assert gitignore.read_text() == original


def test_init_seeds_exceptions_under_the_exact_parent(tmp_path: Path) -> None:
    """Under the parent punt writes, the exceptions behave as intended."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".claude/\n")

    run_init(str(tmp_path))

    lines = [ln.strip() for ln in gitignore.read_text().split("\n")]
    assert "!.claude/settings.json" in lines
    assert "!.claude/hooks/" in lines


def test_init_writes_the_full_block_when_no_claude_stanza_exists(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n")

    run_init(str(tmp_path))

    lines = [ln.strip() for ln in gitignore.read_text().split("\n")]
    assert "node_modules/" in lines
    assert ".claude/" in lines
    assert "!.claude/hooks/" in lines


def test_init_never_activates_a_dormant_negation(tmp_path: Path) -> None:
    """The invariant, not the case: what git ignores must not change.

    Asserted by asking git itself, before and after, rather than by
    inspecting the file.
    """
    import subprocess

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    (tmp_path / ".gitignore").write_text(".claude/*\n!.claude/settings.json\n")
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre.sh").write_text("#!/bin/sh\n")
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)

    def ignored() -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", ".claude/hooks/pre.sh"],
                cwd=tmp_path,
                check=False,
            ).returncode
            == 0
        )

    before = ignored()
    run_init(str(tmp_path))
    assert ignored() == before, "punt init changed what git ignores"


@pytest.mark.parametrize(
    "stanza", ["/.claude/", ".claude/*", "/.claude/*", "**/.claude/*", ".claude"]
)
def test_init_respects_every_claude_stanza_spelling(
    tmp_path: Path, stanza: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchored and globbed forms are stanzas too.

    An anchored `/.claude/` reaching the "no reference" branch would get the
    unanchored block appended, broadening the ignore from root-only to any
    depth — the same invariant violation this guard exists to prevent.

    ``bd`` is disabled — see ``_no_bd``.
    """
    monkeypatch.setattr(shutil, "which", _no_bd)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    gitignore = tmp_path / ".gitignore"
    original = stanza + "\n"
    gitignore.write_text(original)

    run_init(str(tmp_path))

    assert gitignore.read_text() == original


def test_foreign_stanza_warning_omits_the_anchor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Suggesting `.claude/` to a repo that chose `.claude/*` contradicts it."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    (tmp_path / ".gitignore").write_text(".claude/*\n")

    run_init(str(tmp_path))

    out = capsys.readouterr().out
    assert "stanza" in out
    assert "!.claude/settings.json" in out or "settings.json" in out


def test_foreign_stanza_warning_has_no_empty_suggestion_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With every exception already present there is nothing to suggest."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    (tmp_path / ".gitignore").write_text(
        ".claude/*\n!.claude/settings.json\n!.claude/hooks/\n"
    )

    run_init(str(tmp_path))

    assert "Add these by hand" not in capsys.readouterr().out


# --- seeded permission set tests ---


def test_seeder_never_grants_an_unrestricted_shell() -> None:
    """Bash(bash:*) matches `bash -c "<anything>"`.

    It would make every other Bash entry decorative and reach straight through
    the deny rules — `bash -c "curl ..."` satisfies the allow list while
    Bash(curl:*) is denied.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.init import build_standard_permissions

    perms = build_standard_permissions(ProjectInfo(root=Path("/nonexistent")))
    assert "Bash(bash:*)" not in perms
    assert "Bash(sed:*)" not in perms


def test_seeder_keeps_the_development_tools() -> None:
    """git and gh are dev tools; this scaffolds a dev environment."""
    from punt_kit.detect import ProjectInfo
    from punt_kit.init import build_standard_permissions

    perms = build_standard_permissions(ProjectInfo(root=Path("/nonexistent")))
    assert "Bash(git:*)" in perms
    assert "Bash(gh:*)" in perms


def test_mcp_wildcards_name_real_plugin_servers() -> None:
    """Each wildcard must be derivable from a plugin manifest.

    A wildcard naming a plugin that ships no MCP server matches nothing while
    looking like a working grant — that is how `mcp__plugin_github_github__*`
    survived in this list despite there being no github plugin.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.init import build_standard_permissions

    perms = build_standard_permissions(ProjectInfo(root=Path("/nonexistent")))
    plugin_wildcards = {p for p in perms if p.startswith("mcp__plugin_")}

    # plugin -> server key, from each plugin's .claude-plugin/plugin.json
    known = {
        "beadle": "email",
        "biff": "tty",
        "dungeon": "grimoire",
        "ethos": "self",
        "lux": "lux",
        "quarry": "quarry",
        "vox": "mic",
        "z-spec": "zspec",
    }
    expected = {f"mcp__plugin_{p}_{s}__*" for p, s in known.items()}
    assert plugin_wildcards == expected


def test_mcp_wildcards_are_all_or_nothing() -> None:
    """A subset is not a policy — it is whoever edited the list last."""
    from punt_kit.detect import ProjectInfo
    from punt_kit.init import build_standard_permissions

    perms = build_standard_permissions(ProjectInfo(root=Path("/nonexistent")))
    # prfaq and punt ship no MCP server, so they must not appear.
    assert not any("prfaq" in p for p in perms if p.startswith("mcp__"))
    assert not any(p.startswith("mcp__plugin_punt_") for p in perms)
