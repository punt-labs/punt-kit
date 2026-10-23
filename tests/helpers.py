"""Public helpers shared by the test modules: projects, git, fault ops."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from punt_kit.detect import detect
from punt_kit.init import build_standard_deny_rules, build_standard_permissions
from punt_kit.phases.phase02_version_bump import Phase2VersionBump
from punt_kit.phases.shared.hook_firing import HookFiringCommand
from punt_kit.phases.shared.timeouts import DEFAULT_RUN
from tests.harness.fault_ops import FaultInjectingOps

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from tests.harness.fault_ops import FaultRule, RunFn

real_which = shutil.which


def run_real(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = DEFAULT_RUN,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` for real, with release.py's own floor on hook-firing timeouts.

    The runner a test hands ``FaultInjectingOps`` for the git it lets through.
    It is independent of ``release._run``, which tests rebind on the module.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=HookFiringCommand(cmd).timeout(timeout),
        check=check,
    )


def git(args: list[str], cwd: str) -> None:
    """Run a git command with standard options."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def git_out(args: list[str], cwd: str) -> str:
    """Run a git command and return its stripped stdout."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit and fake remote."""
    d = str(path)
    git(["init", "-b", "main"], cwd=d)
    git(["config", "user.email", "test@test.com"], cwd=d)
    git(["config", "user.name", "Test"], cwd=d)
    # Create initial commit so HEAD exists
    (path / ".gitkeep").write_text("")
    git(["add", "."], cwd=d)
    git(["commit", "-m", "init"], cwd=d)
    # Set origin to self so fetch/diff work
    git(["remote", "add", "origin", d], cwd=d)
    git(["fetch", "origin"], cwd=d)


def make_release_project(tmp_path: Path, *, subdir: bool = False) -> Path:
    """Create a minimal Python project ready for release testing.

    ``subdir`` selects the DES-025 layout, where the plugin surface lives
    under ``plugin/``.
    """
    root = tmp_path / "proj"
    root.mkdir()

    # Init git first with bare commit
    init_git_repo(root)

    # Now write project files
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n\n'
        "[project.scripts]\ntest-cli = 'test_pkg:main'\n"
    )

    src = root / "src" / "test_pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (src / "py.typed").write_text("")

    plugin_dir = (root / "plugin" if subdir else root) / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {"name": "test-dev", "version": "0.1.0"},
            indent=2,
        )
        + "\n"
    )

    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "git commit --allow-empty"
        ' -m "chore: prepare plugin for release"\n'
    )
    (scripts_dir / "restore-dev-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "git commit --allow-empty"
        ' -m "chore: restore dev plugin state"\n'
    )

    # Placeholder so info.workflow_files includes "release.yml" — Phase 6
    # (_phase6_ci_wait) fails fast when it's absent for a hybrid/non-plugin
    # project. Content is irrelevant; only the filename matters
    # to detect().
    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "release.yml").write_text("")

    (root / "install.sh").write_text(
        '#!/bin/sh\nPACKAGE="test-pkg"\nVERSION="0.1.0"\n'
        'uv tool install --force "$PACKAGE==$VERSION"\n'
    )

    install_url = (
        "https://raw.githubusercontent.com/punt-labs/test-pkg/v0.1.0/install.sh"
    )
    (root / "README.md").write_text(
        f"# test-pkg\n\n```bash\ncurl -fsSL {install_url} | sh\n```\n"
    )

    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n"
        "- Initial release\n"
    )

    d = str(root)
    git(["add", "."], cwd=d)
    git(["commit", "-m", "scaffold"], cwd=d)
    git(["fetch", "origin"], cwd=d)

    return root


def make_sibling(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """Create a sibling git repo with given files."""
    sibling = tmp_path / name
    sibling.mkdir(parents=True, exist_ok=True)
    init_git_repo(sibling)
    for filepath, content in files.items():
        (sibling / filepath).parent.mkdir(parents=True, exist_ok=True)
        (sibling / filepath).write_text(content)
    if files:
        git(["add", "."], cwd=str(sibling))
        git(["commit", "-m", f"init {name}"], cwd=str(sibling))
    git(["fetch", "origin"], cwd=str(sibling))
    return sibling


def fault_ops(
    rules: Sequence[FaultRule] = (),
    *,
    real_run: RunFn = run_real,
    passthrough: Sequence[Sequence[str]] = (),
) -> FaultInjectingOps:
    """Build the ``ReleaseOps`` double every test shares.

    Real ``git`` runs through ``real_run``; anything else must match a rule or
    ``passthrough``, so a forgotten ``gh`` rule fails loudly instead of
    reaching GitHub.
    """
    return FaultInjectingOps(real_run=real_run, rules=rules, passthrough=passthrough)


def flat(text: str) -> str:
    """Collapse rich's width-dependent line wrapping into single spaces."""
    return " ".join(text.split())


def fake_which(_name: str) -> str:
    """Stand in for a gh binary so phase 6 gets past its tool check."""
    return "/usr/bin/gh"


def bump(root: Path, version: str = "0.2.0") -> None:
    Phase2VersionBump(detect(root), version, dry_run=False, ops=fault_ops()).run()


def commit_all(root: Path, message: str) -> None:
    git(["add", "."], cwd=str(root))
    git(["commit", "-m", message], cwd=str(root))


def project_with_origin(tmp_path: Path) -> ProjectInfo:
    root = make_release_project(tmp_path)
    git(["tag", "v0.2.0"], cwd=str(root))
    git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=str(root),
    )
    return detect(root)


def no_bd(
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
    return real_which(cmd, mode, path)


def python_project(root: Path) -> None:
    (root / "pyproject.toml").write_text('[project]\nname = "test-pkg"\n')


def make_compliant_python(tmp_path: Path) -> None:
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


def make_compliant_hybrid(tmp_path: Path) -> None:
    """Create a compliant hybrid project (CLI + plugin) scaffold."""
    make_compliant_python(tmp_path)

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


def refuse_run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 0,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"version checks read files only, not {cmd}")


def fake_bd(directory: Path, script: str) -> str:
    """Put a ``bd`` that is ``script`` on PATH and return the directory to prepend."""
    directory.mkdir()
    bd = directory / "bd"
    bd.write_text(script)
    bd.chmod(0o755)
    return str(directory)
