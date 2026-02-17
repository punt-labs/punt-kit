"""punt audit — read-only compliance check against Punt Labs standards."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect

console = Console()

PASS = "[green]✓[/green]"
FAIL = "[red]✗[/red]"
INFO = "[dim]○[/dim]"


def run_audit(path: str) -> None:
    """Check compliance against Punt Labs standards."""
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    info = detect(root)

    console.print(f"\n[bold]punt audit[/bold] — {root.name}")
    console.print(f"  Language: {info.language or 'none'}  Type: {info.project_type or 'unknown'}\n")

    results: list[tuple[str, str, str]] = []

    # CI checks
    results.extend(_check_ci(info))

    # Tool config checks
    results.extend(_check_tool_config(info))

    # Beads check
    results.extend(_check_beads(info))

    # CLAUDE.md check
    results.extend(_check_claude_md(info))

    # GitHub API checks (if gh available)
    results.extend(_check_github_settings(info))

    # Print results
    passes = 0
    failures = 0
    for status, label, detail in results:
        console.print(f"  {status} {label}")
        if detail:
            console.print(f"      [dim]{detail}[/dim]")
        if status == PASS:
            passes += 1
        elif status == FAIL:
            failures += 1

    console.print(f"\n  [bold]{passes} passed[/bold], [bold]{failures} failed[/bold]\n")


def _check_ci(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check CI workflow existence per project type."""
    results: list[tuple[str, str, str]] = []
    workflows_dir = info.root / ".github" / "workflows"

    if info.language == "python":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append((
            PASS if lint_exists else FAIL,
            "CI lint workflow exists",
            ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
        ))

        test_exists = (workflows_dir / "test.yml").exists()
        results.append((
            PASS if test_exists else FAIL,
            "CI test workflow exists",
            ".github/workflows/test.yml" if test_exists else "Missing test.yml",
        ))

    elif info.language == "node":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append((
            PASS if lint_exists else FAIL,
            "CI lint workflow exists",
            ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
        ))

    elif info.language == "swift":
        build_exists = (workflows_dir / "build.yml").exists()
        results.append((
            PASS if build_exists else FAIL,
            "CI build workflow exists",
            ".github/workflows/build.yml" if build_exists else "Missing build.yml",
        ))

    # All repos should have docs.yml
    docs_exists = (workflows_dir / "docs.yml").exists()
    results.append((
        PASS if docs_exists else FAIL,
        "CI docs workflow exists",
        ".github/workflows/docs.yml" if docs_exists else "Missing docs.yml",
    ))

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
    results.append((
        PASS if ruff else FAIL,
        r"Linting configured (\[tool.ruff])",
        r"in pyproject.toml" if ruff else r"Missing \[tool.ruff] in pyproject.toml",
    ))

    mypy = tool.get("mypy")
    results.append((
        PASS if mypy else FAIL,
        r"Type checking configured (\[tool.mypy])",
        r"in pyproject.toml" if mypy else r"Missing \[tool.mypy] in pyproject.toml",
    ))

    pyright = tool.get("pyright")
    results.append((
        PASS if pyright else FAIL,
        r"Type checking configured (\[tool.pyright])",
        r"in pyproject.toml" if pyright else r"Missing \[tool.pyright] in pyproject.toml",
    ))

    pytest_cfg = tool.get("pytest", {}).get("ini_options")
    results.append((
        PASS if pytest_cfg else FAIL,
        r"Test config exists (\[tool.pytest.ini_options])",
        r"in pyproject.toml" if pytest_cfg else r"Missing \[tool.pytest.ini_options]",
    ))

    return results


def _check_beads(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if beads is initialized."""
    return [(
        PASS if info.has_beads else FAIL,
        "Beads initialized",
        ".beads/ directory" if info.has_beads else "Missing .beads/ — run bd init",
    )]


def _check_claude_md(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if CLAUDE.md exists."""
    return [(
        PASS if info.has_claude_md else FAIL,
        "CLAUDE.md exists",
        "" if info.has_claude_md else "Missing CLAUDE.md",
    )]


def _check_github_settings(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check GitHub repo settings via gh API. Falls back gracefully."""
    results: list[tuple[str, str, str]] = []

    gh = shutil.which("gh")
    if gh is None:
        results.append((INFO, "GitHub settings (gh CLI not available)", "Install gh to check remote settings"))
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
            results.append((
                PASS if pr_required else FAIL,
                "Branch protection: PR required",
                "",
            ))

            status_checks = protection.get("required_status_checks") is not None
            results.append((
                PASS if status_checks else FAIL,
                "Branch protection: status checks required",
                "",
            ))
        else:
            results.append((FAIL, "Branch protection on main", "Not configured or no access"))
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
        results.append((
            PASS if enabled else FAIL,
            "Dependabot vulnerability alerts",
            "Enabled" if enabled else "Not enabled",
        ))
    except (subprocess.TimeoutExpired, OSError):
        results.append((INFO, "Dependabot alerts (could not check)", ""))

    return results


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
