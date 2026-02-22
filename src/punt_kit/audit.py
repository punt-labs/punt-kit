"""punt audit — compliance check against Punt Labs standards."""

from __future__ import annotations

import importlib.resources
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import cast

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect
from punt_kit.init import build_standard_permissions

console = Console()

TEMPLATES = importlib.resources.files("punt_kit") / "templates"

PASS = "[green]✓[/green]"
FAIL = "[red]✗[/red]"
FIXED = "[yellow]⚡[/yellow]"
INFO = "[dim]○[/dim]"


def run_audit(path: str, *, fix: bool = False) -> None:
    """Check compliance against Punt Labs standards.

    When *fix* is True, create missing mechanical files from templates.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    info = detect(root)

    mode = "[bold]punt audit --fix[/bold]" if fix else "[bold]punt audit[/bold]"
    console.print(f"\n{mode} — {root.name}")
    lang = info.language or "none"
    ptype = info.project_type or "unknown"
    console.print(f"  Language: {lang}  Type: {ptype}\n")

    results: list[tuple[str, str, str]] = []

    results.extend(_check_ci(info))
    results.extend(_check_tool_config(info))
    results.extend(_check_markdownlint(info, fix=fix))
    results.extend(_check_markdownlint_content(info))
    results.extend(_check_py_typed(info, fix=fix))
    results.extend(_check_changelog(info, fix=fix))
    results.extend(_check_beads(info))
    results.extend(_check_claude_md(info))
    results.extend(_check_permissions(info))
    results.extend(_check_plugin_dev_isolation(info))
    results.extend(_check_github_settings(info))

    # Print results
    passes = 0
    failures = 0
    fixes = 0
    for status, label, detail in results:
        console.print(f"  {status} {label}")
        if detail:
            console.print(f"      [dim]{detail}[/dim]")
        if status == PASS:
            passes += 1
        elif status == FAIL:
            failures += 1
        elif status == FIXED:
            fixes += 1

    summary = f"  [bold]{passes} passed[/bold], [bold]{failures} failed[/bold]"
    if fixes:
        summary += f", [bold yellow]{fixes} fixed[/bold yellow]"
    console.print(f"\n{summary}\n")

    if failures > 0:
        raise SystemExit(1)


def _check_ci(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check CI workflow existence per project type."""
    results: list[tuple[str, str, str]] = []
    workflows_dir = info.root / ".github" / "workflows"

    if info.language == "python":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append(
            (
                PASS if lint_exists else FAIL,
                "CI lint workflow exists",
                ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
            )
        )

        test_exists = (workflows_dir / "test.yml").exists()
        results.append(
            (
                PASS if test_exists else FAIL,
                "CI test workflow exists",
                ".github/workflows/test.yml" if test_exists else "Missing test.yml",
            )
        )

    elif info.language == "node":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append(
            (
                PASS if lint_exists else FAIL,
                "CI lint workflow exists",
                ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
            )
        )

    elif info.language == "swift":
        build_exists = (workflows_dir / "build.yml").exists()
        results.append(
            (
                PASS if build_exists else FAIL,
                "CI build workflow exists",
                ".github/workflows/build.yml" if build_exists else "Missing build.yml",
            )
        )

    # All repos should have docs.yml
    docs_exists = (workflows_dir / "docs.yml").exists()
    results.append(
        (
            PASS if docs_exists else FAIL,
            "CI docs workflow exists",
            ".github/workflows/docs.yml" if docs_exists else "Missing docs.yml",
        )
    )

    return results


