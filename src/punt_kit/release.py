"""punt release — deterministic release workflow for Punt Labs projects."""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn, cast

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 7200,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with standard options."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


def _fail(msg: str) -> NoReturn:
    """Print error and exit."""
    console.print(f"[red]Error:[/red] {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def _info(msg: str) -> None:
    console.print(f"  [dim]▶[/dim] {msg}")


def _dry(msg: str) -> None:
    console.print(f"  [yellow]DRY[/yellow] {msg}")


def _get_project_version(info: ProjectInfo) -> str:
    """Extract current version from pyproject.toml."""
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    version = cast("dict[str, object]", project).get("version")
    if not isinstance(version, str):
        _fail("No version in pyproject.toml [project]")
    return version


def _get_package_name(info: ProjectInfo) -> str:
    """Extract package name from pyproject.toml."""
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    name = cast("dict[str, object]", project).get("name")
    if not isinstance(name, str):
        _fail("No name in pyproject.toml [project]")
    return name


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    src_dir = info.root / "src"
    if not src_dir.is_dir():
        return None
    for child in sorted(src_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child
    return None


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    try:
        result = _run(
            ["git", "remote", "get-url", "origin"], cwd=str(root), check=False
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        if url.startswith("git@github.com:"):
            return url.removeprefix("git@github.com:").removesuffix(".git")
        if "github.com/" in url:
            return url.split("github.com/")[1].removesuffix(".git")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _read_changelog(root: Path) -> str:
    """Read CHANGELOG.md content."""
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        _fail("CHANGELOG.md not found")
    return changelog.read_text(encoding="utf-8")


def _extract_version_notes(changelog: str, version: str) -> str:
    """Extract release notes for a specific version from changelog."""
    # Match ## [X.Y.Z] - YYYY-MM-DD or ## [X.Y.Z]
    pattern = rf"## \[{re.escape(version)}\][^\n]*\n"
    match = re.search(pattern, changelog)
    if not match:
        return f"Release v{version}"

    start = match.end()
    # Find next ## heading
    next_heading = re.search(r"\n## \[", changelog[start:])
    end = start + next_heading.start() if next_heading else len(changelog)

    return changelog[start:end].strip()


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


def _phase1_preflight(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 1: Pre-flight checks."""
    console.print("\n[bold]Phase 1: Pre-flight[/bold]")

    # 1a. Git state
    branch = _run(
        ["git", "branch", "--show-current"], cwd=str(info.root)
    ).stdout.strip()
    if branch != "main":
        _fail(f"Must be on main branch (currently on '{branch}')")
    _ok("On main branch")

    status = _run(["git", "status", "--porcelain"], cwd=str(info.root)).stdout.strip()
    if status:
        _fail(f"Working tree is not clean:\n{status}")
    _ok("Working tree clean (no modified or untracked files)")

    fetch = _run(["git", "fetch", "origin"], cwd=str(info.root), check=False)
    if fetch.returncode != 0:
        _fail(f"git fetch origin failed:\n{fetch.stderr.strip()}")
    diff = _run(
        ["git", "diff", "HEAD", "origin/main", "--stat"],
        cwd=str(info.root),
        check=False,
    )
    if diff.returncode != 0:
        _fail(f"git diff failed:\n{diff.stderr.strip()}")
    if diff.stdout.strip():
        _fail(f"Not up to date with origin/main:\n{diff.stdout.strip()}")
    _ok("Up to date with origin/main")

    # 1b. Project type (already detected)
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"
    _ok(f"Project type: {ptype}")

    if info.is_hybrid:
        release_script = info.root / "scripts" / "release-plugin.sh"
        restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
        if not release_script.exists() or not restore_script.exists():
            _fail("Missing release-plugin.sh or restore-dev-plugin.sh")
        _ok("Release/restore scripts present")

    # 1c. Changelog check
    changelog = _read_changelog(info.root)
    if "## [Unreleased]" not in changelog:
        _fail("No [Unreleased] section in CHANGELOG.md")

    unreleased_match = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased_match or not unreleased_match.group(1).strip():
        _fail("[Unreleased] section is empty — nothing to release")
    _ok("Changelog has unreleased entries")

    # 1d. Quality gates
    if not dry_run and info.language == "python":
        _info("Running quality gates...")
        gates = [
            ["uv", "run", "ruff", "check", "src/", "tests/"],
            ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
            ["uv", "run", "mypy", "src/", "tests/"],
            ["uv", "run", "pyright", "src/", "tests/"],
            ["uv", "run", "pytest", "tests/", "-v"],
        ]
        for gate in gates:
            result = _run(gate, cwd=str(info.root), check=False, capture=False)
            if result.returncode != 0:
                _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif dry_run:
        _dry("Would run quality gates")


def _suggest_version(changelog: str, current: str) -> str:
    """Suggest a version bump based on changelog content."""
    unreleased = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased:
        return current

    content = unreleased.group(1)
    parts = current.split(".")
    if len(parts) != 3:
        return current

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    # Check for breaking changes only within the ### Changed subsection
    changed_match = re.search(r"### Changed\n(.*?)(?=\n### |\Z)", content, re.DOTALL)
    has_breaking = (
        changed_match is not None and "breaking" in changed_match.group(1).lower()
    )
    if has_breaking:
        return f"{major + 1}.0.0"
    if "### Added" in content:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _phase2_version_bump(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 2: Bump version in all locations."""
    console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

    root = info.root

    # 2b. Bump version in pyproject.toml
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(version\s*=\s*")[^"]*(")',
            rf"\g<1>{version}\2",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if dry_run:
            _dry(f'pyproject.toml: version = "{version}"')
        else:
            pyproject_path.write_text(new_content, encoding="utf-8")
            _ok(f'pyproject.toml: version = "{version}"')

    # Bump __init__.py __version__
    pkg_dir = _find_package_dir(info)
    if pkg_dir is not None:
        init_py = pkg_dir / "__init__.py"
        if init_py.exists():
            content = init_py.read_text(encoding="utf-8")
            if "__version__" in content:
                new_content = re.sub(
                    r'^(__version__\s*=\s*")[^"]*(")',
                    rf"\g<1>{version}\2",
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                if dry_run:
                    _dry(f'{init_py.name}: __version__ = "{version}"')
                else:
                    init_py.write_text(new_content, encoding="utf-8")
                    _ok(f'{init_py.name}: __version__ = "{version}"')

    # Bump plugin.json version
    plugin_json = root / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        data["version"] = version
        if dry_run:
            _dry(f'plugin.json: version = "{version}"')
        else:
            plugin_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            _ok(f'plugin.json: version = "{version}"')

    # 2c. Update CHANGELOG.md
    changelog_path = root / "CHANGELOG.md"
    if changelog_path.exists():
        today = datetime.date.today().isoformat()
        content = changelog_path.read_text(encoding="utf-8")
        new_content = content.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n## [{version}] - {today}",
            1,
        )
        if dry_run:
            _dry(f"CHANGELOG.md: [Unreleased] → [{version}] - {today}")
        else:
            changelog_path.write_text(new_content, encoding="utf-8")
            _ok(f"CHANGELOG.md: [{version}] - {today}")

    # 2d. Commit
    if dry_run:
        _dry(f'git commit -m "chore: release v{version}"')
    else:
        _run(["git", "add", "-A"], cwd=str(root))
        _run(
            ["git", "commit", "-m", f"chore: release v{version}"],
            cwd=str(root),
        )
        _ok("Release commit created")


def _phase3_build(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 3: Build validation."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 3: Build validation[/bold]")

    if dry_run:
        _dry("rm -rf dist/ && uv build && uvx twine check dist/*")
        return

    dist = info.root / "dist"
    if dist.exists():
        shutil.rmtree(dist)

    _run(["uv", "build"], cwd=str(info.root), capture=False)

    # twine check on built artifacts only (.whl and .tar.gz)
    dist_dir = info.root / "dist"
    artifacts = sorted(p for p in dist_dir.iterdir() if p.suffix in {".whl", ".gz"})
    if not artifacts:
        _fail("No build artifacts found in dist/ for twine check")

    result = _run(
        ["uvx", "twine", "check", *[str(p) for p in artifacts]],
        cwd=str(info.root),
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        _fail(f"twine check failed:\n{result.stdout}\n{result.stderr}")
    _ok("Build artifacts pass twine check")


def _phase4_tag_push(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 4: Plugin swap, tag, push, restore."""
    console.print(f"\n[bold]Phase 4: Tag and push v{version}[/bold]")

    root = info.root

    # 4a. Plugin swap (hybrid only)
    if info.is_hybrid:
        release_script = root / "scripts" / "release-plugin.sh"
        if dry_run:
            _dry("bash scripts/release-plugin.sh")
        else:
            _run(["bash", str(release_script)], cwd=str(root), capture=False)
            _ok("Plugin swapped to prod")

    # 4b. Tag
    tag = f"v{version}"
    if dry_run:
        _dry(f"git tag {tag}")
    else:
        _run(["git", "tag", tag], cwd=str(root))
        _ok(f"Tagged {tag}")

    # 4c. Push
    if dry_run:
        _dry(f"git push origin main {tag}")
    else:
        console.print(
            f"\n  [bold yellow]About to push main + {tag} to origin[/bold yellow]"
        )
        _run(["git", "push", "origin", "main", tag], cwd=str(root), capture=False)
        _ok("Pushed to origin")

    # 4d. Restore dev state (hybrid only)
    if info.is_hybrid:
        restore_script = root / "scripts" / "restore-dev-plugin.sh"
        if dry_run:
            _dry("bash scripts/restore-dev-plugin.sh && git push origin main")
        else:
            _run(["bash", str(restore_script)], cwd=str(root), capture=False)
            _run(["git", "push", "origin", "main"], cwd=str(root), capture=False)
            _ok("Dev plugin state restored and pushed")


def _phase5_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 5: Wait for CI."""
    console.print("\n[bold]Phase 5: Wait for CI[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry("gh run list --branch main --limit 5")
        _dry("gh run watch <run-id>")
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found — install from https://cli.github.com")

    # Find the run triggered by the tag push
    _info(f"Looking for CI run triggered by {tag}...")

    # Give CI a moment to start
    import time

    time.sleep(5)

    # Try release workflow first, fall back to any recent run
    release_run = None
    runs: list[dict[str, object]] = []
    for workflow in ["release.yml", ""]:
        cmd = [
            gh,
            "run",
            "list",
            "--limit",
            "3",
            "--json",
            "databaseId,headBranch,event,status,name",
        ]
        if workflow:
            cmd.extend(["--workflow", workflow])
        result = _run(cmd, cwd=str(info.root), check=False)
        if result.returncode != 0:
            continue
        runs = json.loads(result.stdout)
        if runs:
            release_run = runs[0]
            break

    if release_run is None:
        _info("No release workflow run found — checking for any recent run...")
        if runs:
            release_run = runs[0]

    if release_run is None:
        _fail("No CI runs found")

    run_id = release_run["databaseId"]
    _info(f"Watching run {run_id} ({release_run.get('name', 'unknown')})...")

    result = _run(
        [gh, "run", "watch", str(run_id), "--exit-status"],
        cwd=str(info.root),
        check=False,
        capture=False,
        timeout=7200,
    )
    if result.returncode != 0:
        _fail(f"CI run {run_id} failed — fix before continuing")
    _ok("CI passed")


def _phase6_github_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 6: Create GitHub release."""
    console.print(f"\n[bold]Phase 6: GitHub release v{version}[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry(f'gh release create {tag} --title "{tag}" --notes "..."')
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found")

    changelog = _read_changelog(info.root)
    notes = _extract_version_notes(changelog, version)

    result = _run(
        [gh, "release", "create", tag, "--title", tag, "--notes", notes],
        cwd=str(info.root),
        check=False,
    )
    if result.returncode != 0:
        _fail(f"Failed to create release: {result.stderr}")
    _ok(f"GitHub release {tag} created")


def _phase7_verify_pypi(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 7: Verify PyPI install."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 7: Verify PyPI install[/bold]")

    package_name = _get_package_name(info)

    if dry_run:
        _dry(f"uv tool install --force --refresh {package_name}=={version}")
        if info.cli_commands:
            _dry(f"{info.cli_commands[0]} doctor (if available)")
        _dry("uv tool install --force --editable .")
        return

    _info(f"Installing {package_name}=={version} from PyPI...")

    # Retry loop — PyPI propagation can take a minute
    for attempt in range(10):
        result = _run(
            [
                "uv",
                "tool",
                "install",
                "--force",
                "--refresh",
                f"{package_name}=={version}",
            ],
            cwd=str(info.root),
            check=False,
            capture=False,
        )
        if result.returncode == 0:
            break
        if attempt < 9:
            _info(f"Attempt {attempt + 1}/10 — waiting 30s for PyPI propagation...")
            import time

            time.sleep(30)
    else:
        _fail(
            f"Failed to install {package_name}=={version} from PyPI after 10 attempts"
        )

    _ok(f"Installed {package_name}=={version} from PyPI")

    # Run doctor if available
    if info.cli_commands:
        cli_name = info.cli_commands[0]
        cli_path = shutil.which(cli_name)
        if cli_path:
            doctor_result = _run([cli_path, "doctor"], check=False, capture=False)
            if doctor_result.returncode == 0:
                _ok(f"{cli_name} doctor passed")

    # Restore editable install
    _info("Restoring editable install...")
    _run(
        ["uv", "tool", "install", "--force", "--editable", "."],
        cwd=str(info.root),
        capture=False,
    )
    _ok("Editable install restored")


def _trigger_and_wait(
    gh: str, target_repo: str, fields: list[tuple[str, str]], label: str
) -> bool:
    """Trigger a propagation workflow and wait for it to complete.

    Returns True on success, False on failure (non-fatal).
    """
    cmd = [gh, "workflow", "run", "propagate.yml", "-R", target_repo]
    for key, val in fields:
        cmd.extend(["-f", f"{key}={val}"])

    result = _run(cmd, check=False)
    if result.returncode != 0:
        _info(f"{label}: workflow not available ({result.stderr.strip()})")
        return False

    _ok(f"{label}: triggered")

    import time

    time.sleep(5)

    result = _run(
        [
            gh,
            "run",
            "list",
            "-R",
            target_repo,
            "--workflow=propagate.yml",
            "--limit",
            "1",
            "--json",
            "databaseId,status",
        ],
        check=False,
    )
    if result.returncode != 0:
        _info(f"{label}: could not find run — check manually")
        return False

    runs = json.loads(result.stdout)
    if not runs:
        _info(f"{label}: no runs found — check manually")
        return False

    run_id = runs[0]["databaseId"]
    _info(f"{label}: watching run {run_id}...")
    watch = _run(
        [gh, "run", "watch", str(run_id), "--exit-status", "-R", target_repo],
        check=False,
        capture=False,
        timeout=7200,
    )
    if watch.returncode != 0:
        _info(f"{label}: run {run_id} failed")
        return False

    _ok(f"{label}: complete")
    return True


def _phase8_trigger_propagation(
    info: ProjectInfo, version: str, *, dry_run: bool
) -> None:
    """Phase 8: Trigger cross-repo propagation Actions and wait."""
    if not info.is_plugin and info.language != "python":
        return

    console.print("\n[bold]Phase 8: Cross-repo propagation[/bold]")

    repo = _get_github_repo(info.root)
    if repo is None:
        _info("No GitHub remote detected — skipping propagation")
        return

    tag = f"v{version}"

    # Determine which propagations apply
    # 1. punt-kit: update install-all.sh SHAs (any CLI project)
    # 2. claude-plugins: update marketplace.json (any plugin project)
    # 3. .github: update profile README install-all.sh URL (punt-kit only)
    targets: list[tuple[str, list[tuple[str, str]], str]] = []

    targets.append(
        (
            "punt-labs/punt-kit",
            [("repo", repo), ("tag", tag)],
            "install-all.sh",
        )
    )

    if info.is_plugin or info.is_hybrid:
        targets.append(
            (
                "punt-labs/claude-plugins",
                [("repo", repo), ("version", version), ("tag", tag)],
                "marketplace",
            )
        )

    if repo == "punt-labs/punt-kit":
        targets.append(
            (
                "punt-labs/.github",
                [("repo", repo), ("tag", tag)],
                "org profile README",
            )
        )

    if dry_run:
        for target_repo, fields, _label in targets:
            field_str = " ".join(f"-f {k}={v}" for k, v in fields)
            _dry(f"gh workflow run propagate.yml -R {target_repo} {field_str}")
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found")

    failures: list[str] = []
    for target_repo, fields, label in targets:
        if not _trigger_and_wait(gh, target_repo, fields, label):
            failures.append(label)

    if failures:
        _info(f"Some propagations need manual attention: {', '.join(failures)}")
    else:
        _ok("All propagations complete")


def _phase_summary(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Print release summary."""
    tag = f"v{version}"
    package = _get_package_name(info) if info.language == "python" else info.root.name
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"

    dr = "(dry run) " if dry_run else ""
    console.print(f"\n[bold green]Release {tag} {dr}Complete[/bold green]\n")
    console.print(f"  Package:        {package}")
    console.print(f"  Version:        {version}")
    console.print(f"  Type:           {ptype}")
    console.print(f"  Tag:            {tag}")

    if info.language == "python" and not dry_run:
        pypi = "✓"
    elif info.language != "python":
        pypi = "N/A"
    else:
        pypi = "skipped (dry run)"
    console.print(f"  PyPI:           {pypi}")

    gh_status = "✓" if not dry_run else "skipped (dry run)"
    console.print(f"  GitHub Release: {gh_status}")

    has_propagation = info.is_plugin or info.language == "python"
    if has_propagation and not dry_run:
        prop = "✓ (install-all.sh"
        if info.is_plugin or info.is_hybrid:
            prop += " + marketplace"
        repo = _get_github_repo(info.root)
        if repo == "punt-labs/punt-kit":
            prop += " + org profile"
        prop += ")"
    elif not has_propagation:
        prop = "N/A"
    else:
        prop = "skipped (dry run)"
    console.print(f"  Propagation:    {prop}")
    console.print()
    if not dry_run:
        console.print("  Restart Claude Code to pick up marketplace changes.")
    console.print()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_release(
    path: str,
    *,
    version: str | None = None,
    dry_run: bool = False,
) -> None:
    """Execute the release workflow.

    Phases 1-7 run locally. Phase 8 triggers a GitHub Action for cross-repo
    propagation and waits for it to complete.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        _fail(f"{root} is not a directory")

    info = detect(root)

    if info.language is None and not info.is_plugin:
        _fail("Cannot detect project type — is this a Punt Labs project?")

    mode = "[bold yellow]DRY RUN[/bold yellow] — " if dry_run else ""
    console.print(f"\n{mode}[bold]punt release[/bold] — {root.name}")

    # Phase 1: Pre-flight
    _phase1_preflight(info, dry_run=dry_run)

    # Determine version
    if version is None:
        if info.pyproject is None:
            _fail("Version required for plugin-only projects (no pyproject.toml)")
        current = _get_project_version(info)
        changelog = _read_changelog(root)
        version = _suggest_version(changelog, current)
        console.print(
            f"\n  [bold]Suggested version:[/bold] {version} (current: {current})"
        )
        if not dry_run:
            # In CLI mode, we use the suggestion. The plugin wrapper can
            # override via AskUserQuestion if needed.
            _info(f"Using suggested version {version}")

    # Phase 2: Version bump
    _phase2_version_bump(info, version, dry_run=dry_run)

    # Phase 3: Build
    _phase3_build(info, dry_run=dry_run)

    # Phase 4: Tag and push
    _phase4_tag_push(info, version, dry_run=dry_run)

    # Phase 5: CI wait
    _phase5_ci_wait(info, version, dry_run=dry_run)

    # Phase 6: GitHub release
    _phase6_github_release(info, version, dry_run=dry_run)

    # Phase 7: Verify PyPI
    _phase7_verify_pypi(info, version, dry_run=dry_run)

    # Phase 8: Cross-repo propagation
    _phase8_trigger_propagation(info, version, dry_run=dry_run)

    # Summary
    _phase_summary(info, version, dry_run=dry_run)