def _check_tool_config(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check language-specific tool configuration."""
    results: list[tuple[str, str, str]] = []

    if info.language != "python":
        return results

    pyproject_path = info.root / "pyproject.toml"
    if not pyproject_path.exists():
        results.append((FAIL, "pyproject.toml exists", "Missing"))
        return results

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    tool = data.get("tool", {})

    ruff = tool.get("ruff")
    results.append(
        (
            PASS if ruff else FAIL,
            r"Linting configured (\[tool.ruff])",
            r"in pyproject.toml" if ruff else r"Missing \[tool.ruff] in pyproject.toml",
        )
    )

    mypy = tool.get("mypy")
    results.append(
        (
            PASS if mypy else FAIL,
            r"Type checking configured (\[tool.mypy])",
            r"in pyproject.toml" if mypy else r"Missing \[tool.mypy] in pyproject.toml",
        )
    )

    pyright = tool.get("pyright")
    results.append(
        (
            PASS if pyright else FAIL,
            r"Type checking configured (\[tool.pyright])",
            r"in pyproject.toml"
            if pyright
            else r"Missing \[tool.pyright] in pyproject.toml",
        )
    )

    pytest_cfg = tool.get("pytest", {}).get("ini_options")
    results.append(
        (
            PASS if pytest_cfg else FAIL,
            r"Test config exists (\[tool.pytest.ini_options])",
            r"in pyproject.toml"
            if pytest_cfg
            else r"Missing \[tool.pytest.ini_options]",
        )
    )

    return results


def _check_markdownlint(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check markdownlint configuration files."""
    results: list[tuple[str, str, str]] = []

    # Template files stored without dot prefix to avoid setuptools dotfile issues
    configs = {
        ".markdownlint.jsonc": "markdownlint.jsonc",
        ".markdownlint-cli2.jsonc": "markdownlint-cli2.jsonc",
    }

    for filename, template_name in configs.items():
        target = info.root / filename
        if target.exists():
            results.append((PASS, f"{filename} exists", ""))
        elif fix:
            template_ref = TEMPLATES / template_name
            content = template_ref.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8")
            results.append((FIXED, f"{filename} created", ""))
        else:
            results.append(
                (FAIL, f"{filename} exists", "Missing — run punt audit --fix")
            )

    return results


def _check_markdownlint_content(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Run markdownlint-cli2 on tracked markdown files to catch content errors."""
    npx = shutil.which("npx")
    if npx is None:
        return [(INFO, "Markdown lint (npx not available)", "Install Node.js to run")]

    # Only lint git-tracked files to avoid scratch file noise
    tracked_md = _get_tracked_markdown(info.root)
    if not tracked_md:
        return [(INFO, "Markdown lint (no tracked .md files)", "")]

    try:
        result = subprocess.run(
            [npx, "--yes", "markdownlint-cli2", *tracked_md],
            cwd=str(info.root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return [
                (PASS, "Markdown lint passes", f"{len(tracked_md)} file(s) checked")
            ]
        # Count errors from output
        error_lines = [
            line
            for line in result.stdout.splitlines()
            if " error " in line or "MD0" in line
        ]
        return [
            (
                FAIL,
                "Markdown lint passes",
                f"{len(error_lines)} error(s) — run: npx markdownlint-cli2 '**/*.md'",
            )
        ]
    except subprocess.TimeoutExpired:
        return [(INFO, "Markdown lint (timed out)", "")]
    except OSError:
        return [(INFO, "Markdown lint (could not run)", "")]


def _get_tracked_markdown(root: Path) -> list[str]:
    """Get list of git-tracked markdown files relative to root."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "*.md", "**/*.md"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().splitlines() if f.endswith(".md")]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _check_py_typed(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check py.typed marker file for Python packages."""
    if info.language != "python":
        return []

    pkg_dir = _find_package_dir(info)
    if pkg_dir is None:
        return [(INFO, "py.typed marker", "Could not determine package directory")]

    py_typed = pkg_dir / "py.typed"
    if py_typed.exists():
        return [(PASS, "py.typed marker exists", str(_relpath(py_typed, info.root)))]

    if fix:
        py_typed.write_text("")
        return [(FIXED, "py.typed marker created", str(_relpath(py_typed, info.root)))]

    return [
        (
            FAIL,
            "py.typed marker exists",
            f"Missing {_relpath(py_typed, info.root)} — run punt audit --fix",
        )
    ]


def _check_changelog(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check CHANGELOG.md exists."""
    changelog = info.root / "CHANGELOG.md"
    if changelog.exists():
        return [(PASS, "CHANGELOG.md exists", "")]

    if fix:
        project_name = _get_project_name(info)
        changelog.write_text(
            f"# Changelog\n\nAll notable changes to {project_name} "
            "will be documented in this file.\n\n"
            "The format is based on "
            "[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n",
            encoding="utf-8",
        )
        return [(FIXED, "CHANGELOG.md created", "")]

    return [(FAIL, "CHANGELOG.md exists", "Missing — run punt audit --fix")]


def _check_beads(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if beads is initialized."""
    return [
        (
            PASS if info.has_beads else FAIL,
            "Beads initialized",
            ".beads/ directory" if info.has_beads else "Missing .beads/ — run bd init",
        )
    ]


def _check_claude_md(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if CLAUDE.md exists."""
    return [
        (
            PASS if info.has_claude_md else FAIL,
            "CLAUDE.md exists",
            "" if info.has_claude_md else "Missing CLAUDE.md — run punt init",
        )
    ]


def _check_github_settings(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check GitHub repo settings via gh API. Falls back gracefully."""
    results: list[tuple[str, str, str]] = []

    gh = shutil.which("gh")
    if gh is None:
        results.append(
            (
                INFO,
                "GitHub settings (gh CLI not available)",
                "Install gh to check remote settings",
            )
        )
        return results

    # Detect repo from git remote
    repo = _get_github_repo(info.root)
    if repo is None:
        results.append((INFO, "GitHub settings (no remote detected)", ""))
        return results

    # Check branch protection
    try:
        result = subprocess.run(
            [gh, "api", f"repos/{repo}/branches/main/protection"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            protection = json.loads(result.stdout)
            pr_required = protection.get("required_pull_request_reviews") is not None
            results.append(
                (
                    PASS if pr_required else FAIL,
                    "Branch protection: PR required",
                    "",
                )
            )

            status_checks = protection.get("required_status_checks") is not None
            results.append(
                (
                    PASS if status_checks else FAIL,
                    "Branch protection: status checks required",
                    "",
                )
            )
        else:
            results.append(
                (
                    FAIL,
                    "Branch protection on main",
                    "Not configured or no access",
                )
            )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        results.append((INFO, "Branch protection (could not check)", ""))

    # Check Dependabot / vulnerability alerts
    try:
        result = subprocess.run(
            [gh, "api", f"repos/{repo}/vulnerability-alerts", "--include", "-X", "GET"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # 204 means enabled, 404 means disabled
        enabled = "204" in (result.stderr + result.stdout) or result.returncode == 0
        results.append(
            (
                PASS if enabled else FAIL,
                "Dependabot vulnerability alerts",
                "Enabled" if enabled else "Not enabled",
            )
        )
    except (subprocess.TimeoutExpired, OSError):
        results.append((INFO, "Dependabot alerts (could not check)", ""))

    return results


def _check_permissions(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check .claude/settings.json has standard permissions for this project type."""
    results: list[tuple[str, str, str]] = []
    settings_path = info.root / ".claude" / "settings.json"

    if not settings_path.exists():
        results.append(
            (
                FAIL,
                ".claude/settings.json exists",
                "Missing — run punt init",
            )
        )
        return results

    results.append((PASS, ".claude/settings.json exists", ""))

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        results.append((FAIL, "settings.json is valid JSON", "Parse error"))
        return results

    if not isinstance(data, dict):
        results.append((FAIL, "settings.json is valid JSON", "Expected object"))
        return results

    typed_data = cast("dict[str, object]", data)

    perms_raw = typed_data.get("permissions")
    if not isinstance(perms_raw, dict):
        results.append((FAIL, "Standard permissions present", "No permissions key"))
        return results

    perms = cast("dict[str, object]", perms_raw)
    allow_raw = perms.get("allow")
    if not isinstance(allow_raw, list):
        results.append((FAIL, "Standard permissions present", "Missing allow array"))
        return results

    allow_strs = [str(x) for x in cast("list[object]", allow_raw)]

    standard = build_standard_permissions(info)
    missing = [p for p in standard if p not in allow_strs]

    if missing:
        results.append(
            (
                FAIL,
                "Standard permissions present",
                f"Missing {len(missing)}: {', '.join(missing[:5])}"
                + ("..." if len(missing) > 5 else ""),
            )
        )
    else:
        results.append(
            (PASS, "Standard permissions present", f"{len(standard)} standard entries")
        )

    return results


def _check_plugin_dev_isolation(
    info: ProjectInfo,
) -> list[tuple[str, str, str]]:
    """Check plugin repos follow the dev/prod namespace isolation standard.

    Checks:
    1. plugin.json name ends in -dev (working tree is the dev namespace)
    2. Every prod command has a -dev variant
    3. Release/restore scripts exist
    """
    if not info.is_plugin:
        return []

    results: list[tuple[str, str, str]] = []

    # Check plugin name has -dev suffix
    plugin_name = _read_plugin_name(info)
    if plugin_name is not None:
        if plugin_name.endswith("-dev"):
            results.append((PASS, "Plugin name has -dev suffix", plugin_name))
        else:
            results.append(
                (
                    FAIL,
                    "Plugin name has -dev suffix",
                    f"'{plugin_name}' — should be '{plugin_name}-dev'",
                )
            )

    # Check release/restore scripts exist
    release_script = info.root / "scripts" / "release-plugin.sh"
    restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
    if release_script.exists() and restore_script.exists():
        results.append((PASS, "Release/restore scripts exist", ""))
    else:
        missing_scripts: list[str] = []
        if not release_script.exists():
            missing_scripts.append("scripts/release-plugin.sh")
        if not restore_script.exists():
            missing_scripts.append("scripts/restore-dev-plugin.sh")
        detail = f"Missing: {', '.join(missing_scripts)}"
        results.append((FAIL, "Release/restore scripts exist", detail))

    # Check -dev command variants
    commands_dir = info.root / "commands"
    if commands_dir.is_dir():
        prod_commands = sorted(
            f.stem for f in commands_dir.glob("*.md") if not f.stem.endswith("-dev")
        )
        dev_commands = sorted(
            f.stem.removesuffix("-dev") for f in commands_dir.glob("*-dev.md")
        )

        if prod_commands:
            missing = [c for c in prod_commands if c not in dev_commands]
            if missing:
                results.append(
                    (
                        FAIL,
                        "Dev command variants exist",
                        f"Missing: {', '.join(f'{c}-dev.md' for c in missing)}",
                    )
                )
            else:
                results.append(
                    (
                        PASS,
                        "Dev command variants exist",
                        f"{len(dev_commands)} dev commands",
                    )
                )

    return results


def _read_plugin_name(info: ProjectInfo) -> str | None:
    """Read plugin name from plugin.json."""
    for pj_path in (
        info.root / ".claude-plugin" / "plugin.json",
        info.root / "plugin.json",
    ):
        if pj_path.exists():
            try:
                data = json.loads(pj_path.read_text(encoding="utf-8"))
                name = data.get("name")
                if isinstance(name, str):
                    return name
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    src_dir = info.root / "src"
    if not src_dir.is_dir():
        return None

    # Look for directories with __init__.py under src/
    for child in sorted(src_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child

    return None


def _get_project_name(info: ProjectInfo) -> str:
    """Extract human-readable project name from metadata."""
    if info.pyproject is not None:
        project_raw = info.pyproject.get("project")
        if isinstance(project_raw, dict):
            project = cast("dict[str, object]", project_raw)
            name = project.get("name")
            if isinstance(name, str):
                return name

    return info.root.name


def _relpath(path: Path, root: Path) -> str:
    """Return path relative to root as a string."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        url = result.stdout.strip()
        # Handle SSH format: git@github.com:owner/repo.git
        if url.startswith("git@github.com:"):
            repo = url.removeprefix("git@github.com:").removesuffix(".git")
            return repo
        # Handle HTTPS format: https://github.com/owner/repo.git
        if "github.com/" in url:
            parts = url.split("github.com/")[1].removesuffix(".git")
            return parts
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None
